"""Endpoints de autenticación y sesiones."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.config import Settings
from app.core.deps import AuthDep, DbDep, StateDep, client_ip, require_local_profile
from app.core.errors import ForbiddenError, UnauthorizedError
from app.db.types import utcnow
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    LocalExchangeRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SessionOut,
    TokenResponse,
)
from app.modules.auth.service import AuthService, IssuedTokens
from app.modules.users.schemas import UserOut

REFRESH_COOKIE = "milt_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
CSRF_HEADER = "X-MILT-Client"
CSRF_HEADER_VALUE = "web"

router = APIRouter(prefix="/auth", tags=["auth"])
sessions_router = APIRouter(prefix="/sessions", tags=["auth"])


def _set_refresh_cookie(
    response: Response, settings: Settings, token: str, expires_at: datetime
) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=int((expires_at - utcnow()).total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _token_response(
    tokens: IssuedTokens, response: Response, settings: Settings, *, use_cookie: bool
) -> TokenResponse:
    if use_cookie:
        _set_refresh_cookie(response, settings, tokens.refresh_token, tokens.refresh_expires_at)
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=max(0, int((tokens.access_expires_at - utcnow()).total_seconds())),
        refresh_token=None if use_cookie else tokens.refresh_token,
        user=UserOut.model_validate(tokens.user),
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request, db: DbDep, state: StateDep) -> UserOut:
    """Crea una cuenta. La primera cuenta del sistema se convierte en administradora."""
    user = await AuthService(db, state).register(body, ip=client_ip(request))
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, db: DbDep, state: StateDep
) -> TokenResponse:
    tokens = await AuthService(db, state).login(
        body, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return _token_response(tokens, response, state.settings, use_cookie=body.use_cookie)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: DbDep,
    state: StateDep,
    body: RefreshRequest | None = None,
) -> TokenResponse:
    """Rota el refresh token (cookie HttpOnly o, para clientes nativos, en el cuerpo)."""
    body_token = body.refresh_token if body else None
    raw = body_token or request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise UnauthorizedError("Falta el refresh token.")
    if body_token is None and request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        # Protección CSRF: una cabecera propia obliga al navegador a hacer preflight CORS,
        # que falla para orígenes no autorizados (incluidas otras webs en localhost:<puerto>,
        # que para SameSite cuentan como el mismo sitio).
        raise ForbiddenError(f"Falta la cabecera {CSRF_HEADER}.")
    try:
        tokens = await AuthService(db, state).refresh(
            raw, ip=client_ip(request), user_agent=request.headers.get("user-agent")
        )
    except UnauthorizedError:
        if body_token is None:
            _clear_refresh_cookie(response, state.settings)
        raise
    return _token_response(tokens, response, state.settings, use_cookie=body_token is None)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, db: DbDep, state: StateDep, auth: AuthDep
) -> None:
    await AuthService(db, state).logout(auth, ip=client_ip(request))
    _clear_refresh_cookie(response, state.settings)


@router.post(
    "/local-exchange",
    response_model=TokenResponse,
    dependencies=[Depends(require_local_profile)],
)
async def local_exchange(
    body: LocalExchangeRequest,
    request: Request,
    response: Response,
    db: DbDep,
    state: StateDep,
) -> TokenResponse:
    """Solo perfil local: canjea el token de arranque de la app de escritorio."""
    tokens = await AuthService(db, state).local_exchange(
        body.token, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return _token_response(tokens, response, state.settings, use_cookie=body.use_cookie)


@router.get("/me", response_model=UserOut)
async def me(auth: AuthDep) -> UserOut:
    return UserOut.model_validate(auth.user)


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest, request: Request, db: DbDep, state: StateDep, auth: AuthDep
) -> None:
    """Cambia la contraseña y cierra todas las demás sesiones."""
    await AuthService(db, state).change_password(
        auth, body.current_password, body.new_password, ip=client_ip(request)
    )


@sessions_router.get("", response_model=list[SessionOut])
async def list_sessions(db: DbDep, state: StateDep, auth: AuthDep) -> list[SessionOut]:
    return await AuthService(db, state).list_sessions(auth)


@sessions_router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID, request: Request, db: DbDep, state: StateDep, auth: AuthDep
) -> None:
    await AuthService(db, state).revoke_session(auth, session_id, ip=client_ip(request))
