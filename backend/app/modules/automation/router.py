"""Endpoints de herramientas, carpetas permitidas, scripts autorizados y reportes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.core.deps import (
    AdminDep,
    AuthDep,
    DbDep,
    StateDep,
    client_ip,
    require_local_profile,
)
from app.core.errors import NotFoundError, ValidationAppError
from app.modules.automation.models import SecurityReport, ToolExecution
from app.modules.automation.scripts import ScriptService
from app.modules.settings.service import get_or_create
from app.tools.base import Decision, ToolError
from app.tools.fs_guard import validate_root
from app.tools.policy import decide, validate_override

router = APIRouter(tags=["tools"])
LocalOnly = [Depends(require_local_profile)]


# ------------------------------------------------------------------ herramientas
class ToolOut(BaseModel):
    name: str
    description: str
    risk: str
    profiles: list[str]
    decision: Decision
    customized: bool
    needs_roots: bool


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: "default" elimina la preferencia y vuelve al comportamiento por riesgo.
    decision: Literal["auto", "confirm", "deny", "default"]


@router.get("/tools", response_model=list[ToolOut])
async def list_tools(db: DbDep, state: StateDep, auth: AuthDep) -> list[ToolOut]:
    prefs = await get_or_create(db, auth.user.id)
    await db.commit()
    policies = prefs.tool_policies or {}
    return [
        ToolOut(
            name=t.name,
            description=t.description,
            risk=t.risk.value,
            profiles=sorted(t.profiles),
            decision=decide(t, policies, remote=False),
            customized=t.name in policies,
            needs_roots=t.needs_roots,
        )
        for t in state.tools.all()
    ]


@router.put("/tools/policies/{name}", response_model=ToolOut, dependencies=LocalOnly)
async def update_policy(
    name: str, body: PolicyUpdate, request: Request, db: DbDep, state: StateDep, auth: AuthDep
) -> ToolOut:
    tool = state.tools.get(name)
    if tool is None:
        raise NotFoundError("Herramienta no encontrada.")
    prefs = await get_or_create(db, auth.user.id)
    policies = dict(prefs.tool_policies or {})
    if body.decision == "default":
        policies.pop(name, None)
    else:
        decision = Decision(body.decision)
        validate_override(tool, decision)
        policies[name] = decision.value
    prefs.tool_policies = policies
    await db.commit()
    await state.audit.record(
        "tool.policy_change",
        user_id=auth.user.id,
        target_type="tool",
        target_id=name,
        ip=client_ip(request),
        details={"decision": body.decision},
    )
    return ToolOut(
        name=tool.name,
        description=tool.description,
        risk=tool.risk.value,
        profiles=sorted(tool.profiles),
        decision=decide(tool, policies, remote=False),
        customized=name in policies,
        needs_roots=tool.needs_roots,
    )


class ExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID | None
    tool_name: str
    arguments: dict[str, Any] | None
    risk_level: str
    decision: str
    status: str
    result_summary: str | None
    duration_ms: int | None
    created_at: datetime


@router.get("/tools/executions", response_model=list[ExecutionOut])
async def list_executions(
    db: DbDep, auth: AuthDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[ExecutionOut]:
    rows = (
        await db.scalars(
            select(ToolExecution)
            .where(ToolExecution.user_id == auth.user.id)
            .order_by(ToolExecution.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [ExecutionOut.model_validate(r) for r in rows]


# ------------------------------------------------------------------ carpetas permitidas
class AllowedRoots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roots: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(max_length=20)


@router.get("/settings/allowed-roots", response_model=AllowedRoots)
async def get_allowed_roots(db: DbDep, auth: AuthDep) -> AllowedRoots:
    prefs = await get_or_create(db, auth.user.id)
    await db.commit()
    return AllowedRoots(roots=prefs.allowed_roots or [])


@router.put("/settings/allowed-roots", response_model=AllowedRoots, dependencies=LocalOnly)
async def set_allowed_roots(
    body: AllowedRoots, request: Request, db: DbDep, state: StateDep, auth: AuthDep
) -> AllowedRoots:
    """Carpetas a las que pueden acceder las herramientas (solo en el equipo local)."""
    validated: list[str] = []
    for raw in body.roots:
        try:
            path = str(validate_root(raw, data_dir=state.settings.data_dir))
        except ToolError as exc:
            raise ValidationAppError(f"{raw}: {exc.detail}") from exc
        if path not in validated:
            validated.append(path)
    prefs = await get_or_create(db, auth.user.id)
    prefs.allowed_roots = validated
    await db.commit()
    await state.audit.record(
        "tool.allowed_roots_change",
        user_id=auth.user.id,
        ip=client_ip(request),
        details={"roots": validated},
    )
    return AllowedRoots(roots=validated)


# ------------------------------------------------------------------ scripts autorizados
class ScriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    path: str
    sha256: str
    runner: str
    arg_pattern: str
    max_args: int
    timeout_seconds: int
    created_at: datetime


class ScriptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=r"^[a-z0-9_-]{1,64}$")]
    path: Annotated[str, Field(min_length=3, max_length=1000)]
    description: Annotated[str, Field(max_length=500)] = ""
    arg_pattern: Annotated[str, Field(max_length=200)] | None = None
    max_args: int = Field(default=0, ge=0, le=20)
    timeout_seconds: int = Field(default=60, ge=1)


@router.get("/automation/scripts", response_model=list[ScriptOut], dependencies=LocalOnly)
async def list_scripts(db: DbDep, state: StateDep, _auth: AuthDep) -> list[ScriptOut]:
    scripts = await ScriptService(db, state.settings).list_scripts()
    return [ScriptOut.model_validate(s) for s in scripts]


@router.post(
    "/automation/scripts",
    response_model=ScriptOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=LocalOnly,
)
async def register_script(
    body: ScriptCreate, request: Request, db: DbDep, state: StateDep, admin: AdminDep
) -> ScriptOut:
    """Solo administradores: autoriza un script por ruta y hash (lista blanca)."""
    script = await ScriptService(db, state.settings).register(
        name=body.name,
        path=body.path,
        description=body.description,
        arg_pattern=body.arg_pattern,
        max_args=body.max_args,
        timeout_seconds=body.timeout_seconds,
        created_by=admin.user.id,
    )
    await state.audit.record(
        "script.register",
        user_id=admin.user.id,
        target_type="script",
        target_id=script.id,
        ip=client_ip(request),
        details={"name": script.name, "path": script.path, "sha256": script.sha256},
    )
    return ScriptOut.model_validate(script)


@router.post(
    "/automation/scripts/{script_id}/reauthorize", response_model=ScriptOut, dependencies=LocalOnly
)
async def reauthorize_script(
    script_id: uuid.UUID, request: Request, db: DbDep, state: StateDep, admin: AdminDep
) -> ScriptOut:
    """Acepta la versión actual del archivo tras revisarla (recalcula el hash)."""
    script = await ScriptService(db, state.settings).reauthorize(script_id)
    await state.audit.record(
        "script.reauthorize",
        user_id=admin.user.id,
        target_type="script",
        target_id=script.id,
        ip=client_ip(request),
        details={"sha256": script.sha256},
    )
    return ScriptOut.model_validate(script)


@router.delete(
    "/automation/scripts/{script_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=LocalOnly,
)
async def delete_script(
    script_id: uuid.UUID, request: Request, db: DbDep, state: StateDep, admin: AdminDep
) -> None:
    await ScriptService(db, state.settings).delete(script_id)
    await state.audit.record(
        "script.delete",
        user_id=admin.user.id,
        target_type="script",
        target_id=script_id,
        ip=client_ip(request),
    )


# ------------------------------------------------------------------ reportes
class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    severity: str
    conversation_id: uuid.UUID | None
    created_at: datetime


class ReportOut(ReportSummary):
    content: str


async def _get_report(db: DbDep, user_id: uuid.UUID, report_id: uuid.UUID) -> SecurityReport:
    report = await db.scalar(
        select(SecurityReport).where(
            SecurityReport.id == report_id, SecurityReport.user_id == user_id
        )
    )
    if report is None:
        raise NotFoundError("Reporte no encontrado.")
    return report


@router.get("/security/reports", response_model=list[ReportSummary])
async def list_reports(db: DbDep, auth: AuthDep) -> list[ReportSummary]:
    rows = (
        await db.scalars(
            select(SecurityReport)
            .where(SecurityReport.user_id == auth.user.id)
            .order_by(SecurityReport.created_at.desc())
            .limit(200)
        )
    ).all()
    return [ReportSummary.model_validate(r) for r in rows]


@router.get("/security/reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: uuid.UUID, db: DbDep, auth: AuthDep) -> ReportOut:
    return ReportOut.model_validate(await _get_report(db, auth.user.id, report_id))


@router.get("/security/reports/{report_id}/markdown")
async def download_report(report_id: uuid.UUID, db: DbDep, auth: AuthDep) -> PlainTextResponse:
    report = await _get_report(db, auth.user.id, report_id)
    return PlainTextResponse(
        f"# {report.title}\n\n"
        f"_Severidad: {report.severity} · {report.created_at:%Y-%m-%d %H:%M} UTC_\n\n"
        f"{report.content}\n",
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="reporte-{report.id}.md"'},
    )


@router.delete("/security/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: uuid.UUID, db: DbDep, auth: AuthDep) -> None:
    await _get_report(db, auth.user.id, report_id)
    await db.execute(
        delete(SecurityReport).where(
            SecurityReport.id == report_id, SecurityReport.user_id == auth.user.id
        )
    )
    await db.commit()
