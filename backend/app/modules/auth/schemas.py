"""Esquemas de autenticación y sesiones."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.users.schemas import DisplayName, Email, Password, UserOut

Platform = Literal["windows", "web", "android", "linux", "macos", "other"]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    display_name: DisplayName
    password: Password


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: Password
    device_name: Annotated[str, Field(min_length=1, max_length=100)] = "Navegador"
    platform: Platform = "web"
    #: ``True``: refresh token en cookie HttpOnly (navegador). ``False``: en el cuerpo
    #: de la respuesta (clientes nativos: escritorio, Android, sincronización).
    use_cookie: bool = True


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: Annotated[str, Field(min_length=20, max_length=200)] | None = None


class LocalExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=20, max_length=200)]
    use_cookie: bool = False


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: Password
    new_password: Password


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - no es una contraseña
    expires_in: int
    refresh_token: str | None = None
    user: UserOut


class SessionOut(BaseModel):
    id: uuid.UUID
    device_name: str | None
    platform: str | None
    started_at: datetime
    last_refresh_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool
