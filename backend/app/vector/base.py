"""Contrato del almacén vectorial (índice derivado; SQL es la fuente de verdad)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class VectorPoint:
    id: uuid.UUID
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorHit:
    id: uuid.UUID
    score: float
    payload: dict[str, Any]


class VectorStore(Protocol):
    """Todas las operaciones exigen ``user_id``: el aislamiento no depende de quien llama."""

    async def upsert(
        self, collection: str, user_id: uuid.UUID, points: list[VectorPoint]
    ) -> None: ...

    async def search(
        self,
        collection: str,
        user_id: uuid.UUID,
        vector: list[float],
        *,
        limit: int,
        min_score: float | None = None,
        match: dict[str, Any] | None = None,
        match_any: dict[str, list[str]] | None = None,
    ) -> list[VectorHit]: ...

    async def delete(
        self,
        collection: str,
        user_id: uuid.UUID,
        *,
        ids: list[uuid.UUID] | None = None,
        match: dict[str, Any] | None = None,
    ) -> None: ...

    async def count(self, collection: str, user_id: uuid.UUID) -> int: ...

    async def health(self) -> bool: ...

    async def aclose(self) -> None: ...


def collection_name(kind: str, model: str) -> str:
    """``memories__nomic-embed-text``: los vectores de modelos distintos nunca se mezclan."""
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in model.lower())
    return f"{kind}__{slug}"
