"""Mensajes del protocolo de chat (WebSocket y SSE). Ver docs/fase-1/04-api.md."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.llm.base import GenerationParams
from app.modules.settings.schemas import MODEL_NAME_PATTERN

RequestId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
ModelName = Annotated[str, Field(pattern=MODEL_NAME_PATTERN)]
Content = Annotated[str, Field(min_length=1, max_length=100_000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WsAuth(_Strict):
    type: Literal["auth"]
    token: Annotated[str, Field(min_length=10, max_length=4096)]


class WsPing(_Strict):
    type: Literal["ping"]


Attachments = Annotated[list[uuid.UUID], Field(max_length=10)]


class WsChatSend(_Strict):
    type: Literal["chat.send"]
    request_id: RequestId
    conversation_id: uuid.UUID
    content: Content
    model: ModelName | None = None
    params: GenerationParams | None = None
    #: Documentos (ya procesados) que se adjuntan a este mensaje.
    attachments: Attachments = []
    #: Consultar la memoria del usuario en este turno.
    use_memory: bool = True


class WsChatRegenerate(_Strict):
    type: Literal["chat.regenerate"]
    request_id: RequestId
    conversation_id: uuid.UUID
    model: ModelName | None = None
    params: GenerationParams | None = None


class WsChatCancel(_Strict):
    type: Literal["chat.cancel"]
    request_id: RequestId


ClientMessage = Annotated[
    WsAuth | WsPing | WsChatSend | WsChatRegenerate | WsChatCancel,
    Field(discriminator="type"),
]
client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


class ChatCompletionRequest(_Strict):
    """Cuerpo del endpoint SSE ``POST /chat/completions`` (fallback del WebSocket)."""

    request_id: RequestId | None = None
    conversation_id: uuid.UUID
    content: Content | None = None
    regenerate: bool = False
    model: ModelName | None = None
    params: GenerationParams | None = None
    attachments: Attachments = []
    use_memory: bool = True

    @model_validator(mode="after")
    def _content_or_regenerate(self) -> ChatCompletionRequest:
        if not self.regenerate and self.content is None:
            raise ValueError("'content' es obligatorio salvo con regenerate=true")
        if self.regenerate and self.content is not None:
            raise ValueError("'content' no se admite con regenerate=true")
        return self
