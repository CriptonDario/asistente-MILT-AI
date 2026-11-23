"""Ingesta en segundo plano: parseo -> fragmentación -> embeddings -> índice vectorial.

Un único trabajador procesa los documentos de uno en uno: en CPU, procesar varios a la
vez solo competiría por la memoria con el modelo de chat. El parseo se hace en un
subproceso con límite de tiempo para que un archivo malicioso no bloquee el servicio.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import uuid
from pathlib import Path
from typing import cast

import anyio.to_thread
import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import uuid7
from app.llm.base import ModelNotFoundError, ProviderUnavailableError
from app.llm.embeddings import EmbeddingService
from app.modules.documents.chunking import chunk_sections
from app.modules.documents.models import Document, DocumentChunk
from app.modules.documents.parsers import (
    DocumentKind,
    DocumentParseError,
    Section,
    parse_document,
    parse_isolated,
)
from app.modules.users.models import User
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

    @property
    def max_chars(self) -> int:
        return self.settings.max_document_chunks * self.settings.chunk_chars

    # ------------------------------------------------------------------ ciclo de vida
    async def start(self) -> None:
        await self._recover()
        await anyio.to_thread.run_sync(self._sweep_orphan_files_sync, await self._known_files())
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
        """Reanuda los documentos a medias y reindexa los de otro modelo de embeddings."""
        async with self.sessionmaker() as db:
            docs = (
                await db.scalars(
                    select(Document).where(
                        Document.status.in_(("pending", "processing"))
                        | (
                            (Document.status == "ready")
                            & (Document.embedding_model != self.embeddings.model)
                        )
                    )
                )
            ).all()
            for doc in docs:
                doc.status = "pending"
            await db.commit()
        for doc in docs:
            self.enqueue(doc.id)
        if docs:
            log.info("ingestion_recovered", count=len(docs))

    async def _known_files(self) -> dict[str, set[str]]:
        async with self.sessionmaker() as db:
            rows = (await db.execute(select(Document.user_id, Document.storage_key))).all()
            users = {str(u) for u in (await db.scalars(select(User.id))).all()}
        known: dict[str, set[str]] = {u: set() for u in users}
        for user_id, key in rows:
            known.setdefault(str(user_id), set()).add(key)
        return known

    def _sweep_orphan_files_sync(self, known: dict[str, set[str]]) -> None:
        """Borra archivos sin documento (borrados que fallaron, usuarios eliminados, .part)."""
        root = self.settings.uploads_dir
        if not root.exists():
            return
        for user_dir in root.iterdir():
            if not user_dir.is_dir():
                continue
            if user_dir.name not in known:
                shutil.rmtree(user_dir, ignore_errors=True)
                continue
            for file in user_dir.iterdir():
                if file.name not in known[user_dir.name]:
                    with contextlib.suppress(OSError):
                        file.unlink()

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
    def _parse(self, kind: DocumentKind, path: Path) -> list[Section]:
        if self.settings.parse_isolated:
            return parse_isolated(
                kind, path, max_chars=self.max_chars, timeout=self.settings.parse_timeout_seconds
            )
        return parse_document(kind, path, max_chars=self.max_chars)

    async def process(self, document_id: uuid.UUID) -> None:
        async with self.sessionmaker() as db:
            doc = await db.get(Document, document_id)
            if doc is None or doc.status not in ("pending", "processing"):
                return
            # Si ya tenía un índice válido, un fallo al reindexar no debe destruirlo.
            had_index = doc.chunk_count > 0 and doc.embedding_model == self.embeddings.model
            doc.status = "processing"
            doc.error = None
            await db.commit()
            user_id, kind, storage_key = doc.user_id, doc.kind, doc.storage_key
            used_by_others = int(
                await db.scalar(
                    select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                        Document.user_id == user_id, Document.id != document_id
                    )
                )
                or 0
            )

        try:
            path = document_path(self.settings, user_id, storage_key)
            sections = await anyio.to_thread.run_sync(self._parse, cast("DocumentKind", kind), path)
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
            if used_by_others + len(chunks) > self.settings.max_chunks_per_user:
                raise DocumentParseError(
                    "Has alcanzado el límite de texto indexado. Elimina algún documento."
                )

            # 1) Embeddings primero: si fallan, el índice anterior sigue intacto.
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
            # 2) Sustitución del índice: se retira el anterior y se escribe el nuevo.
            had_index = False
            await self.vectors.delete(
                self.collection, user_id, match={"document_id": str(document_id)}
            )
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

            # 3) SQL (sin esperas externas con la transacción abierta).
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
                doc.error = None
                doc.chunk_count = len(rows)
                doc.char_count = sum(len(c.text) for c in chunks)
                doc.embedding_model = self.embeddings.model
                await db.commit()
            log.info("document_ready", document_id=str(document_id), chunks=len(rows))
        except AppError as exc:
            await self._fail(document_id, user_id, exc.detail or exc.title, keep_index=had_index)
        except Exception:
            log.exception("document_failed", document_id=str(document_id))
            await self._fail(
                document_id,
                user_id,
                "Error inesperado al procesar el documento.",
                keep_index=had_index,
            )

    async def _fail(
        self, document_id: uuid.UUID, user_id: uuid.UUID, message: str, *, keep_index: bool
    ) -> None:
        if not keep_index:
            try:
                await self.vectors.delete(
                    self.collection, user_id, match={"document_id": str(document_id)}
                )
            except Exception:
                log.warning("document_vector_cleanup_failed", document_id=str(document_id))
        async with self.sessionmaker() as db:
            doc = await db.get(Document, document_id)
            if doc is not None:
                # Reindexado fallido con un índice previo válido: sigue utilizable.
                doc.status = "ready" if keep_index else "failed"
                doc.error = (
                    f"No se pudo reindexar: {message}"[:1000] if keep_index else message[:1000]
                )
                await db.commit()
