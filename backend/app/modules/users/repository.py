"""Acceso a datos de usuarios."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from app.security.rbac import Role


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def count_users(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(User)) or 0)


async def count_active_admins(db: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .where(User.role == Role.ADMIN.value, User.is_active.is_(True))
    )
    return int(await db.scalar(stmt) or 0)


async def first_admin(db: AsyncSession) -> User | None:
    stmt = (
        select(User)
        .where(User.role == Role.ADMIN.value, User.is_active.is_(True))
        .order_by(User.created_at)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_users(db: AsyncSession, *, limit: int, offset: int) -> Sequence[User]:
    stmt = select(User).order_by(User.created_at).limit(limit).offset(offset)
    return (await db.scalars(stmt)).all()
