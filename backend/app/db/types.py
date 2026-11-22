"""Tipos de columna portables entre SQLite y PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Dialect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

#: JSON genérico; JSONB en PostgreSQL.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """``DateTime`` que siempre devuelve fechas *aware* en UTC.

    SQLite no guarda zona horaria: se almacena en UTC sin tz y se restaura como UTC.
    Se rechazan fechas *naive* para evitar ambigüedades.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("timezone", True)
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Se requiere una fecha con zona horaria (UTC)")
        value = value.astimezone(UTC)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
