"""Preferencias por usuario."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.types import JSONType


class UserSettings(TimestampMixin, Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(String(16), default="system", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="es", nullable=False)
    default_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    generation_defaults: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    #: Usar los recuerdos aprobados en las respuestas.
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
