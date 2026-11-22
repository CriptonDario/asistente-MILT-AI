"""Contrato común para proveedores de modelos de lenguaje."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError, NotFoundError, ServiceUnavailableError, ValidationAppError

Role = Literal["system", "user", "assistant", "tool"]


# --------------------------------------------------------------------------- errores
class ProviderUnavailableError(ServiceUnavailableError):
    code = "provider_unavailable"
    title = "Motor de IA no disponible"


class ModelNotFoundError(NotFoundError):
    code = "model_not_found"
    title = "Modelo no encontrado"


class ProviderError(AppError):
    status_code = 502
    code = "provider_error"
    title = "Error del motor de IA"


class InsufficientMemoryError(ProviderError):
    status_code = 503
    code = "insufficient_memory"
    title = "Memoria insuficiente para el modelo"


class ContextOverflowError(ValidationAppError):
    code = "context_overflow"
    title = "El mensaje no cabe en el contexto del modelo"


# --------------------------------------------------------------------------- datos
class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str
    tool_calls: list[dict[str, Any]] | None = None


class GenerationParams(BaseModel):
    """Parámetros de generación aceptados por la API (validados y acotados)."""

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    num_ctx: int | None = Field(default=None, ge=512, le=131_072)
    max_tokens: int | None = Field(default=None, ge=1, le=32_768)
    seed: int | None = None
    think: bool | None = None

    def merged_over(self, base: GenerationParams) -> GenerationParams:
        """Devuelve ``base`` sobrescrito con los valores no nulos de ``self``."""
        data = base.model_dump()
        data.update(self.model_dump(exclude_none=True))
        return GenerationParams(**data)


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_duration_ms: int = 0


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ThinkingDelta:
    text: str


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Done:
    usage: Usage
    done_reason: str | None = None


ChatChunk = TextDelta | ThinkingDelta | ToolCallRequest | Done


@dataclass(frozen=True)
class ModelInfo:
    provider: str
    name: str
    size_bytes: int | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    context_length: int | None = None
    capabilities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderHealth:
    ok: bool
    provider: str
    version: str | None = None
    detail: str | None = None
    latency_ms: int | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def health(self) -> ProviderHealth: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def get_model(self, name: str) -> ModelInfo: ...

    def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        params: GenerationParams,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ChatChunk]: ...

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]: ...

    async def aclose(self) -> None: ...
