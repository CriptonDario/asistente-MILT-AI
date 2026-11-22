"""Pruebas unitarias del núcleo: IDs, HLC, paginación, rate limit, logging y configuración."""

from __future__ import annotations

import time
import uuid

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import RateLimitedError, ValidationAppError
from app.core.hlc import HLCTimestamp, HybridLogicalClock
from app.core.ids import uuid7, uuid7_timestamp_ms
from app.core.logging import REDACTED, redact
from app.core.pagination import decode_cursor, encode_cursor
from app.core.rate_limit import SlidingWindowRateLimiter


def test_uuid7_version_variant_and_order() -> None:
    ids = [uuid7() for _ in range(5000)]
    assert all(i.version == 7 for i in ids)
    assert all(i.variant == uuid.RFC_4122 for i in ids)
    assert ids == sorted(ids), "los UUIDv7 deben ser estrictamente crecientes"
    assert len(set(ids)) == len(ids)


def test_uuid7_timestamp_is_current() -> None:
    now_ms = time.time_ns() // 1_000_000
    assert abs(uuid7_timestamp_ms(uuid7()) - now_ms) < 5000


def test_hlc_monotonic_and_parse() -> None:
    clock = HybridLogicalClock("nodo-a")
    stamps = [HLCTimestamp.parse(clock.now()) for _ in range(200)]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)


def test_hlc_update_advances_past_remote() -> None:
    clock = HybridLogicalClock("a")
    future = HLCTimestamp(time.time_ns() // 1_000_000 + 60_000, 7, "b")
    updated = HLCTimestamp.parse(clock.update(str(future)))
    assert updated > future
    assert HLCTimestamp.parse(clock.now()) > updated


def test_hlc_rejects_bad_node() -> None:
    with pytest.raises(ValueError, match="nodo"):
        HybridLogicalClock("a:b")


def test_cursor_roundtrip_and_tampering() -> None:
    cursor = encode_cursor(["2026-01-01T00:00:00+00:00", "abc"])
    assert decode_cursor(cursor, 2) == ["2026-01-01T00:00:00+00:00", "abc"]
    with pytest.raises(ValidationAppError):
        decode_cursor(cursor, 1)
    with pytest.raises(ValidationAppError):
        decode_cursor("@@no-base64@@", 2)


@pytest.mark.anyio
async def test_rate_limiter_blocks_and_resets() -> None:
    limiter = SlidingWindowRateLimiter()
    for _ in range(3):
        await limiter.hit("k", limit=3, window_seconds=60)
    with pytest.raises(RateLimitedError) as info:
        await limiter.hit("k", limit=3, window_seconds=60)
    assert info.value.retry_after >= 1
    await limiter.reset("k")
    await limiter.hit("k", limit=3, window_seconds=60)


def test_redact_nested_secrets() -> None:
    data = {"user": "x", "password": "p", "nested": {"refresh_token": "t", "ok": [{"api_key": 1}]}}
    out = redact(data)
    assert out["password"] == REDACTED
    assert out["nested"]["refresh_token"] == REDACTED
    assert out["nested"]["ok"][0]["api_key"] == REDACTED
    assert out["user"] == "x"


def test_server_profile_requires_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, profile="server")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            profile="server",
            database_url="postgresql+asyncpg://u:p@db/milt",
            jwt_secret=SecretStr("corto"),
        )
    ok = Settings(  # type: ignore[call-arg]
        _env_file=None,
        profile="server",
        database_url="postgresql+asyncpg://u:p@db/milt",
        jwt_secret=SecretStr("x" * 40),
    )
    assert ok.resolved_database_url.startswith("postgresql")


def test_local_default_database_is_sqlite(tmp_path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]
    assert settings.is_sqlite
    assert settings.resolved_database_url.endswith("/milt.db")
