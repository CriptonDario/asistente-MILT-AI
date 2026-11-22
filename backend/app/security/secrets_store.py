"""Gestión de secretos locales.

Perfil local: si no se define ``MILT_JWT_SECRET``, se genera uno y se guarda en
``<data_dir>/secrets/jwt.key`` (dentro del perfil del usuario). En la Fase 6 se
migrará al Administrador de credenciales de Windows mediante ``keyring``.
Perfil servidor: el secreto es obligatorio por variable de entorno (validado en Settings).
"""

from __future__ import annotations

import os
import secrets

from app.core.config import Settings


def load_or_create_jwt_secret(settings: Settings) -> str:
    if settings.jwt_secret is not None:
        return settings.jwt_secret.get_secret_value()

    secrets_dir = settings.data_dir / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    key_file = secrets_dir / "jwt.key"
    if key_file.exists():
        value = key_file.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value

    value = secrets.token_urlsafe(64)
    # Creación exclusiva con permisos restrictivos (efectivo en POSIX; en Windows el
    # directorio del perfil de usuario ya está restringido a su propietario).
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    return value
