"""Almacén vectorial Qdrant: embebido (perfil local) o servidor (perfil server)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from app.vector.base import VectorHit, VectorPoint

log = structlog.get_logger(__name__)


class QdrantVectorStore:
    def __init__(
        self,
        *,
        path: Path | None = None,
        url: str | None = None,
        location: str | None = None,
    ) -> None:
        if url:
            self._client = AsyncQdrantClient(url=url)
        elif location:
            self._client = AsyncQdrantClient(location=location)
        else:
            if path is None:
                raise ValueError("Se necesita path, url o location para Qdrant")
            path.mkdir(parents=True, exist_ok=True)
            self._client = AsyncQdrantClient(path=str(path))
        self._known: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def _ensure(self, collection: str, dim: int) -> None:
        if self._known.get(collection) == dim:
            return
        async with self._lock:
            if not await self._client.collection_exists(collection):
                await self._client.create_collection(
                    collection,
                    vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
                )
            else:
                info = await self._client.get_collection(collection)
                params = info.config.params.vectors
                size = params.size if isinstance(params, qm.VectorParams) else None
                if size is not None and size != dim:
                    raise ValueError(
                        f"La colección {collection} usa vectores de {size} dimensiones, no {dim}"
                    )
            self._known[collection] = dim

    async def _exists(self, collection: str) -> bool:
        if collection in self._known:
            return True
        return bool(await self._client.collection_exists(collection))

    @staticmethod
    def _filter(
        user_id: uuid.UUID,
        match: dict[str, Any] | None = None,
        match_any: dict[str, list[str]] | None = None,
        ids: list[uuid.UUID] | None = None,
    ) -> qm.Filter:
        conditions: list[qm.Condition] = [
            qm.FieldCondition(key="user_id", match=qm.MatchValue(value=str(user_id)))
        ]
        if ids is not None:
            conditions.append(qm.HasIdCondition(has_id=[str(i) for i in ids]))
        for key, value in (match or {}).items():
            conditions.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=value)))
        for key, values in (match_any or {}).items():
            conditions.append(qm.FieldCondition(key=key, match=qm.MatchAny(any=values)))
        return qm.Filter(must=conditions)

    async def upsert(self, collection: str, user_id: uuid.UUID, points: list[VectorPoint]) -> None:
        if not points:
            return
        await self._ensure(collection, len(points[0].vector))
        await self._client.upsert(
            collection,
            points=[
                qm.PointStruct(
                    id=str(p.id),
                    vector=p.vector,
                    # El user_id del payload lo fija el almacén, nunca quien llama.
                    payload={**p.payload, "user_id": str(user_id)},
                )
                for p in points
            ],
        )

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
    ) -> list[VectorHit]:
        if not await self._exists(collection):
            return []
        response = await self._client.query_points(
            collection,
            query=vector,
            query_filter=self._filter(user_id, match, match_any),
            limit=limit,
            score_threshold=min_score,
            with_payload=True,
        )
        return [
            VectorHit(id=uuid.UUID(str(p.id)), score=float(p.score), payload=dict(p.payload or {}))
            for p in response.points
        ]

    async def delete(
        self,
        collection: str,
        user_id: uuid.UUID,
        *,
        ids: list[uuid.UUID] | None = None,
        match: dict[str, Any] | None = None,
    ) -> None:
        if (ids is not None and not ids) or not await self._exists(collection):
            return
        # El filtro por user_id va siempre: aunque los ids sean de otro usuario, no se borran.
        flt = self._filter(user_id, match, ids=ids)
        await self._client.delete(collection, points_selector=qm.FilterSelector(filter=flt))

    async def count(self, collection: str, user_id: uuid.UUID) -> int:
        if not await self._exists(collection):
            return 0
        result = await self._client.count(collection, count_filter=self._filter(user_id))
        return int(result.count)

    async def health(self) -> bool:
        try:
            await self._client.get_collections()
        except Exception:
            log.warning("vector_store_unhealthy", exc_info=True)
            return False
        return True

    async def aclose(self) -> None:
        await self._client.close()
