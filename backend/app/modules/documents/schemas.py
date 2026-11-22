"""Esquemas de documentos."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentStatus = Literal["pending", "processing", "ready", "failed"]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    kind: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    error: str | None
    chunk_count: int
    char_count: int
    created_at: datetime
    updated_at: datetime


class UploadResult(BaseModel):
    document: DocumentOut
    #: ``True`` si ya existía un documento idéntico (mismo SHA-256): no se duplica.
    duplicate: bool


class DocumentSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=2, max_length=1000)]
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    top_k: int = Field(default=5, ge=1, le=20)


class DocumentSearchHit(BaseModel):
    document_id: uuid.UUID
    filename: str
    chunk_id: uuid.UUID
    ordinal: int
    content: str
    locator: dict[str, Any] | None
    location: str
    score: float
