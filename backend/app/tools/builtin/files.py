"""Herramientas de archivos y código: listar, leer, árbol de proyecto, buscar y escribir."""

from __future__ import annotations

import fnmatch
import os
import secrets
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, ClassVar

import anyio.to_thread
import regex
from pydantic import ConfigDict, Field

from app.modules.documents.parsers import decode_text
from app.tools.base import RiskLevel, Tool, ToolArgs, ToolContext, ToolError, ToolResult, truncate
from app.tools.fs_guard import FsGuard

MAX_READ_BYTES = 2 * 1024 * 1024
MIN_READ_LINES = 50
MAX_WRITE_CHARS = 200_000
MAX_LIST_ENTRIES = 300
MAX_TREE_ENTRIES = 400
MAX_SEARCH_FILES = 5000
MAX_SEARCH_MATCHES = 150
MAX_SEARCH_FILE_BYTES = 1024 * 1024
MAX_SEARCH_LINE_CHARS = 2000
#: Tiempo máximo de una búsqueda por línea y de la búsqueda completa. Las expresiones
#: regulares las escribe el modelo: una catastrófica, p. ej. ``(a|aa)+$``, no debe
#: bloquear el servidor (``regex`` acepta un ``timeout`` y libera el GIL).
REGEX_LINE_TIMEOUT = 0.25
SEARCH_BUDGET_SECONDS = 20.0
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        "target",
        "vendor",
        ".idea",
        ".vscode",
        ".next",
        ".nuxt",
        "bin",
        "obj",
        ".gradle",
    }
)
LANGUAGES = {
    ".py": "Python",
    ".php": "PHP",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".cs": "C#",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".vue": "Vue",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".cpp": "C++",
    ".rb": "Ruby",
    ".sh": "Shell",
    ".ps1": "PowerShell",
}

PathArg = Annotated[
    str, Field(min_length=1, max_length=1000, description="Ruta del archivo o carpeta")
]


def _guard(ctx: ToolContext) -> FsGuard:
    return FsGuard(ctx.allowed_roots, data_dir=ctx.state.settings.data_dir)


MAX_WALK_ENTRIES = 200_000


class TreeWalker:
    """Recorrido en profundidad, como ``os.walk`` pero más estricto.

    No sigue enlaces simbólicos ni *junctions* (``os.walk`` sí entra en las junctions de
    Windows, que pueden apuntar fuera de la carpeta autorizada o formar ciclos), salta
    ``SKIP_DIRS`` y (salvo ``skip_hidden=False``) las ocultas, y se detiene tras
    ``max_entries`` entradas.
    """

    def __init__(
        self, root: Path, *, max_entries: int = MAX_WALK_ENTRIES, skip_hidden: bool = True
    ) -> None:
        self.root = root
        self.skip_hidden = skip_hidden
        self.max_entries = max_entries
        self.visited = 0
        self.truncated = False

    def __iter__(self) -> Iterator[tuple[Path, list[str], list[str]]]:
        stack = [self.root]
        while stack:
            current = stack.pop()
            dirnames: list[str] = []
            filenames: list[str] = []
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        self.visited += 1
                        if self.visited > self.max_entries:
                            self.truncated = True
                            break
                        try:
                            if entry.is_symlink() or entry.is_junction():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                hidden = self.skip_hidden and entry.name.startswith(".")
                                if entry.name not in SKIP_DIRS and not hidden:
                                    dirnames.append(entry.name)
                            elif entry.is_file(follow_symlinks=False):
                                filenames.append(entry.name)
                        except OSError:
                            continue
            except OSError:
                continue
            dirnames.sort()
            filenames.sort()
            yield current, dirnames, filenames  # el llamador puede podar dirnames
            if self.truncated:
                return
            stack.extend(current / name for name in reversed(dirnames))


