"""Tokens de acceso (JWT) y refresh tokens opacos."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.errors import UnauthorizedError

_ALGORITHM = "HS256"


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    role: str
    session_id: uuid.UUID
    expires_at: datetime


def hash_token(raw: str) -> str:
    """SHA-256 hex. Los refresh tokens nunca se guardan en claro."""
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_refresh_token() -> tuple[str, str]:
    """Devuelve ``(token_en_claro, hash)``. 256 bits de entropía."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


class TokenService:
    def __init__(self, *, secret: str, issuer: str, audience: str, access_ttl_seconds: int) -> None:
        if len(secret) < 32:
            raise ValueError("El secreto JWT debe tener al menos 32 caracteres")
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._ttl = timedelta(seconds=access_ttl_seconds)

    @property
    def access_ttl_seconds(self) -> int:
        return int(self._ttl.total_seconds())

    def create_access_token(
        self, *, user_id: uuid.UUID, role: str, session_id: uuid.UUID
    ) -> tuple[str, datetime]:
        now = datetime.now(UTC)
        expires_at = now + self._ttl
        payload = {
            "sub": str(user_id),
            "role": role,
            "sid": str(session_id),
            "iat": now,
            "nbf": now,
            "exp": expires_at,
            "iss": self._issuer,
            "aud": self._audience,
            "jti": secrets.token_hex(8),
            "typ": "access",
        }
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM), expires_at

    def decode_access_token(self, token: str) -> AccessClaims:
        try:
            data = jwt.decode(
                token,
                self._secret,
                algorithms=[_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=5,
                options={"require": ["exp", "iat", "nbf", "sub", "sid", "aud", "iss"]},
            )
            if data.get("typ") != "access":
                raise UnauthorizedError("Token no válido.")
            return AccessClaims(
                user_id=uuid.UUID(data["sub"]),
                role=str(data.get("role", "")),
                session_id=uuid.UUID(data["sid"]),
                expires_at=datetime.fromtimestamp(int(data["exp"]), UTC),
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("El token ha expirado.") from exc
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise UnauthorizedError("Token no válido.") from exc
