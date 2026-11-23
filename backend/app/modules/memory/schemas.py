"""Esquemas de la memoria persistente."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryKind = Literal["fact", "preference", "project", "instruction"]
MemoryStatus = Literal["active", "suggested"]
MemoryContent = Annotated[str, Field(min_length=2, max_length=1000)]


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content: str
    kind: MemoryKind
    source: str
    status: MemoryStatus
    importance: float
    is_sensitive: bool
    indexed: bool
    source_conversation_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: MemoryContent
    kind: MemoryKind = "fact"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    is_sensitive: bool = False


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: MemoryContent | None = None
    kind: MemoryKind | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    is_sensitive: bool | None = None


class MemorySearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=2, max_length=1000)]
    top_k: int = Field(default=5, ge=1, le=20)


class MemorySearchHit(BaseModel):
    memory: MemoryOut
    score: float


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID


class ExtractResult(BaseModel):
    created: list[MemoryOut]
    skipped_duplicates: int


class DeleteAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: Literal["DELETE"]


class MemoryStats(BaseModel):
    active: int
    suggested: int
    unindexed: int
