"""Base declarativa y mixins comunes."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, MetaData, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import uuid7
from app.db.types import UTCDateTime, utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class SyncMixin:
    """Columnas para la sincronización opcional (ver docs/fase-1/05-offline-sync.md)."""

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_hlc: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    origin_device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)

    def touch(self, hlc: str) -> None:
        """Marca un cambio local: incrementa la versión y actualiza el HLC."""
        self.version = (self.version or 0) + 1
        self.updated_hlc = hlc
        self.updated_at = utcnow()

    def soft_delete(self, hlc: str) -> None:
        self.deleted_at = utcnow()
        self.touch(hlc)
