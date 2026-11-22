"""Recuerdos persistentes del usuario."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SyncMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime


class Memory(UUIDPrimaryKeyMixin, TimestampMixin, SyncMixin, Base):
    """Un hecho, preferencia, proyecto o instrucción que MILT recuerda.

    ``status``: ``suggested`` (propuesto por MILT, pendiente de aprobación) o ``active``.
    Solo los activos se indexan en el almacén vectorial y se usan en las respuestas.
    """

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_user_status", "user_id", "status"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="fact", nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Modelo con el que está indexado; ``None`` si falta indexar (p. ej. Ollama apagado).
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
