"""Dispositivos y refresh tokens (sesiones)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime


class Device(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    remote_access_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Refresh token rotativo. Una *familia* (``family_id``) equivale a una sesión."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_family_id", "family_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
