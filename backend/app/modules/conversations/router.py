"""Endpoints de conversaciones, mensajes y búsqueda."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.core.deps import AuthDep, DbDep, StateDep
from app.core.pagination import Page
from app.modules.conversations.schemas import (
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
    MessageSearchHit,
    SearchQuery,
)
from app.modules.conversations.service import (
    ConversationService,
    export_json,
    export_markdown,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])
search_router = APIRouter(prefix="/search", tags=["conversations"])


def _service(db: DbDep, state: StateDep) -> ConversationService:
    return ConversationService(db, state.hlc)


@router.get("", response_model=Page[ConversationOut])
async def list_conversations(
    db: DbDep,
    state: StateDep,
    auth: AuthDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    archived: bool = False,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[ConversationOut]:
    return await _service(db, state).list_conversations(
        auth.user.id, limit=limit, archived=archived, q=q, cursor=cursor
    )


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, db: DbDep, state: StateDep, auth: AuthDep
) -> ConversationOut:
    conv = await _service(db, state).create(auth.user.id, body)
    return ConversationOut.model_validate(conv)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: uuid.UUID, db: DbDep, state: StateDep, auth: AuthDep
) -> ConversationOut:
    conv = await _service(db, state).get(auth.user.id, conversation_id)
    return ConversationOut.model_validate(conv)


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    db: DbDep,
    state: StateDep,
    auth: AuthDep,
) -> ConversationOut:
    conv = await _service(db, state).update(auth.user.id, conversation_id, body)
    return ConversationOut.model_validate(conv)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, db: DbDep, state: StateDep, auth: AuthDep
) -> None:
    await _service(db, state).delete(auth.user.id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=Page[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    db: DbDep,
    state: StateDep,
    auth: AuthDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> Page[MessageOut]:
    return await _service(db, state).list_messages(
        auth.user.id, conversation_id, limit=limit, cursor=cursor
    )


@router.delete("/{conversation_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    db: DbDep,
    state: StateDep,
    auth: AuthDep,
) -> None:
    await _service(db, state).delete_message(auth.user.id, conversation_id, message_id)


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: uuid.UUID,
    db: DbDep,
    state: StateDep,
    auth: AuthDep,
    format: Literal["md", "json"] = "md",
) -> Response:
    conv, messages = await _service(db, state).export(auth.user.id, conversation_id)
    filename = f"conversacion-{conv.id}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "json":
        return JSONResponse(export_json(conv, messages), headers=headers)
    return PlainTextResponse(
        export_markdown(conv, messages), media_type="text/markdown; charset=utf-8", headers=headers
    )


@search_router.get("/messages", response_model=list[MessageSearchHit])
async def search_messages(
    db: DbDep,
    state: StateDep,
    auth: AuthDep,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[MessageSearchHit]:
    query = SearchQuery(q=q)
    return await _service(db, state).search(auth.user.id, query.q, limit=limit)
