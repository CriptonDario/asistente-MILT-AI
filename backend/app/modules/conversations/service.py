"""Lógica de negocio de conversaciones."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationAppError
from app.core.hlc import HybridLogicalClock
from app.core.pagination import Page, decode_cursor, encode_cursor
from app.modules.conversations import repository
from app.modules.conversations.models import Conversation, Message
from app.modules.conversations.schemas import (
    AttachmentOut,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
    MessageSearchHit,
)

TITLE_MAX_CHARS = 60


def title_from_text(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= TITLE_MAX_CHARS:
        return collapsed
    return collapsed[: TITLE_MAX_CHARS - 1].rstrip() + "…"


def snippet(text: str, query: str, *, radius: int = 60) -> str:
    lowered = text.lower()
    pos = lowered.find(query.lower())
    if pos < 0:
        return text[: radius * 2]
    start = max(0, pos - radius)
    end = min(len(text), pos + len(query) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


class ConversationService:
    def __init__(self, db: AsyncSession, hlc: HybridLogicalClock) -> None:
        self.db = db
        self.hlc = hlc

    async def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
        conv = await repository.get_conversation(self.db, user_id, conversation_id)
        if conv is None:
            # 404 también para conversaciones de otros usuarios: no se revela su existencia.
            raise NotFoundError("Conversación no encontrada.")
        return conv

    async def create(self, user_id: uuid.UUID, data: ConversationCreate) -> Conversation:
        conv = Conversation(
            user_id=user_id,
            title=data.title.strip() if data.title else None,
            model=data.model,
            agent_profile=data.agent_profile,
            params=data.params.model_dump(exclude_none=True) if data.params else None,
            updated_hlc=self.hlc.now(),
        )
        self.db.add(conv)
        await self.db.commit()
        return conv

    async def list_conversations(
        self,
        user_id: uuid.UUID,
        *,
        limit: int,
        archived: bool,
        q: str | None,
        cursor: str | None,
    ) -> Page[ConversationOut]:
        after: tuple[datetime, uuid.UUID] | None = None
        if cursor:
            raw_ts, raw_id = decode_cursor(cursor, 2)
            try:
                after = (datetime.fromisoformat(raw_ts), uuid.UUID(raw_id))
            except ValueError as exc:
                raise ValidationAppError("Cursor de paginación no válido.") from exc
            if after[0].tzinfo is None:
                raise ValidationAppError("Cursor de paginación no válido.")
        rows = await repository.list_conversations(
            self.db, user_id, limit=limit + 1, archived=archived, q=q, after=after
        )
        items = list(rows[:limit])
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = encode_cursor([last.updated_at.isoformat(), str(last.id)])
        return Page[ConversationOut](
            items=[ConversationOut.model_validate(c) for c in items], next_cursor=next_cursor
        )

    async def update(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, data: ConversationUpdate
    ) -> Conversation:
        conv = await self.get(user_id, conversation_id)
        fields = data.model_fields_set
        if "title" in fields:
            conv.title = data.title.strip() if data.title else None
        if "model" in fields:
            conv.model = data.model
        if "agent_profile" in fields and data.agent_profile is not None:
            conv.agent_profile = data.agent_profile
        if "params" in fields:
            conv.params = data.params.model_dump(exclude_none=True) if data.params else None
        if "pinned" in fields and data.pinned is not None:
            conv.pinned = data.pinned
        if "archived" in fields and data.archived is not None:
            conv.archived = data.archived
        conv.touch(self.hlc.now())
        await self.db.commit()
        return conv

    async def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        conv = await self.get(user_id, conversation_id)
        conv.soft_delete(self.hlc.now())
        await self.db.commit()

    async def list_messages(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> Page[MessageOut]:
        await self.get(user_id, conversation_id)
        after_id = None
        if cursor:
            (raw_id,) = decode_cursor(cursor, 1)
            try:
                after_id = uuid.UUID(raw_id)
            except ValueError as exc:
                raise ValidationAppError("Cursor de paginación no válido.") from exc
        rows = await repository.list_messages(
            self.db, conversation_id, limit=limit + 1, after_id=after_id
        )
        items = list(rows[:limit])
        next_cursor = encode_cursor([str(items[-1].id)]) if len(rows) > limit else None
        attachments = await repository.attachments_for_messages(
            self.db, [m.id for m in items if m.role == "user"]
        )
        out = []
        for message in items:
            item = MessageOut.model_validate(message)
            item.attachments = [
                AttachmentOut.model_validate(a) for a in attachments.get(message.id, [])
            ]
            out.append(item)
        return Page[MessageOut](items=out, next_cursor=next_cursor)

    async def delete_message(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, message_id: uuid.UUID
    ) -> None:
        conv = await self.get(user_id, conversation_id)
        message = await repository.get_message(self.db, conversation_id, message_id)
        if message is None:
            raise NotFoundError("Mensaje no encontrado.")
        hlc = self.hlc.now()
        message.soft_delete(hlc)
        conv.touch(hlc)
        await self.db.commit()

    async def export(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> tuple[Conversation, Sequence[Message]]:
        conv = await self.get(user_id, conversation_id)
        messages = await repository.list_messages(self.db, conversation_id, limit=100_000)
        return conv, messages

    async def search(self, user_id: uuid.UUID, q: str, *, limit: int) -> list[MessageSearchHit]:
        rows = await repository.search_messages(self.db, user_id, q, limit=limit)
        return [
            MessageSearchHit(
                message_id=m.id,
                conversation_id=c.id,
                conversation_title=c.title,
                role=m.role,
                snippet=snippet(m.content, q),
                created_at=m.created_at,
            )
            for m, c in rows
        ]


def export_markdown(conv: Conversation, messages: Sequence[Message]) -> str:
    labels = {"user": "Tú", "assistant": "MILT", "system": "Sistema", "tool": "Herramienta"}
    lines = [f"# {conv.title or 'Conversación'}", ""]
    lines.append(f"_Creada: {conv.created_at.isoformat()} · Modelo: {conv.model or '—'}_")
    lines.append("")
    for m in messages:
        lines.append(f"## {labels.get(m.role, m.role)}")
        lines.append("")
        lines.append(m.content)
        lines.append("")
    return "\n".join(lines)


def export_json(conv: Conversation, messages: Sequence[Message]) -> dict[str, Any]:
    return {
        "conversation": ConversationOut.model_validate(conv).model_dump(mode="json"),
        "messages": [MessageOut.model_validate(m).model_dump(mode="json") for m in messages],
    }
