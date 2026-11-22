"""Resolución del usuario autenticado a partir de los claims del token de acceso."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.types import utcnow
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User
from app.security.tokens import AccessClaims


@dataclass(frozen=True)
class AuthContext:
    user: User
    session_id: uuid.UUID
    expires_at: datetime


async def session_is_active(db: AsyncSession, family_id: uuid.UUID) -> bool:
    stmt = (
        select(RefreshToken.id)
        .where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utcnow(),
        )
        .limit(1)
    )
    return (await db.scalar(stmt)) is not None


async def authenticate_claims(db: AsyncSession, claims: AccessClaims) -> AuthContext:
    """Valida que el usuario siga activo y que la sesión no haya sido revocada."""
    user = await db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Usuario no válido o desactivado.")
    if not await session_is_active(db, claims.session_id):
        raise UnauthorizedError("La sesión ha sido cerrada o ha expirado.")
    return AuthContext(user=user, session_id=claims.session_id, expires_at=claims.expires_at)
