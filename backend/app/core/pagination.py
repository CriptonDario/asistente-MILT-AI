"""Paginación por cursor opaco (keyset pagination)."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.core.errors import ValidationAppError

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(values: list[str]) -> str:
    raw = json.dumps(values, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, expected_len: int) -> list[str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValidationAppError("Cursor de paginación no válido.") from exc
    if (
        not isinstance(values, list)
        or len(values) != expected_len
        or not all(isinstance(v, str) for v in values)
    ):
        raise ValidationAppError("Cursor de paginación no válido.")
    return values