def _write_exclusive(path: Path, data: bytes) -> None:
    """Crea ``path`` (falla si ya existe, aunque sea un enlace) y escribe ``data``."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample[:8192]


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size //= 1024
    return f"{size} TB"


# ------------------------------------------------------------------ file_list
class FileListArgs(ToolArgs):
    path: PathArg


class FileListTool(Tool[FileListArgs]):
    name = "file_list"
    description = "Lista el contenido de una carpeta autorizada (nombres, tipo y tamaño)."
    risk = RiskLevel.READ
    Args = FileListArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"general", "coder", "security", "documents"})
    needs_roots = True

    def describe(self, args: FileListArgs) -> str:
        return f"Listar la carpeta {args.path}"

    async def run(self, args: FileListArgs, ctx: ToolContext) -> ToolResult:
        guard = _guard(ctx)
        folder = guard.resolve(args.path)
        if not folder.is_dir():
            raise ToolError("La ruta no es una carpeta.")

        def work() -> list[str]:
            lines = []
            entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            for entry in entries[:MAX_LIST_ENTRIES]:
                if entry.is_dir():
                    lines.append(f"[carpeta] {entry.name}/")
                else:
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        size = 0
                    lines.append(f"{entry.name} ({_human_size(size)})")
            if len(entries) > MAX_LIST_ENTRIES:
                lines.append(f"… y {len(entries) - MAX_LIST_ENTRIES} elementos más")
            return lines

        lines = await anyio.to_thread.run_sync(work)
        header = f"Contenido de {guard.display(folder)}:"
        return ToolResult(
            content=truncate("\n".join([header, *lines])),
            summary=f"{len(lines)} elementos en {guard.display(folder)}",
        )


# ------------------------------------------------------------------ file_read
class FileReadArgs(ToolArgs):
    path: PathArg
    start_line: int = Field(default=1, ge=1, description="Primera línea a leer")
    max_lines: int = Field(default=200, ge=1, le=600, description="Número máximo de líneas")


class FileReadTool(Tool[FileReadArgs]):
    name = "file_read"
    description = (
        "Lee un archivo de texto o código de una carpeta autorizada. Devuelve las líneas "
        "numeradas. Usa start_line para leer por partes un archivo largo."
    )
    risk = RiskLevel.READ
    Args = FileReadArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"general", "coder", "security", "documents"})
    needs_roots = True

    def describe(self, args: FileReadArgs) -> str:
        return f"Leer {args.path} (desde la línea {args.start_line})"

    async def run(self, args: FileReadArgs, ctx: ToolContext) -> ToolResult:
        guard = _guard(ctx)
        path = guard.resolve(args.path)
        if not path.is_file():
            raise ToolError("La ruta no es un archivo.")
        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            raise ToolError(f"El archivo es demasiado grande ({_human_size(size)}; máximo 2 MB).")
        data = await anyio.to_thread.run_sync(path.read_bytes)
        if _is_binary(data):
            raise ToolError("Es un archivo binario; solo se leen archivos de texto.")
        lines = decode_text(data).splitlines()
        start = args.start_line - 1
        # Los modelos pequeños a veces piden max_lines=1 por error (visto con qwen3:1.7b):
        # leer de más es inofensivo y leer de menos arruina la respuesta.
        count = max(args.max_lines, MIN_READ_LINES)
        chunk = lines[start : start + count]
        width = len(str(start + len(chunk)))
        numbered = [f"{start + i + 1:>{width}} | {line}" for i, line in enumerate(chunk)]
        tail = ""
        if start + len(chunk) < len(lines):
            tail = f"\n… (quedan {len(lines) - start - len(chunk)} líneas; usa start_line)"
        return ToolResult(
            content=truncate(
                f"{guard.display(path)} ({len(lines)} líneas)\n" + "\n".join(numbered) + tail
            ),
            summary=f"Leídas {len(chunk)} líneas de {guard.display(path)}",
        )


# ------------------------------------------------------------------ project_tree
class ProjectTreeArgs(ToolArgs):
    path: PathArg
    max_depth: int = Field(default=3, ge=1, le=6, description="Profundidad máxima")


class ProjectTreeTool(Tool[ProjectTreeArgs]):
    name = "project_tree"
    description = (
        "Muestra la estructura de carpetas de un proyecto y los lenguajes que usa "
        "(ignora node_modules, .git, venv, etc.)."
    )
    risk = RiskLevel.READ
    Args = ProjectTreeArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"general", "coder"})
    needs_roots = True

    def describe(self, args: ProjectTreeArgs) -> str:
        return f"Ver la estructura de {args.path}"

    async def run(self, args: ProjectTreeArgs, ctx: ToolContext) -> ToolResult:
        guard = _guard(ctx)
        root = guard.resolve(args.path)
        if not root.is_dir():
            raise ToolError("La ruta no es una carpeta.")

        def work() -> tuple[list[str], Counter[str], int]:
            lines: list[str] = []
            languages: Counter[str] = Counter()
            files = 0
            for current, dirnames, filenames in TreeWalker(root):
                depth = len(current.relative_to(root).parts)
                for name in filenames:
                    files += 1
                    language = LANGUAGES.get(Path(name).suffix.lower())
                    if language:
                        languages[language] += 1
                if depth >= args.max_depth:
                    dirnames[:] = []
                if len(lines) < MAX_TREE_ENTRIES:
                    indent = "  " * depth
                    lines.append(f"{indent}{current.name}/")
                    for name in filenames[:30]:
                        if len(lines) >= MAX_TREE_ENTRIES:
                            break
                        lines.append(f"{indent}  {name}")
                    if len(filenames) > 30:
                        lines.append(f"{indent}  … {len(filenames) - 30} archivos más")
                if files > 50_000:
                    break
            return lines, languages, files

        lines, languages, files = await anyio.to_thread.run_sync(work)
        stats = ", ".join(f"{lang}: {count}" for lang, count in languages.most_common(8))
        content = (
            f"Proyecto {guard.display(root)} — {files} archivos. Lenguajes: {stats or 'n/d'}\n"
        )
        content += "\n".join(lines)
        if len(lines) >= MAX_TREE_ENTRIES:
            content += "\n… (árbol recortado)"
        return ToolResult(
            content=truncate(content),
            summary=f"{files} archivos; {stats or 'sin código reconocido'}",
        )


# ------------------------------------------------------------------ code_search
class CodeSearchArgs(ToolArgs):
    query: Annotated[str, Field(min_length=1, max_length=200, description="Texto a buscar")]
    path: PathArg
    file_glob: str = Field(
        default="*", max_length=50, description="Filtro de archivos, p. ej. *.php"
    )
    regex: bool = Field(default=False, description="Interpretar query como expresión regular")
    case_sensitive: bool = False


class CodeSearchTool(Tool[CodeSearchArgs]):
    name = "code_search"
    description = (
        "Busca un texto (o expresión regular) en los archivos de una carpeta autorizada y "
        "devuelve las coincidencias con archivo y número de línea."
    )
    risk = RiskLevel.READ
    Args = CodeSearchArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"general", "coder", "security"})
    needs_roots = True

    def describe(self, args: CodeSearchArgs) -> str:
        return f"Buscar «{args.query}» en {args.path} ({args.file_glob})"

    async def run(self, args: CodeSearchArgs, ctx: ToolContext) -> ToolResult:
        guard = _guard(ctx)
        root = guard.resolve(args.path)
        flags = regex.V0 if args.case_sensitive else regex.V0 | regex.IGNORECASE
        try:
            pattern = regex.compile(args.query if args.regex else regex.escape(args.query), flags)
        except regex.error as exc:
            raise ToolError(f"Expresión regular no válida: {exc}") from exc

        def work() -> tuple[list[str], int, str]:
            matches: list[str] = []
            scanned = 0
            deadline = time.monotonic() + SEARCH_BUDGET_SECONDS
            single: list[tuple[Path, list[str], list[str]]] = [(root.parent, [], [root.name])]
            walker: Iterator[tuple[Path, list[str], list[str]]] | TreeWalker = (
                iter(single) if root.is_file() else TreeWalker(root)
            )
            for current, _dirnames, filenames in walker:
                for name in filenames:
                    if not fnmatch.fnmatch(name, args.file_glob):
                        continue
                    scanned += 1
                    if scanned > MAX_SEARCH_FILES:
                        return matches, scanned, "límite de archivos alcanzado"
                    try:
                        # Cada archivo se valida: un enlace simbólico dentro del proyecto
                        # podría apuntar fuera de las carpetas autorizadas.
                        path = guard.resolve(str(current / name))
                    except ToolError:
                        continue
                    try:
                        if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                            continue
                        data = path.read_bytes()
                    except OSError:
                        continue
                    if _is_binary(data):
                        continue
                    for number, line in enumerate(decode_text(data).splitlines(), start=1):
                        line = line[:MAX_SEARCH_LINE_CHARS]
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return matches, scanned, "tiempo de búsqueda agotado"
                        try:
                            found = pattern.search(
                                line, timeout=min(REGEX_LINE_TIMEOUT, remaining), concurrent=True
                            )
                        except TimeoutError:
                            return (
                                matches,
                                scanned,
                                "la expresión regular es demasiado costosa; simplifícala",
                            )
                        if found:
                            matches.append(f"{guard.display(path)}:{number}: {line.strip()[:240]}")
                            if len(matches) >= MAX_SEARCH_MATCHES:
                                return matches, scanned, "límite de coincidencias alcanzado"
            if isinstance(walker, TreeWalker) and walker.truncated:
                return matches, scanned, "carpeta demasiado grande, recorrido parcial"
            return matches, scanned, ""

        matches, scanned, stopped = await anyio.to_thread.run_sync(work)
        note = f" (búsqueda detenida: {stopped})" if stopped else ""
        if not matches:
            return ToolResult(
                content=(
                    f"Sin coincidencias para «{args.query}» ({scanned} archivos revisados){note}."
                ),
                summary="Sin coincidencias" + note,
            )
        extra = note
        return ToolResult(
            content=truncate(f"{len(matches)} coincidencias{extra}:\n" + "\n".join(matches)),
            summary=f"{len(matches)} coincidencias en {scanned} archivos",
        )


# ------------------------------------------------------------------ file_write
class FileWriteArgs(ToolArgs):
    # El contenido de un archivo se escribe tal cual (sin recortar espacios ni saltos).
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: PathArg
    content: Annotated[str, Field(max_length=MAX_WRITE_CHARS, description="Contenido completo")]
    overwrite: bool = Field(default=False, description="Permitir sobrescribir un archivo existente")


class FileWriteTool(Tool[FileWriteArgs]):
    name = "file_write"
    description = (
        "Crea (o, con overwrite=true, reemplaza) un archivo de texto en una carpeta autorizada. "
        "Siempre requiere la confirmación del usuario."
    )
    risk = RiskLevel.WRITE
    Args = FileWriteArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"coder"})
    needs_roots = True

    def describe(self, args: FileWriteArgs) -> str:
        action = "Sobrescribir" if args.overwrite else "Crear"
        lines = args.content.count("\n") + 1
        return f"{action} {args.path} ({len(args.content)} caracteres, {lines} líneas)"

    async def run(self, args: FileWriteArgs, ctx: ToolContext) -> ToolResult:
        guard = _guard(ctx)
        target = guard.resolve_for_write(args.path)
        if not target.parent.is_dir():
            raise ToolError("La carpeta de destino no existe.")
        existed = target.exists()
        if existed and not target.is_file():
            raise ToolError("La ruta existe y no es un archivo.")
        if existed and not args.overwrite:
            raise ToolError("El archivo ya existe; pide permiso para sobrescribirlo (overwrite).")

        def work() -> None:
            if existed:
                # Copia de seguridad antes de reemplazar. Si alguien dejó un enlace con el
                # nombre de la copia, se elimina el enlace (no se escribe a través de él).
                backup = target.with_name(target.name + ".milt.bak")
                if backup.is_symlink() or backup.is_junction():
                    backup.unlink()
                elif backup.exists() and not backup.is_file():
                    raise ToolError("La copia de seguridad .milt.bak no es un archivo.")
                backup.unlink(missing_ok=True)
                _write_exclusive(backup, target.read_bytes())
            # Nombre temporal aleatorio creado con O_EXCL: no se sigue ningún enlace preparado.
            temp = target.with_name(f".{target.name}.{secrets.token_hex(6)}.milt.tmp")
            # Sin traducir \n a \r\n en Windows (se respeta lo que pide el usuario).
            _write_exclusive(temp, args.content.encode("utf-8"))
            try:
                temp.replace(target)
            except BaseException:
                temp.unlink(missing_ok=True)
                raise

        await anyio.to_thread.run_sync(work)
        verb = "Reemplazado (copia en .milt.bak)" if existed else "Creado"
        return ToolResult(
            content=f"{verb}: {guard.display(target)} ({len(args.content)} caracteres).",
            summary=f"{verb}: {guard.display(target)}",
        )
