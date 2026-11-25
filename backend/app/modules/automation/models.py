"""Ejecuciones de herramientas, scripts autorizados y reportes de seguridad."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONType


class ToolExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Registro de cada llamada a una herramienta (qué, quién, decisión y resultado)."""

    __tablename__ = "tool_executions"
    __table_args__ = (Index("ix_tool_executions_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: Sin clave foránea: la conversación o el mensaje pueden borrarse y el historial queda.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    #: auto | approved | denied | timeout | policy_denied | invalid
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    #: ok | error | denied
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AutomationScript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Script que un administrador autoriza explícitamente (ruta + hash SHA-256)."""

    __tablename__ = "automation_scripts"

    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    #: python | powershell | exe
    runner: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Expresión regular que debe cumplir CADA argumento (lista blanca).
    arg_pattern: Mapped[str] = mapped_column(String(200), nullable=False)
    max_args: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SecurityReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "security_reports"
    __table_args__ = (Index("ix_security_reports_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    content: Mapped[str] = mapped_column(Text, nullable=False)
