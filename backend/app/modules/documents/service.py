"""Subida, consulta, borrado, reindexado y búsqueda de documentos."""

from __future__ import annotations

import contextlib
import hashlib
import re
import uuid
from collections.abc import Sequence
from pathlib import Path

import anyio.to_thread
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PayloadTooLargeError, ValidationAppError
from app.core.state import AppState
from app.modules.documents.chunking import format_locator
from app.modules.documents.ingestion import document_path
from app.modules.documents.models import Document
from app.modules.documents.parsers import MIME_TYPES, detect_kind
from app.modules.documents.retriever import RetrievedChunk, retrieve_chunks
from app.modules.documents.schemas import DocumentSearchHit

MAX_DOCUMENTS_PER_USER = 500
MAX_BYTES_PER_USER = 2 * 1024 * 1024 * 1024
_READ_CHUNK = 1024 * 1024
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]+")


def safe_filename(name: str | None) -> str:
    """Nombre para mostrar: sin rutas ni caracteres de control (en disco se usa un UUID)."""
    base = Path((name or "documento").replace("\\", "/")).name
    cleaned = _UNSAFE_NAME.sub("_", base).strip(" .") or "documento"
    if len(cleaned) > 200:
        stem, dot, ext = cleaned.rpartition(".")
        cleaned = (stem[:190] + dot + ext) if dot else cleaned[:200]
    return cleaned


def to_hit(chunk: RetrievedChunk) -> DocumentSearchHit:
    return DocumentSearchHit(
        document_id=chunk.document_id,
        filename=chunk.filename,
        chunk_id=chunk.chunk_id,
        ordinal=chunk.ordinal,
        content=chunk.content,
        locator=chunk.locator,
        location=format_locator(chunk.locator),
        score=round(chunk.score, 4),
    )


class DocumentService:
    def __init__(self, db: AsyncSession, state: AppState) -> None:
        self.db = db
        self.state = state
        self.settings = state.settings

    async def get(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        doc = await self.db.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        if doc is None:
            raise NotFoundError("Documento no encontrado.")
        return doc

    async def list_documents(self, user_id: uuid.UUID) -> Sequence[Document]:
        stmt = (
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc())
            .limit(MAX_DOCUMENTS_PER_USER)
        )
        return (await self.db.scalars(stmt)).all()

    async def _check_quota(self, user_id: uuid.UUID) -> None:
        count, total = (
            await self.db.execute(
                select(func.count(), func.coalesce(func.sum(Document.size_bytes), 0)).where(
                    Document.user_id == user_id
                )
            )
        ).one()
        if count >= MAX_DOCUMENTS_PER_USER:
            raise ValidationAppError(f"Máximo de {MAX_DOCUMENTS_PER_USER} documentos alcanzado.")
        if total >= MAX_BYTES_PER_USER:
            raise ValidationAppError("Has alcanzado el espacio máximo para documentos.")

    async def upload(self, user_id: uuid.UUID, file: UploadFile) -> tuple[Document, bool]:
        await self._check_quota(user_id)
        filename = safe_filename(file.filename)
        user_dir = self.settings.uploads_dir / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        storage_key = uuid.uuid4().hex
        temp = user_dir / f"{storage_key}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with temp.open("wb") as out:
                while chunk := await file.read(_READ_CHUNK):
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        limit_mb = self.settings.max_upload_bytes // (1024 * 1024)
                        raise PayloadTooLargeError(f"El archivo supera {limit_mb} MB.")
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise ValidationAppError("El archivo está vacío.")
            kind = await anyio.to_thread.run_sync(detect_kind, temp, filename)
            sha256 = digest.hexdigest()

            existing = await self.db.scalar(
                select(Document).where(
                    Document.user_id == user_id,
                    Document.sha256 == sha256,
                    Document.status != "failed",
                )
            )
            if existing is not None:
                return existing, True

            temp.replace(user_dir / storage_key)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temp.unlink()

        doc = Document(
            user_id=user_id,
            filename=filename,
            storage_key=storage_key,
            kind=kind,
            mime_type=MIME_TYPES[kind],
            size_bytes=size,
            sha256=sha256,
            status="pending",
        )
        self.db.add(doc)
        await self.db.commit()
        self.state.ingestion.enqueue(doc.id)
        return doc, False

    async def delete(self, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
        doc = await self.get(user_id, document_id)
        await self.state.vectors.delete(
            self.state.ingestion.collection, user_id, match={"document_id": str(doc.id)}
        )
        path = document_path(self.settings, user_id, doc.storage_key)
        await self.db.delete(doc)
        await self.db.commit()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()

    async def reindex(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        doc = await self.get(user_id, document_id)
        if doc.status in ("pending", "processing"):
            return doc
        doc.status = "pending"
        doc.error = None
        await self.db.commit()
        self.state.ingestion.enqueue(doc.id)
        return doc

    async def ready_ids(
        self, user_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
    ) -> list[uuid.UUID]:
        """Filtra los ids que pertenecen al usuario y están listos para consultarse."""
        if not document_ids:
            return []
        rows = await self.db.scalars(
            select(Document.id).where(
                Document.id.in_(list(document_ids)),
                Document.user_id == user_id,
                Document.status == "ready",
            )
        )
        return list(rows.all())

    async def search(
        self,
        user_id: uuid.UUID,
        query: str,
        *,
        document_ids: list[uuid.UUID] | None,
        top_k: int,
    ) -> list[DocumentSearchHit]:
        vector = await self.state.embeddings.embed_query(query)
        chunks = await retrieve_chunks(
            self.db,
            self.state.vectors,
            self.state.ingestion.collection,
            user_id,
            vector,
            document_ids=document_ids,
            top_k=top_k,
            min_score=None,
        )
        return [to_hit(c) for c in chunks]

    def file_path(self, doc: Document) -> Path:
        return document_path(self.settings, doc.user_id, doc.storage_key)
