"""Pruebas unitarias de contraseñas (Argon2id), tokens JWT y RBAC."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.errors import UnauthorizedError, ValidationAppError
from app.security.passwords import PasswordService, validate_password_strength
from app.security.rbac import Permission, Role, has_permission
from app.security.tokens import TokenService, generate_refresh_token, hash_token

SECRET = "k" * 48


@pytest.fixture
def passwords() -> PasswordService:
    return PasswordService(time_cost=1, memory_cost_kib=1024, parallelism=1)


@pytest.fixture
def tokens() -> TokenService:
    return TokenService(
        secret=SECRET, issuer="milt-ai", audience="milt-api", access_ttl_seconds=900
    )


@pytest.mark.anyio
async def test_argon2id_hash_and_verify(passwords: PasswordService) -> None:
    hashed = await passwords.hash("una-clave-larga-y-segura")
    assert hashed.startswith("$argon2id$")
    assert await passwords.verify(hashed, "una-clave-larga-y-segura")
    assert not await passwords.verify(hashed, "otra-clave-distinta")
    assert not await passwords.verify("no-es-un-hash", "x")


@pytest.mark.anyio
async def test_needs_rehash_when_params_change(passwords: PasswordService) -> None:
    hashed = await passwords.hash("una-clave-larga-y-segura")
    stronger = PasswordService(time_cost=2, memory_cost_kib=2048, parallelism=1)
    assert not passwords.needs_rehash(hashed)
    assert stronger.needs_rehash(hashed)


@pytest.mark.parametrize(
    "password",
    ["corta", "password1234", "aaaaaaaaaaaaaaaa", "x" * 129],
)
def test_password_policy_rejects(password: str) -> None:
    with pytest.raises(ValidationAppError):
        validate_password_strength(password)


def test_password_policy_rejects_email() -> None:
    with pytest.raises(ValidationAppError):
        validate_password_strength("yo@ejemplo.local", email="yo@ejemplo.local")


def test_password_policy_accepts_passphrase() -> None:
    validate_password_strength("caballo correcto batería grapa")


def test_access_token_roundtrip(tokens: TokenService) -> None:
    user_id, sid = uuid.uuid4(), uuid.uuid4()
    token, expires = tokens.create_access_token(user_id=user_id, role="admin", session_id=sid)
    claims = tokens.decode_access_token(token)
    assert claims.user_id == user_id
    assert claims.session_id == sid
    assert claims.role == "admin"
    assert abs((claims.expires_at - expires).total_seconds()) < 1


def test_access_token_rejects_tampering(tokens: TokenService) -> None:
    token, _ = tokens.create_access_token(
        user_id=uuid.uuid4(), role="user", session_id=uuid.uuid4()
    )
    other = TokenService(
        secret="z" * 48, issuer="milt-ai", audience="milt-api", access_ttl_seconds=60
    )
    with pytest.raises(UnauthorizedError):
        other.decode_access_token(token)
    with pytest.raises(UnauthorizedError):
        tokens.decode_access_token(token[:-2] + "xx")


def test_access_token_rejects_alg_none_and_expired(tokens: TokenService) -> None:
    now = datetime.now(UTC)
    base = {
        "sub": str(uuid.uuid4()),
        "sid": str(uuid.uuid4()),
        "role": "admin",
        "iss": "milt-ai",
        "aud": "milt-api",
        "typ": "access",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
    }
    unsigned = jwt.encode(base, key=None, algorithm="none")
    with pytest.raises(UnauthorizedError):
        tokens.decode_access_token(unsigned)

    expired = jwt.encode(
        {
            **base,
            "iat": now - timedelta(hours=1),
            "nbf": now - timedelta(hours=1),
            "exp": now - timedelta(minutes=10),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError, match="expirado"):
        tokens.decode_access_token(expired)

    wrong_type = jwt.encode({**base, "typ": "refresh"}, SECRET, algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        tokens.decode_access_token(wrong_type)


def test_token_service_requires_long_secret() -> None:
    with pytest.raises(ValueError, match="32"):
        TokenService(secret="corto", issuer="i", audience="a", access_ttl_seconds=60)


def test_refresh_tokens_are_random_and_hashed() -> None:
    raw1, h1 = generate_refresh_token()
    raw2, _ = generate_refresh_token()
    assert raw1 != raw2
    assert h1 == hash_token(raw1)
    assert len(h1) == 64
    assert raw1 not in h1


def test_rbac() -> None:
    assert has_permission(Role.ADMIN, Permission.USERS_MANAGE)
    assert not has_permission(Role.USER, Permission.USERS_MANAGE)
    assert not has_permission("desconocido", Permission.USERS_MANAGE)
