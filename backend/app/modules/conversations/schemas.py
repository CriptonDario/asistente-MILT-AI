"""Esquemas de conversaciones y mensajes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.profiles import AgentProfileName
from app.llm.base import GenerationParams
from app.modules.settings.schemas import MODEL_NAME_PATTERN


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, pattern=MODEL_NAME_PATTERN)
    agent_profile: AgentProfileName = "general"
    params: GenerationParams | None = None


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, pattern=MODEL_NAME_PATTERN)
    agent_profile: AgentProfileName | None = None
    params: GenerationParams | None = None
    pinned: bool | None = None
    archived: bool | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    model: str | None
    agent_profile: str
    params: dict[str, Any] | None
    pinned: bool
    archived: bool
    created_at: datetime
    updated_at: datetime


MessageRole = Literal["system", "user", "assistant", "tool"]
MessageStatus = Literal["complete", "cancelled", "error"]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    model: str | None
    status: MessageStatus
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    created_at: datetime


class MessageSearchHit(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    conversation_title: str | None
    role: MessageRole
    snippet: str
    created_at: datetime


class SearchQuery(BaseModel):
    q: str = Field(min_length=2, max_length=200)

    @field_validator("q")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("La búsqueda debe tener al menos 2 caracteres")
        return value
