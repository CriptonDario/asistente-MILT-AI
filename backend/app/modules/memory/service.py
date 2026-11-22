"""Lógica de la memoria: CRUD, indexación vectorial, búsqueda y sugerencias."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError, ValidationAppError
from app.core.state import AppState
from app.db.types import utcnow
from app.modules.memory.models import Memory
from app.modules.memory.schemas import MemoryCreate, MemoryOut, MemoryStats, MemoryUpdate
from app.vector.base import VectorPoint, collection_name

log = structlog.get_logger(__name__)

MAX_MEMORIES_PER_USER = 2000


def to_out(memory: Memory) -> MemoryOut:
    return MemoryOut(
        id=memory.id,
        content=memory.content,
        kind=memory.kind,
        source=memory.source,
        status=memory.status,
        importance=memory.importance,
        is_sensitive=memory.is_sensitive,
        indexed=memory.embedding_model is not None,
        source_conversation_id=memory.source_conversation_id,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        last_used_at=memory.last_used_at,
    )


@dataclass(frozen=True)
class RecalledMemory:
    memory: Memory
    score: float


class MemoryService:
    def __init__(self, db: AsyncSession, state: AppState) -> None:
        self.db = db
        self.state = state
        self.embeddings = state.embeddings
        self.collection = collection_name("memories", state.embeddings.model)

    # ------------------------------------------------------------------ consultas
    async def get(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
        memory = await self.db.scalar(
            select(Memory).where(
                Memory.id == memory_id, Memory.user_id == user_id, Memory.deleted_at.is_(None)
            )
        )
        if memory is None:
            raise NotFoundError("Recuerdo no encontrado.")
        return memory

    async def list_memories(
        self, user_id: uuid.UUID, *, status: str, kind: str | None, q: str | None
    ) -> Sequence[Memory]:
        stmt = select(Memory).where(
            Memory.user_id == user_id, Memory.status == status, Memory.deleted_at.is_(None)
        )
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(Memory.content.ilike(f"%{escaped}%", escape="\\"))
        return (await self.db.scalars(stmt.order_by(Memory.updated_at.desc()).limit(500))).all()

    async def stats(self, user_id: uuid.UUID) -> MemoryStats:
        rows = (
            await self.db.execute(
                select(Memory.status, Memory.embedding_model.is_(None), func.count())
                .where(Memory.user_id == user_id, Memory.deleted_at.is_(None))
                .group_by(Memory.status, Memory.embedding_model.is_(None))
            )
        ).all()
        active = sum(c for s, _u, c in rows if s == "active")
        suggested = sum(c for s, _u, c in rows if s == "suggested")
        unindexed = sum(c for s, unindexed, c in rows if s == "active" and unindexed)
        return MemoryStats(active=active, suggested=suggested, unindexed=unindexed)

    # ------------------------------------------------------------------ índice vectorial
    async def _index(self, memory: Memory) -> None:
        """Indexa un recuerdo activo. Si el motor de embeddings falla, queda pendiente."""
        try:
            (vector,) = await self.embeddings.embed_documents([memory.content])
            await self.state.vectors.upsert(
                self.collection,
                memory.user_id,
                [VectorPoint(id=memory.id, vector=vector, payload={"kind": memory.kind})],
            )
            memory.embedding_model = self.embeddings.model
        except AppError as exc:
            log.warning("memory_index_failed", memory_id=str(memory.id), code=exc.code)
            memory.embedding_model = None

    async def _unindex(self, user_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
        await self.state.vectors.delete(self.collection, user_id, ids=ids)

    async def reindex_pending(self, user_id: uuid.UUID) -> int:
        pending = (
            await self.db.scalars(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.status == "active",
                    Memory.deleted_at.is_(None),
                    Memory.embedding_model.is_(None),
                )
            )
        ).all()
        for memory in pending:
            await self._index(memory)
        await self.db.commit()
        return sum(1 for m in pending if m.embedding_model is not None)

    # ------------------------------------------------------------------ escritura
    async def _check_quota(self, user_id: uuid.UUID) -> None:
        total = await self.db.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.user_id == user_id, Memory.deleted_at.is_(None))
        )
        if int(total or 0) >= MAX_MEMORIES_PER_USER:
            raise ValidationAppError("Has alcanzado el máximo de recuerdos. Elimina algunos.")

    async def create(
        self,
        user_id: uuid.UUID,
        data: MemoryCreate,
        *,
        status: str = "active",
        source: str = "user",
        conversation_id: uuid.UUID | None = None,
    ) -> Memory:
        await self._check_quota(user_id)
        memory = Memory(
            user_id=user_id,
            content=data.content.strip(),
            kind=data.kind,
            importance=data.importance,
            is_sensitive=data.is_sensitive,
            status=status,
            source=source,
            source_conversation_id=conversation_id,
            updated_hlc=self.state.hlc.now(),
        )
        self.db.add(memory)
        await self.db.flush()
        if status == "active":
            await self._index(memory)
        await self.db.commit()
        return memory

    async def update(self, user_id: uuid.UUID, memory_id: uuid.UUID, data: MemoryUpdate) -> Memory:
        memory = await self.get(user_id, memory_id)
        changed_text = data.content is not None and data.content.strip() != memory.content
        if data.content is not None:
            memory.content = data.content.strip()
        if data.kind is not None:
            memory.kind = data.kind
        if data.importance is not None:
            memory.importance = data.importance
        if data.is_sensitive is not None:
            memory.is_sensitive = data.is_sensitive
        memory.touch(self.state.hlc.now())
        if memory.status == "active" and (changed_text or data.kind is not None):
            await self._index(memory)
        await self.db.commit()
        return memory

    async def delete(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
        memory = await self.get(user_id, memory_id)
        await self._unindex(user_id, [memory.id])
        await self.db.delete(memory)
        await self.db.commit()

    async def delete_all(self, user_id: uuid.UUID) -> int:
        ids = list(
            (await self.db.scalars(select(Memory.id).where(Memory.user_id == user_id))).all()
        )
        await self.state.vectors.delete(self.collection, user_id)
        await self.db.execute(delete(Memory).where(Memory.user_id == user_id))
        await self.db.commit()
        return len(ids)

    async def accept(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
        memory = await self.get(user_id, memory_id)
        if memory.status != "suggested":
            raise ValidationAppError("Ese recuerdo ya está activo.")
        memory.status = "active"
        memory.touch(self.state.hlc.now())
        await self._index(memory)
        await self.db.commit()
        return memory

    # ------------------------------------------------------------------ recuperación
    async def search(self, user_id: uuid.UUID, query: str, *, top_k: int) -> list[RecalledMemory]:
        vector = await self.embeddings.embed_query(query)
        return await self.search_by_vector(user_id, vector, top_k=top_k)

    async def search_by_vector(
        self,
        user_id: uuid.UUID,
        vector: list[float],
        *,
        top_k: int,
        min_score: float | None = None,
    ) -> list[RecalledMemory]:
        hits = await self.state.vectors.search(
            self.collection, user_id, vector, limit=top_k, min_score=min_score
        )
        if not hits:
            return []
        by_id = {
            m.id: m
            for m in (
                await self.db.scalars(
                    select(Memory).where(
                        Memory.id.in_([h.id for h in hits]),
                        Memory.user_id == user_id,
                        Memory.status == "active",
                        Memory.deleted_at.is_(None),
                    )
                )
            ).all()
        }
        return [RecalledMemory(by_id[h.id], h.score) for h in hits if h.id in by_id]

    async def recall_for_prompt(
        self, user_id: uuid.UUID, vector: list[float]
    ) -> list[RecalledMemory]:
        """Recuerdos relevantes para una pregunta ya embebida (con umbral de similitud)."""
        settings = self.state.settings
        recalled = await self.search_by_vector(
            user_id, vector, top_k=settings.memory_top_k, min_score=settings.memory_min_score
        )
        if recalled:
            now = utcnow()
            for r in recalled:
                r.memory.last_used_at = now
            await self.db.commit()
        return recalled
