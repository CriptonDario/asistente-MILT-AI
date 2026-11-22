"""Dependencias de FastAPI compartidas por los routers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.state import AppState
from app.modules.auth.context import AuthContext, authenticate_claims
from app.security.rbac import Permission, has_permission


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.milt
    return state


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with get_state(request).sessionmaker() as session:
        yield session


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def extract_bearer(header: str | None) -> str:
    if not header:
        raise UnauthorizedError("Falta la cabecera Authorization.")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError("Formato de Authorization no válido.")
    return token.strip()


async def get_auth(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> AuthContext:
    state = get_state(request)
    claims = state.tokens.decode_access_token(extract_bearer(request.headers.get("authorization")))
    return await authenticate_claims(db, claims)


def require_permission(permission: Permission) -> Callable[..., Awaitable[AuthContext]]:
    async def dependency(auth: Annotated[AuthContext, Depends(get_auth)]) -> AuthContext:
        if not has_permission(auth.user.role, permission):
            raise ForbiddenError("No tienes permiso para realizar esta acción.")
        return auth

    return dependency


def require_local_profile(request: Request) -> None:
    """Oculta (404) los endpoints que solo existen en el perfil local."""
    if get_state(request).settings.profile != "local":
        raise NotFoundError()


StateDep = Annotated[AppState, Depends(get_state)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
AuthDep = Annotated[AuthContext, Depends(get_auth)]
AdminDep = Annotated[AuthContext, Depends(require_permission(Permission.USERS_MANAGE))]
