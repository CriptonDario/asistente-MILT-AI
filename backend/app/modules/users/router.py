"""Administración de usuarios (solo administradores)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.core.deps import AdminDep, DbDep, StateDep, client_ip
from app.modules.users.schemas import UserCreate, UserOut, UserUpdate
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    db: DbDep,
    state: StateDep,
    _admin: AdminDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserOut]:
    users = await UserService(db, state.passwords).list_users(limit=limit, offset=offset)
    return [UserOut.model_validate(u) for u in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate, request: Request, db: DbDep, state: StateDep, admin: AdminDep
) -> UserOut:
    user = await UserService(db, state.passwords).create(body)
    await state.audit.record(
        "user.create",
        user_id=admin.user.id,
        target_type="user",
        target_id=user.id,
        ip=client_ip(request),
        details={"role": user.role},
    )
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    db: DbDep,
    state: StateDep,
    admin: AdminDep,
) -> UserOut:
    user = await UserService(db, state.passwords).update(user_id, body, actor=admin.user)
    await state.audit.record(
        "user.update",
        user_id=admin.user.id,
        target_type="user",
        target_id=user.id,
        ip=client_ip(request),
        details=body.model_dump(exclude_none=True, mode="json"),
    )
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID, request: Request, db: DbDep, state: StateDep, admin: AdminDep
) -> None:
    await UserService(db, state.passwords).delete(user_id, actor=admin.user)
    await state.audit.record(
        "user.delete",
        user_id=admin.user.id,
        target_type="user",
        target_id=user_id,
        ip=client_ip(request),
    )
