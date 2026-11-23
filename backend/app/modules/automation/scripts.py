"""Registro y ejecución de scripts autorizados (lista blanca con hash SHA-256)."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import anyio.to_thread
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.automation.models import AutomationScript
from app.tools.fs_guard import check_sensitive

#: Por defecto: letras, números y separadores comunes. Sin comillas, ; | & $ ` < > ( ).
#: Tampoco puede empezar por «-»: el script recibiría opciones en lugar de datos.
DEFAULT_ARG_PATTERN = r"^(?!-)[\w.,:@/\\ =+-]{0,200}$"
RUNNERS = {".py": "python", ".ps1": "powershell", ".exe": "exe"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _open_deny_write(path: Path) -> int:
    """Abre ``path`` impidiendo que nadie lo modifique, renombre o borre mientras siga abierto.

    Windows: ``CreateFileW`` con ``FILE_SHARE_READ`` solamente. El intérprete puede leer
    el script, pero ningún otro proceso puede cambiarlo entre la verificación del hash y
    la ejecución (TOCTOU). Devuelve un descriptor que hay que cerrar con ``os.close``.
    """
    if sys.platform != "win32":
        return os.open(path, os.O_RDONLY)
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    generic_read, file_share_read, open_existing, attribute_normal = 0x80000000, 1, 3, 0x80
    handle = kernel32.CreateFileW(
        str(path), generic_read, file_share_read, None, open_existing, attribute_normal, None
    )
    if handle is None or handle == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        if error == 32:  # ERROR_SHARING_VIOLATION
            raise ValidationAppError(
                "El script está abierto para escritura por otro programa; ciérralo y reintenta."
            )
        raise ValidationAppError(f"No se pudo abrir el script (error {error}).")
    # O_BINARY: sin él, os.read traduciría \r\n y el hash no coincidiría.
    return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)


@contextmanager
def locked_verified(script: AutomationScript) -> Iterator[Path]:
    """Bloquea el archivo, comprueba su hash y lo mantiene bloqueado mientras se ejecuta."""
    path = Path(script.path)
    if not path.is_file():
        raise ValidationAppError(f"El script «{script.name}» ya no existe en {script.path}.")
    fd = _open_deny_write(path)
    try:
        if _sha256_fd(fd) != script.sha256:
            raise ValidationAppError(
                f"El script «{script.name}» ha cambiado desde que se autorizó. Un administrador "
                "debe revisarlo y volver a autorizarlo."
            )
        yield path
    finally:
        os.close(fd)


def _powershell() -> str:
    if sys.platform == "win32":
        root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        candidate = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if candidate.exists():
            return str(candidate)
    found = shutil.which("pwsh") or shutil.which("powershell")
    if not found:
        raise ValidationAppError("PowerShell no está disponible en este equipo.")
    return found


def build_argv(script: AutomationScript, args: Sequence[str], settings: Settings) -> list[str]:
    """Línea de comandos como lista (sin shell). Las rutas son absolutas."""
    if script.runner == "python":
        python = shutil.which(settings.script_python) or settings.script_python
        # -I: modo aislado (ignora PYTHONPATH y el directorio de usuario).
        return [python, "-I", script.path, *args]
    if script.runner == "powershell":
        return [
            _powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script.path,
            *args,
        ]
    return [script.path, *args]


def validate_args(script: AutomationScript, args: Sequence[str]) -> None:
    if len(args) > script.max_args:
        raise ValidationAppError(
            f"El script «{script.name}» admite como máximo {script.max_args} argumentos."
        )
    pattern = re.compile(script.arg_pattern)
    for arg in args:
        if not pattern.fullmatch(arg):
            raise ValidationAppError(f"Argumento no permitido para «{script.name}»: {arg[:60]!r}")


class ScriptService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def list_scripts(self) -> Sequence[AutomationScript]:
        return (
            await self.db.scalars(select(AutomationScript).order_by(AutomationScript.name))
        ).all()

    async def get_by_name(self, name: str) -> AutomationScript | None:
        stmt = select(AutomationScript).where(AutomationScript.name == name)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get(self, script_id: uuid.UUID) -> AutomationScript:
        script = await self.db.get(AutomationScript, script_id)
        if script is None:
            raise NotFoundError("Script no encontrado.")
        return script

    async def register(
        self,
        *,
        name: str,
        path: str,
        description: str,
        arg_pattern: str | None,
        max_args: int,
        timeout_seconds: int,
        created_by: uuid.UUID,
    ) -> AutomationScript:
        file = Path(path).expanduser()
        if not file.is_absolute():
            raise ValidationAppError("Indica la ruta absoluta del script.")
        try:
            resolved = file.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ValidationAppError(f"No existe: {path}") from exc
        if not resolved.is_file():
            raise ValidationAppError("La ruta no es un archivo.")
        runner = RUNNERS.get(resolved.suffix.lower())
        if runner is None:
            raise ValidationAppError(
                "Solo se admiten scripts .py, .ps1 o ejecutables .exe (los .bat/.cmd pasan "
                "por cmd.exe y permitirían inyectar comandos)."
            )
        check_sensitive(resolved)
        if timeout_seconds > self.settings.script_max_timeout_seconds:
            raise ValidationAppError(
                f"El tiempo máximo es {self.settings.script_max_timeout_seconds} s."
            )
        pattern = arg_pattern or DEFAULT_ARG_PATTERN
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValidationAppError(f"Patrón de argumentos no válido: {exc}") from exc

        script = AutomationScript(
            name=name,
            description=description,
            path=str(resolved),
            sha256=await anyio.to_thread.run_sync(sha256_file, resolved),
            runner=runner,
            arg_pattern=pattern,
            max_args=max_args,
            timeout_seconds=timeout_seconds,
            created_by=created_by,
        )
        self.db.add(script)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError(f"Ya existe un script llamado «{name}».") from exc
        return script

    async def reauthorize(self, script_id: uuid.UUID) -> AutomationScript:
        """Acepta la versión actual del archivo (tras revisarla) recalculando su hash."""
        script = await self.get(script_id)
        path = Path(script.path)
        if not path.is_file():
            raise ValidationAppError("El archivo ya no existe.")
        script.sha256 = await anyio.to_thread.run_sync(sha256_file, path)
        await self.db.commit()
        return script

    async def delete(self, script_id: uuid.UUID) -> None:
        script = await self.get(script_id)
        await self.db.delete(script)
        await self.db.commit()
