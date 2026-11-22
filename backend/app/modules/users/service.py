"""Lógica de negocio de usuarios (creación y administración)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.users import repository
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate
from app.security.passwords import PasswordService, validate_password_strength
from app.security.rbac import Role


class UserService:
    def __init__(self, db: AsyncSession, passwords: PasswordService) -> None:
        self.db = db
        self.passwords = passwords

    async def create(self, data: UserCreate) -> User:
        validate_password_strength(data.password, email=data.email)
        if await repository.get_by_email(self.db, data.email) is not None:
            raise ConflictError("Ya existe una cuenta con ese correo.")
        user = User(
            email=data.email,
            display_name=data.display_name.strip(),
            password_hash=await self.passwords.hash(data.password),
            role=data.role.value,
        )
        self.db.add(user)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("Ya existe una cuenta con ese correo.") from exc
        return user

    async def get(self, user_id: uuid.UUID) -> User:
        user = await repository.get_by_id(self.db, user_id)
        if user is None:
            raise NotFoundError("Usuario no encontrado.")
        return user

    async def list_users(self, *, limit: int, offset: int) -> Sequence[User]:
        return await repository.list_users(self.db, limit=limit, offset=offset)

    async def update(self, user_id: uuid.UUID, data: UserUpdate, *, actor: User) -> User:
        user = await self.get(user_id)
        losing_admin = user.role == Role.ADMIN.value and (
            (data.role is not None and data.role != Role.ADMIN) or data.is_active is False
        )
        if losing_admin and await repository.count_active_admins(self.db) <= 1:
            raise ValidationAppError("No se puede retirar el último administrador activo.")
        if user.id == actor.id and data.is_active is False:
            raise ValidationAppError("No puedes desactivar tu propia cuenta.")
        if data.display_name is not None:
            user.display_name = data.display_name.strip()
        if data.role is not None:
            user.role = data.role.value
        if data.is_active is not None:
            user.is_active = data.is_active
        await self.db.commit()
        return user

    async def delete(self, user_id: uuid.UUID, *, actor: User) -> None:
        user = await self.get(user_id)
        if user.id == actor.id:
            raise ValidationAppError("No puedes eliminar tu propia cuenta desde aquí.")
        if user.role == Role.ADMIN.value and await repository.count_active_admins(self.db) <= 1:
            raise ValidationAppError("No se puede eliminar el último administrador activo.")
        await self.db.delete(user)
        await self.db.commit()
