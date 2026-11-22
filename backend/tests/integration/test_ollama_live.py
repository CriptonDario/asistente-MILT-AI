"""Prueba opcional contra un Ollama real. Ejecutar con::

MILT_TEST_OLLAMA=1 uv run pytest -m ollama
"""

from __future__ import annotations

import os

import pytest

from app.llm.base import ChatMessage, Done, GenerationParams, TextDelta
from app.llm.ollama_provider import OllamaProvider

pytestmark = [
    pytest.mark.ollama,
    pytest.mark.skipif(os.environ.get("MILT_TEST_OLLAMA") != "1", reason="MILT_TEST_OLLAMA!=1"),
]

MODEL = os.environ.get("MILT_TEST_OLLAMA_MODEL", "qwen3:1.7b")


@pytest.mark.anyio
async def test_live_ollama_chat_stream() -> None:
    provider = OllamaProvider(os.environ.get("MILT_OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    try:
        assert (await provider.health()).ok
        models = {m.name for m in await provider.list_models()}
        assert MODEL in models, f"Instala el modelo: ollama pull {MODEL}"
        chunks = [
            chunk
            async for chunk in provider.chat_stream(
                [ChatMessage(role="user", content="Responde solo con la palabra: hola")],
                model=MODEL,
                params=GenerationParams(temperature=0, num_ctx=1024, max_tokens=20, think=False),
            )
        ]
        text = "".join(c.text for c in chunks if isinstance(c, TextDelta))
        assert text.strip()
        assert isinstance(chunks[-1], Done)
        assert chunks[-1].usage.completion_tokens > 0
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_live_embeddings_rank_related_text_higher() -> None:
    from app.llm.embeddings import EmbeddingService

    provider = OllamaProvider(os.environ.get("MILT_OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    embed_model = os.environ.get("MILT_TEST_EMBED_MODEL", "nomic-embed-text")
    try:
        service = EmbeddingService(provider, model=embed_model)
        docs = await service.embed_documents(
            ["El servidor escucha en el puerto 8443.", "Mi gato se llama Michi."]
        )
        query = await service.embed_query("¿Qué puerto usa el servidor?")

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))

        assert len(query) == len(docs[0]) > 100
        assert cosine(query, docs[0]) > cosine(query, docs[1])
    finally:
        await provider.aclose()
