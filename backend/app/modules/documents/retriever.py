"""Recuperación de fragmentos relevantes (RAG) con verificación de propiedad en SQL."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document, DocumentChunk
from app.vector.base import VectorStore


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    ordinal: int
    content: str
    locator: dict[str, Any] | None
    score: float


async def whole_documents_if_small(
    db: AsyncSession,
    user_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    *,
    budget_tokens: int,
) -> list[RetrievedChunk] | None:
    """Todos los fragmentos, en orden, si los documentos caben enteros en el presupuesto.

    Así funcionan peticiones como "resume el documento", que no se parecen a ningún
    fragmento concreto y la búsqueda por similitud no recuperaría bien.
    """
    total = await db.scalar(
        select(func.coalesce(func.sum(DocumentChunk.token_count), 0))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.document_id.in_(document_ids),
            Document.user_id == user_id,
            Document.status == "ready",
        )
    )
    if int(total or 0) > budget_tokens:
        return None
    rows = (
        await db.execute(
            select(DocumentChunk, Document.filename)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.document_id.in_(document_ids),
                Document.user_id == user_id,
                Document.status == "ready",
            )
            .order_by(Document.created_at, DocumentChunk.ordinal)
        )
    ).all()
    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            ordinal=chunk.ordinal,
            content=chunk.content,
            locator=chunk.locator,
            score=1.0,
        )
        for chunk, filename in rows
    ]


async def retrieve_chunks(
    db: AsyncSession,
    vectors: VectorStore,
    collection: str,
    user_id: uuid.UUID,
    query_vector: list[float],
    *,
    document_ids: list[uuid.UUID] | None,
    top_k: int,
    min_score: float | None,
) -> list[RetrievedChunk]:
    match_any = {"document_id": [str(d) for d in document_ids]} if document_ids else None
    hits = await vectors.search(
        collection, user_id, query_vector, limit=top_k, min_score=min_score, match_any=match_any
    )
    if not hits:
        return []
    scores = {h.id: h.score for h in hits}
    rows = (
        await db.execute(
            select(DocumentChunk, Document.filename)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.id.in_(list(scores)),
                Document.user_id == user_id,
                Document.status == "ready",
            )
        )
    ).all()
    result = [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            ordinal=chunk.ordinal,
            content=chunk.content,
            locator=chunk.locator,
            score=scores[chunk.id],
        )
        for chunk, filename in rows
    ]
    result.sort(key=lambda r: r.score, reverse=True)
    return result
