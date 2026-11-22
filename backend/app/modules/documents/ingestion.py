"""Ingesta en segundo plano: parseo -> fragmentación -> embeddings -> índice vectorial.

Un único trabajador procesa los documentos de uno en uno: en CPU, procesar varios a la
vez solo competiría por la memoria con el modelo de chat.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import cast

import anyio.to_thread
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import uuid7
from app.llm.base import ModelNotFoundError, ProviderUnavailableError
from app.llm.embeddings import EmbeddingService
from app.modules.documents.chunking import chunk_sections
from app.modules.documents.models import Document, DocumentChunk
from app.modules.documents.parsers import DocumentKind, DocumentParseError, parse_document
from app.vector.base import VectorPoint, VectorStore, collection_name

log = structlog.get_logger(__name__)


def document_path(settings: Settings, user_id: uuid.UUID, storage_key: str) -> Path:
    return settings.uploads_dir / str(user_id) / storage_key


class IngestionWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        vectors: VectorStore,
        embeddings: EmbeddingService,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.vectors = vectors
        self.embeddings = embeddings
        self.collection = collection_name("documents", embeddings.model)
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ ciclo de vida
    async def start(self) -> None:
        await self._recover()
        self._task = asyncio.create_task(self._run(), name="document-ingestion")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def enqueue(self, document_id: uuid.UUID) -> None:
        self._queue.put_nowait(document_id)

    async def wait_idle(self) -> None:
        await self._queue.join()

    async def _recover(self) -> None:
        """Tras un cierre inesperado, se reanudan los documentos que quedaron a medias."""
        async with self.sessionmaker() as db:
            docs = (
                await db.scalars(
                    select(Document).where(Document.status.in_(("pending", "processing")))
                )
            ).all()
            for doc in docs:
                doc.status = "pending"
            await db.commit()
        for doc in docs:
            self.enqueue(doc.id)

    async def _run(self) -> None:
        while True:
            document_id = await self._queue.get()
            try:
                await self.process(document_id)
            except Exception:
                log.exception("ingestion_crashed", document_id=str(document_id))
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------ procesamiento
    async def process(self, document_id: uuid.UUID) -> None:
        async with self.sessionmaker() as db:
            doc = await db.get(Document, document_id)
            if doc is None or doc.status not in ("pending", "processing"):
                return
            doc.status = "processing"
            doc.error = None
            await db.commit()
            user_id, kind, storage_key = doc.user_id, doc.kind, doc.storage_key

        try:
            path = document_path(self.settings, user_id, storage_key)
            sections = await anyio.to_thread.run_sync(
                parse_document, cast("DocumentKind", kind), path
            )
            chunks = chunk_sections(
                sections,
                size=self.settings.chunk_chars,
                overlap=self.settings.chunk_overlap_chars,
            )
            if not chunks:
                raise DocumentParseError(
                    "No se encontró texto. Si es un PDF escaneado, necesita OCR (no soportado)."
                )
            if len(chunks) > self.settings.max_document_chunks:
                raise DocumentParseError(
                    f"El documento es demasiado largo ({len(chunks)} fragmentos; "
                    f"máximo {self.settings.max_document_chunks})."
                )

            # Reindexado: se descarta lo anterior antes de escribir lo nuevo.
            await self.vectors.delete(
                self.collection, user_id, match={"document_id": str(document_id)}
            )
            try:
                vectors = await self.embeddings.embed_documents([c.text for c in chunks])
            except ModelNotFoundError as exc:
                raise DocumentParseError(
                    f"Falta el modelo de embeddings. Instálalo con: "
                    f"ollama pull {self.embeddings.model}"
                ) from exc
            except ProviderUnavailableError as exc:
                raise DocumentParseError(
                    "El motor de IA no está disponible. Reintenta cuando Ollama esté abierto."
                ) from exc

            rows = [
                DocumentChunk(
                    id=uuid7(),
                    document_id=document_id,
                    ordinal=c.ordinal,
                    content=c.text,
                    locator=c.locator,
                    token_count=c.token_count,
                )
                for c in chunks
            ]
            await self.vectors.upsert(
                self.collection,
                user_id,
                [
                    VectorPoint(
                        id=row.id,
                        vector=vector,
                        payload={"document_id": str(document_id), "ordinal": row.ordinal},
                    )
                    for row, vector in zip(rows, vectors, strict=True)
                ],
            )

            async with self.sessionmaker() as db:
                doc = await db.get(Document, document_id)
                if doc is None:  # eliminado mientras se procesaba
                    await self.vectors.delete(
                        self.collection, user_id, match={"document_id": str(document_id)}
                    )
                    return
                await db.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
                db.add_all(rows)
                doc.status = "ready"
                doc.chunk_count = len(rows)
                doc.char_count = sum(len(c.text) for c in chunks)
                doc.embedding_model = self.embeddings.model
                await db.commit()
            log.info("document_ready", document_id=str(document_id), chunks=len(rows))
        except AppError as exc:
            await self._fail(document_id, user_id, exc.detail or exc.title)
        except Exception:
            log.exception("document_failed", document_id=str(document_id))
            await self._fail(document_id, user_id, "Error inesperado al procesar el documento.")

    async def _fail(self, document_id: uuid.UUID, user_id: uuid.UUID, message: str) -> None:
        try:
            await self.vectors.delete(
                self.collection, user_id, match={"document_id": str(document_id)}
            )
        except Exception:
            log.warning("document_vector_cleanup_failed", document_id=str(document_id))
        async with self.sessionmaker() as db:
            doc = await db.get(Document, document_id)
            if doc is not None:
                doc.status = "failed"
                doc.error = message[:1000]
                await db.commit()
