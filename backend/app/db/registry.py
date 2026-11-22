"""Importa todos los modelos para que ``Base.metadata`` esté completo (Alembic, tests)."""

from app.db.base import Base
from app.modules.audit.models import AuditLog
from app.modules.auth.models import Device, RefreshToken
from app.modules.conversations.models import Conversation, Message
from app.modules.documents.models import Document, DocumentChunk, MessageAttachment
from app.modules.memory.models import Memory
from app.modules.settings.models import UserSettings
from app.modules.users.models import User

__all__ = [
    "AuditLog",
    "Base",
    "Conversation",
    "Device",
    "Document",
    "DocumentChunk",
    "Memory",
    "Message",
    "MessageAttachment",
    "RefreshToken",
    "User",
    "UserSettings",
]
