"""Registro de auditoría con hash encadenado."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONType, UTCDateTime, utcnow

# BIGINT en PostgreSQL; INTEGER en SQLite (necesario para el autoincremento del rowid).
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_user_created", "user_id", "created_at"),
        Index("ix_audit_log_action_created", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # Sin clave foránea a propósito: las columnas incluidas en el hash nunca deben
    # cambiar. Un ON DELETE SET NULL reescribiría las filas al borrar un usuario y
    # rompería la cadena (falsos positivos de manipulación).
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
