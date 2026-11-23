"""Servicio de embeddings sobre el proveedor de IA (por defecto Ollama)."""

from __future__ import annotations

from app.llm.base import LLMProvider

# Algunos modelos rinden mejor con prefijos de tarea distintos para documentos y consultas.
_TASK_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic-embed-text": ("search_document: ", "search_query: "),
}


class EmbeddingService:
    def __init__(self, provider: LLMProvider, *, model: str, batch_size: int = 16) -> None:
        self.provider = provider
        self.model = model
        self.batch_size = batch_size
        base = model.split(":", 1)[0].lower()
        self._doc_prefix, self._query_prefix = _TASK_PREFIXES.get(base, ("", ""))

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embeddings en lotes pequeños: en CPU evita picos de memoria y de latencia."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [self._doc_prefix + t for t in texts[start : start + self.batch_size]]
            vectors.extend(await self.provider.embed(batch, model=self.model))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        (vector,) = await self.provider.embed([self._query_prefix + text], model=self.model)
        return vector
