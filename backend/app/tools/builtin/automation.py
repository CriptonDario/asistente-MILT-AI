"""Herramienta de automatización: ejecutar un script autorizado (siempre con confirmación)."""

from __future__ import annotations

from typing import Annotated, ClassVar

import anyio.to_thread
from pydantic import Field

from app.core.errors import ValidationAppError
from app.modules.automation.scripts import (
    ScriptService,
    build_argv,
    validate_args,
    verify_integrity,
)
from app.tools.base import RiskLevel, Tool, ToolArgs, ToolContext, ToolError, ToolResult, truncate
from app.tools.sandbox import run_sandboxed


class ScriptRunArgs(ToolArgs):
    name: Annotated[
        str, Field(pattern=r"^[a-z0-9_-]{1,64}$", description="Nombre del script autorizado")
    ]
    args: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=20, description="Argumentos del script"
    )


class ScriptRunTool(Tool[ScriptRunArgs]):
    name = "script_run"
    description = (
        "Ejecuta uno de los scripts que el administrador ha autorizado (por su nombre). "
        "Requiere siempre la confirmación del usuario."
    )
    risk = RiskLevel.EXECUTE
    Args = ScriptRunArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"coder", "security"})

    def describe(self, args: ScriptRunArgs) -> str:
        shown = " ".join(args.args) if args.args else "(sin argumentos)"
        return f"Ejecutar el script «{args.name}» {shown}"

    async def run(self, args: ScriptRunArgs, ctx: ToolContext) -> ToolResult:
        settings = ctx.state.settings
        if settings.profile != "local":
            raise ToolError("La ejecución de scripts solo está disponible en el equipo local.")
        async with ctx.state.sessionmaker() as db:
            service = ScriptService(db, settings)
            script = await service.get_by_name(args.name)
            if script is None:
                names = ", ".join(s.name for s in await service.list_scripts()) or "ninguno"
                raise ToolError(f"No existe el script «{args.name}». Autorizados: {names}.")
        try:
            validate_args(script, args.args)
            path = await verify_integrity(script)
            argv = build_argv(script, args.args, settings)
        except ValidationAppError as exc:
            raise ToolError(exc.detail or exc.title) from exc

        result = await anyio.to_thread.run_sync(
            lambda: run_sandboxed(
                argv,
                cwd=path.parent,
                timeout=float(script.timeout_seconds),
                memory_mb=settings.script_memory_mb,
            )
        )
        if result.timed_out:
            status = f"cancelado tras {script.timeout_seconds} s"
        elif result.killed_by_limit:
            status = f"detenido por superar {settings.script_memory_mb} MB de memoria"
        else:
            status = f"código de salida {result.exit_code}"
        body = [f"Script «{script.name}»: {status} ({result.duration_ms} ms)."]
        if result.stdout.strip():
            body.append("Salida:\n" + result.stdout.strip())
        if result.stderr.strip():
            body.append("Errores:\n" + result.stderr.strip()[-2000:])
        if result.truncated:
            body.append("(salida recortada)")
        return ToolResult(content=truncate("\n\n".join(body)), summary=f"«{script.name}»: {status}")
