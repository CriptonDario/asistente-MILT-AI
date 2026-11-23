"""Registro y ejecución de scripts autorizados (lista blanca con hash SHA-256)."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import uuid
from collections.abc import Sequence
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
DEFAULT_ARG_PATTERN = r"^[\w.,:@/\\ =+-]{0,200}$"
RUNNERS = {".py": "python", ".ps1": "powershell", ".exe": "exe"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


async def verify_integrity(script: AutomationScript) -> Path:
    """El archivo debe existir y conservar el hash registrado (si cambió, se bloquea)."""
    path = Path(script.path)
    if not path.is_file():
        raise ValidationAppError(f"El script «{script.name}» ya no existe en {script.path}.")
    current = await anyio.to_thread.run_sync(sha256_file, path)
    if current != script.sha256:
        raise ValidationAppError(
            f"El script «{script.name}» ha cambiado desde que se autorizó. Un administrador "
            "debe revisarlo y volver a autorizarlo."
        )
    return path


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
