"""Proveedor simulado: pruebas automáticas y desarrollo del frontend sin Ollama.

Se activa con ``MILT_LLM_PROVIDER=fake``.
"""

from __future__ import annotations

import asyncio
import hashlib
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
    Usage,
)

DEFAULT_FAKE_MODEL = "fake-model"


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
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vectors.append([b / 255.0 for b in digest[:16]])
        return vectors

    async def aclose(self) -> None:
        self.closed = True
