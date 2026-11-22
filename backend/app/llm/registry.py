"""Registro de proveedores de IA disponibles."""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.llm.base import LLMProvider
from app.llm.fake_provider import FakeLLMProvider
from app.llm.ollama_provider import OllamaProvider


class ProviderRegistry:
    def __init__(self, providers: list[LLMProvider], *, default: str) -> None:
        self._providers = {p.name: p for p in providers}
        if default not in self._providers:
            raise ValueError(f"Proveedor por defecto desconocido: {default}")
        self._default = default

    @property
    def default_name(self) -> str:
        return self._default

    def get(self, name: str | None = None) -> LLMProvider:
        key = name or self._default
        provider = self._providers.get(key)
        if provider is None:
            raise NotFoundError(f"Proveedor de IA desconocido: {key}")
        return provider

    def all(self) -> list[LLMProvider]:
        return list(self._providers.values())

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()


def build_default_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeLLMProvider(models=[settings.default_model])
    return OllamaProvider(
        settings.ollama_base_url,
        connect_timeout=settings.llm_connect_timeout,
        read_timeout=settings.llm_read_timeout,
        default_think=settings.llm_think,
    )
