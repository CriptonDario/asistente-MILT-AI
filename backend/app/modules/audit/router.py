"""Consulta del registro de auditoría."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.deps import AuthDep, DbDep, StateDep, require_permission
from app.core.errors import ForbiddenError
from app.modules.audit.models import AuditLog
from app.modules.auth.context import AuthContext
from app.security.rbac import Permission, has_permission

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    ip: str | None
    details: dict[str, Any] | None
    created_at: datetime


class AuditVerifyOut(BaseModel):
    valid: bool
    checked: int
    broken_at_id: int | None


@router.get("", response_model=list[AuditEntryOut])
async def list_audit(
    db: DbDep,
    auth: AuthDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    user_id: uuid.UUID | None = None,
) -> list[AuditEntryOut]:
    """Los usuarios ven sus propios eventos; los administradores pueden filtrar por usuario."""
    is_admin = has_permission(auth.user.role, Permission.AUDIT_READ_ALL)
    if user_id is not None and user_id != auth.user.id and not is_admin:
        raise ForbiddenError("Solo puedes consultar tus propios eventos.")
    stmt = select(AuditLog)
    if not is_admin:
        stmt = stmt.where(AuditLog.user_id == auth.user.id)
    elif user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if before_id:
        stmt = stmt.where(AuditLog.id < before_id)
    rows = (await db.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit))).all()
    return [AuditEntryOut.model_validate(r) for r in rows]


@router.get("/verify", response_model=AuditVerifyOut)
async def verify_audit(
    state: StateDep,
    _admin: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ_ALL))],
) -> AuditVerifyOut:
    """Comprueba la integridad de la cadena de hashes del registro."""
    result = await state.audit.verify_chain()
    return AuditVerifyOut(
        valid=result.valid, checked=result.checked, broken_at_id=result.broken_at_id
    )
