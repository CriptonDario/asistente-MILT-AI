"""Servicio de auditoría con hash encadenado (detección de manipulación)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import redact
from app.db.types import utcnow
from app.modules.audit.models import AuditLog

log = structlog.get_logger(__name__)

GENESIS_HASH = "0" * 64


def compute_entry_hash(prev_hash: str, entry: AuditLog) -> str:
    payload = {
        "prev": prev_hash,
        "user_id": str(entry.user_id) if entry.user_id else None,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "outcome": entry.outcome,
        "ip": entry.ip,
        "details": entry.details,
        "created_at": entry.created_at.isoformat(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class ChainVerification:
    valid: bool
    checked: int
    broken_at_id: int | None = None


class AuditService:
    """Escribe en su propia transacción para que la auditoría no dependa de la petición.

    IMPORTANTE: llamar a ``record`` después de hacer *commit* de la sesión de la
    petición, para no competir por el bloqueo de escritura de SQLite.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._lock = asyncio.Lock()

    async def record(
        self,
        action: str,
        *,
        user_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: str | uuid.UUID | None = None,
        outcome: str = "success",
        ip: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        try:
            async with self._lock, self._sessionmaker() as db:
                last = await db.scalar(
                    select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1)
                )
                prev_hash = last or GENESIS_HASH
                entry = AuditLog(
                    user_id=user_id,
                    action=action,
                    target_type=target_type,
                    target_id=str(target_id) if target_id is not None else None,
                    outcome=outcome,
                    ip=ip,
                    details=redact(details) if details else None,
                    prev_hash=prev_hash,
                    created_at=utcnow(),
                )
                entry.entry_hash = compute_entry_hash(prev_hash, entry)
                db.add(entry)
                await db.commit()
        except Exception:
            # La auditoría nunca debe romper la operación principal, pero sí quedar registrada.
            log.exception("audit_record_failed", action=action, outcome=outcome)

    async def verify_chain(self, *, batch_size: int = 500) -> ChainVerification:
        prev_hash = GENESIS_HASH
        checked = 0
        last_id = 0
        async with self._sessionmaker() as db:
            while True:
                rows = (
                    await db.scalars(
                        select(AuditLog)
                        .where(AuditLog.id > last_id)
                        .order_by(AuditLog.id)
                        .limit(batch_size)
                    )
                ).all()
                if not rows:
                    return ChainVerification(valid=True, checked=checked)
                for entry in rows:
                    if (
                        entry.prev_hash != prev_hash
                        or compute_entry_hash(prev_hash, entry) != entry.entry_hash
                    ):
                        return ChainVerification(
                            valid=False, checked=checked, broken_at_id=entry.id
                        )
                    prev_hash = entry.entry_hash
                    last_id = entry.id
                    checked += 1
