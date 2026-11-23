"""Proveedor simulado: pruebas automáticas y desarrollo del frontend sin Ollama.

Se activa con ``MILT_LLM_PROVIDER=fake``.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import (
    ChatChunk,
    ChatMessage,
    Done,
    GenerationParams,
    ModelInfo,
    ModelNotFoundError,
    ProviderHealth,
    TextDelta,
    ToolCallRequest,
    Usage,
)

DEFAULT_FAKE_MODEL = "fake-model"
FAKE_EMBED_DIM = 256


class FakeLLMProvider:
    name = "fake"

    def __init__(
        self,
        reply: str = "Hola, soy MILT. Esta es una respuesta simulada.",
        *,
        delay: float = 0.0,
        models: list[str] | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        self.reply = reply
        self.delay = delay
        self.fail_with = fail_with
        self.model_names = models or [DEFAULT_FAKE_MODEL]
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.embed_calls = 0
        self.embed_fail_with: Exception | None = None
        self.embed_delay = 0.0
        #: Cada elemento es una "vuelta" en la que el modelo pide esas herramientas.
        self.tool_rounds: list[list[ToolCallRequest]] = []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, provider=self.name, version="fake", latency_ms=0)

    async def list_models(self) -> list[ModelInfo]:
        return [await self.get_model(name) for name in self.model_names]

    async def get_model(self, name: str) -> ModelInfo:
        if name not in self.model_names:
            raise ModelNotFoundError(f"model '{name}' not found")
        return ModelInfo(
            provider=self.name,
            name=name,
            size_bytes=0,
            family="fake",
            parameter_size="0B",
            context_length=8192,
            capabilities=["completion"],
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        params: GenerationParams,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ChatChunk]:
        await self.get_model(model)
        self.calls.append({"messages": messages, "model": model, "params": params, "tools": tools})
        if self.fail_with is not None:
            raise self.fail_with
        # Guion de herramientas: si se ofrecen, la siguiente "vuelta" pide estas llamadas.
        if tools and self.tool_rounds:
            for call in self.tool_rounds.pop(0):
                yield call
            yield Done(usage=Usage(prompt_tokens=10, completion_tokens=1), done_reason="stop")
            return
        words = re.findall(r"\S+\s*", self.reply)
        for word in words:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield TextDelta(word)
        prompt_chars = sum(len(m.content) for m in messages)
        yield Done(
            usage=Usage(prompt_tokens=prompt_chars // 4, completion_tokens=len(words)),
            done_reason="stop",
        )

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        """Bolsa de palabras con *hashing*: textos que comparten palabras quedan cerca.

        Determinista y sin modelo, suficiente para probar la recuperación semántica.
        """
        self.embed_calls += 1
        if self.embed_delay:
            await asyncio.sleep(self.embed_delay)
        if self.embed_fail_with is not None:
            raise self.embed_fail_with
        vectors = []
        for text in texts:
            vector = [0.0] * FAKE_EMBED_DIM
            for word in re.findall(r"\w{3,}", text.lower()):
                if word in ("search_document", "search_query"):
                    continue
                bucket = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big")
                vector[bucket % FAKE_EMBED_DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            vectors.append([v / norm for v in vector])
        return vectors

    async def aclose(self) -> None:
        self.closed = True
