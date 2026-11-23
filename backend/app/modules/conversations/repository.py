"""Acceso a datos de conversaciones y mensajes.

Todas las consultas filtran por ``user_id`` para impedir el acceso a datos ajenos (IDOR).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversations.models import Conversation, Message
from app.modules.documents.models import Document, MessageAttachment


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_conversation(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
        Conversation.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_conversations(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int,
    archived: bool,
    q: str | None,
    after: tuple[datetime, uuid.UUID] | None,
) -> Sequence[Conversation]:
    stmt: Select[tuple[Conversation]] = select(Conversation).where(
        Conversation.user_id == user_id,
        Conversation.deleted_at.is_(None),
        Conversation.archived.is_(archived),
    )
    if q:
        stmt = stmt.where(Conversation.title.ilike(f"%{escape_like(q)}%", escape="\\"))
    if after is not None:
        updated_at, conv_id = after
        stmt = stmt.where(
            or_(
                Conversation.updated_at < updated_at,
                and_(Conversation.updated_at == updated_at, Conversation.id < conv_id),
            )
        )
    stmt = stmt.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit)
    return (await db.scalars(stmt)).all()


async def list_messages(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    limit: int,
    after_id: uuid.UUID | None = None,
) -> Sequence[Message]:
    """Mensajes en orden cronológico (los UUIDv7 son ordenables por tiempo)."""
    stmt = select(Message).where(
        Message.conversation_id == conversation_id, Message.deleted_at.is_(None)
    )
    if after_id is not None:
        stmt = stmt.where(Message.id > after_id)
    stmt = stmt.order_by(Message.id).limit(limit)
    return (await db.scalars(stmt)).all()


async def recent_messages(
    db: AsyncSession, conversation_id: uuid.UUID, *, limit: int
) -> list[Message]:
    """Últimos ``limit`` mensajes visibles, devueltos en orden cronológico."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
        .order_by(Message.id.desc())
        .limit(limit)
    )
    rows = list((await db.scalars(stmt)).all())
    rows.reverse()
    return rows


async def get_message(
    db: AsyncSession, conversation_id: uuid.UUID, message_id: uuid.UUID
) -> Message | None:
    stmt = select(Message).where(
        Message.id == message_id,
        Message.conversation_id == conversation_id,
        Message.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def conversation_document_ids(
    db: AsyncSession, conversation_id: uuid.UUID
) -> list[uuid.UUID]:
    """Documentos adjuntados en cualquier mensaje visible de la conversación (su ámbito RAG)."""
    stmt = (
        select(MessageAttachment.document_id)
        .join(Message, Message.id == MessageAttachment.message_id)
        .join(Document, Document.id == MessageAttachment.document_id)
        .where(
            Message.conversation_id == conversation_id,
            Message.deleted_at.is_(None),
            Document.status == "ready",
        )
        .distinct()
    )
    return list((await db.scalars(stmt)).all())


async def attachments_for_messages(
    db: AsyncSession, message_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, str]]]:
    if not message_ids:
        return {}
    rows = (
        await db.execute(
            select(MessageAttachment.message_id, Document.id, Document.filename)
            .join(Document, Document.id == MessageAttachment.document_id)
            .where(MessageAttachment.message_id.in_(list(message_ids)))
        )
    ).all()
    out: dict[uuid.UUID, list[dict[str, str]]] = {}
    for message_id, document_id, filename in rows:
        out.setdefault(message_id, []).append(
            {"document_id": str(document_id), "filename": filename}
        )
    return out


async def count_messages(db: AsyncSession, conversation_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
    )
    return int(await db.scalar(stmt) or 0)


async def search_messages(
    db: AsyncSession, user_id: uuid.UUID, q: str, *, limit: int
) -> Sequence[tuple[Message, Conversation]]:
    """Búsqueda textual simple (LIKE). Se sustituirá por FTS5/tsvector en la Fase 4."""
    stmt = (
        select(Message, Conversation)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
            Message.deleted_at.is_(None),
            Message.role.in_(("user", "assistant")),
            Message.content.ilike(f"%{escape_like(q)}%", escape="\\"),
        )
        .order_by(Message.id.desc())
        .limit(limit)
    )
    return [(m, c) for m, c in (await db.execute(stmt)).all()]
