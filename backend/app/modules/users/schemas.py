"""Esquemas de entrada/salida de usuarios."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.security.rbac import Role

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")


def normalize_email(value: str) -> str:
    """Normaliza y valida un correo. Se permiten dominios locales (p. ej. ``yo@milt.local``)."""
    email = value.strip().lower()
    if not _EMAIL_RE.match(email) or ".." in email:
        raise ValueError("Correo electrónico no válido")
    return email


Email = Annotated[str, Field(min_length=3, max_length=320), AfterValidator(normalize_email)]
DisplayName = Annotated[str, Field(min_length=1, max_length=100)]
# La fortaleza se valida en el servicio (validate_password_strength) para dar mensajes claros.
Password = Annotated[str, Field(min_length=1, max_length=128)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    display_name: DisplayName
    password: Password
    role: Role = Role.USER


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None = None
    role: Role | None = None
    is_active: bool | None = None
