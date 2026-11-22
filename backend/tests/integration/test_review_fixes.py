"""Pruebas de regresión de la revisión de la Fase 2 (un test por hallazgo corregido)."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.errors import UnauthorizedError
from app.core.pagination import encode_cursor
from app.llm.base import ProviderUnavailableError
from app.llm.fake_provider import FakeLLMProvider
from app.modules.chat.service import ChatService, TurnRequest
from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    API,
    auth_headers,
    create_conversation,
    login,
    register,
)

WEB = {"X-MILT-Client": "web"}
WS = f"{API}/ws/chat"


def _admin(client: TestClient) -> str:
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    return str(login(client, ADMIN_EMAIL, ADMIN_PASSWORD).json()["access_token"])


def _send_ws(client: TestClient, token: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json(payload)
        events = []
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] in ("chat.done", "chat.error"):
                return events


# 1 --------------------------------------------------------------------------------
def test_concurrent_refresh_does_not_kill_session(client: TestClient) -> None:
    """Dos renovaciones casi simultáneas: la segunda recibe 409, la sesión sigue viva."""
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    old = login(client, ADMIN_EMAIL, ADMIN_PASSWORD, use_cookie=False).json()["refresh_token"]
    first = client.post(f"{API}/auth/refresh", json={"refresh_token": old})
    assert first.status_code == 200
    second = client.post(f"{API}/auth/refresh", json={"refresh_token": old})
    assert second.status_code == 409
    assert second.json()["code"] == "refresh_in_progress"
    new_access = first.json()["access_token"]
    assert client.get(f"{API}/auth/me", headers=auth_headers(new_access)).status_code == 200
    assert (
        client.post(
            f"{API}/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}
        ).status_code
        == 200
    )


def test_cookie_refresh_requires_csrf_header(client: TestClient) -> None:
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    blocked = client.post(f"{API}/auth/refresh")
    assert blocked.status_code == 403
    assert client.post(f"{API}/auth/refresh", headers=WEB).status_code == 200


# 2 --------------------------------------------------------------------------------
def test_audit_chain_survives_user_deletion(client: TestClient) -> None:
    token = _admin(client)
    headers = auth_headers(token)
    created = client.post(
        f"{API}/users",
        json={"email": "temp@milt.local", "display_name": "T", "password": "Clave-Temporal-2026"},
        headers=headers,
    ).json()
    login(client, "temp@milt.local", "Clave-Temporal-2026", use_cookie=False)
    assert client.delete(f"{API}/users/{created['id']}", headers=headers).status_code == 204
    verify = client.get(f"{API}/audit/verify", headers=headers).json()
    assert verify["valid"] is True, verify


# 3 --------------------------------------------------------------------------------
def test_failed_regenerate_keeps_previous_answer(
    client_factory: Callable[..., TestClient],
) -> None:
    llm = FakeLLMProvider(reply="Primera respuesta")
    client = client_factory(provider=llm)
    token = _admin(client)
    conv = create_conversation(client, token)
    _send_ws(
        client,
        token,
        {"type": "chat.send", "request_id": "a", "conversation_id": conv["id"], "content": "hola"},
    )

    llm.fail_with = ProviderUnavailableError("apagado")
    events = _send_ws(
        client, token, {"type": "chat.regenerate", "request_id": "b", "conversation_id": conv["id"]}
    )
    assert events[-1]["code"] == "provider_unavailable"

    items = client.get(
        f"{API}/conversations/{conv['id']}/messages", headers=auth_headers(token)
    ).json()["items"]
    assert [(m["role"], m["content"]) for m in items] == [
        ("user", "hola"),
        ("assistant", "Primera respuesta"),
    ]


# 4 --------------------------------------------------------------------------------
def test_local_bootstrap_token_is_single_use(client_factory: Callable[..., TestClient]) -> None:
    bootstrap = "b" * 40
    client = client_factory(local_bootstrap_token=SecretStr(bootstrap))
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert client.post(f"{API}/auth/local-exchange", json={"token": bootstrap}).status_code == 200
    again = client.post(f"{API}/auth/local-exchange", json={"token": bootstrap})
    assert again.status_code == 401


# 5 --------------------------------------------------------------------------------
def test_concurrent_failed_logins_all_count(client_factory: Callable[..., TestClient]) -> None:
    client = client_factory(lockout_threshold=5, login_attempts_per_minute=100)
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    state = client.app.state.milt  # type: ignore[attr-defined]

    async def burst() -> None:
        from app.modules.auth.schemas import LoginRequest
        from app.modules.auth.service import AuthService

        async def attempt() -> None:
            async with state.sessionmaker() as db:
                with contextlib.suppress(UnauthorizedError):
                    await AuthService(db, state).login(
                        LoginRequest(email=ADMIN_EMAIL, password="incorrecta-123456"),
                        ip="1.2.3.4",
                        user_agent=None,
                    )

        await asyncio.gather(*(attempt() for _ in range(5)))

    client.portal.call(burst)  # type: ignore[union-attr]
    # Las 5 fallan a la vez y el bloqueo se aplica: la contraseña correcta ya no entra.
    assert login(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 401


# 6 --------------------------------------------------------------------------------
def test_password_change_is_rate_limited(client: TestClient) -> None:
    headers = auth_headers(_admin(client))
    codes = [
        client.patch(
            f"{API}/auth/me/password",
            json={"current_password": f"incorrecta-{i:06d}", "new_password": "Nueva-Clave-2026"},
            headers=headers,
        ).status_code
        for i in range(7)
    ]
    assert codes[:5] == [401] * 5
    assert 429 in codes[5:]


# 7 --------------------------------------------------------------------------------
def test_invalid_model_does_not_poison_conversation(client: TestClient, admin_token: str) -> None:
    conv = create_conversation(client, admin_token)
    bad = _send_ws(
        client,
        admin_token,
        {
            "type": "chat.send",
            "request_id": "x",
            "conversation_id": conv["id"],
            "content": "hola",
            "model": "no-existe",
        },
    )
    assert bad[-1]["code"] == "model_not_found"
    good = _send_ws(
        client,
        admin_token,
        {"type": "chat.send", "request_id": "y", "conversation_id": conv["id"], "content": "hola"},
    )
    assert good[-1]["type"] == "chat.done"
    items = client.get(
        f"{API}/conversations/{conv['id']}/messages", headers=auth_headers(admin_token)
    ).json()["items"]
    assert [m["role"] for m in items] == ["user", "assistant"], "el intento fallido no se guarda"


# 8 --------------------------------------------------------------------------------
def test_double_cancel_keeps_partial_answer(client_factory: Callable[..., TestClient]) -> None:
    llm = FakeLLMProvider(reply=" ".join(f"p{i}" for i in range(300)), delay=0.01)
    client = client_factory(provider=llm)
    token = _admin(client)
    conv = create_conversation(client, token)
    me = client.get(f"{API}/auth/me", headers=auth_headers(token)).json()
    state = client.app.state.milt  # type: ignore[attr-defined]
    events: list[dict[str, Any]] = []

    async def scenario() -> None:
        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        turn = TurnRequest(
            request_id="dc",
            user_id=uuid.UUID(me["id"]),
            user_name="Admin",
            conversation_id=uuid.UUID(conv["id"]),
            content="escribe",
        )
        task = asyncio.create_task(ChatService(state).run_turn(turn, emit))
        while sum(1 for e in events if e["type"] == "chat.delta") < 3:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # segunda cancelación durante el guardado
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0.3)  # deja terminar la tarea protegida

    client.portal.call(scenario)  # type: ignore[union-attr]
    assert events[-1] == {
        "type": "chat.error",
        "request_id": "dc",
        "code": "cancelled",
        "detail": "Generación cancelada.",
    }
    items = client.get(
        f"{API}/conversations/{conv['id']}/messages", headers=auth_headers(token)
    ).json()["items"]
    assert items[-1]["role"] == "assistant"
    assert items[-1]["status"] == "cancelled"
    assert items[-1]["content"]


# 9 --------------------------------------------------------------------------------
def test_sse_does_not_hold_db_connection(client_factory: Callable[..., TestClient]) -> None:
    # Proveedor lento: la comprobación se hace en mitad de la generación, no durante
    # el guardado final de la respuesta.
    llm = FakeLLMProvider(reply=" ".join(f"t{i}" for i in range(50)), delay=0.02)
    client = client_factory(provider=llm)
    token = _admin(client)
    conv = create_conversation(client, token)
    state = client.app.state.milt  # type: ignore[attr-defined]
    with client.stream(
        "POST",
        f"{API}/chat/completions",
        json={"conversation_id": conv["id"], "content": "hola"},
        headers=auth_headers(token),
    ) as response:
        lines = response.iter_lines()
        deltas = 0
        for line in lines:
            if line.startswith("event: chat.delta"):
                deltas += 1
                if deltas == 5:
                    break
        assert state.engine.pool.checkedout() == 0
        for _ in lines:
            pass


# 10 -------------------------------------------------------------------------------
def test_naive_cursor_is_422(client: TestClient, admin_token: str) -> None:
    cursor = encode_cursor(["2026-01-01T00:00:00", str(uuid.uuid4())])
    response = client.get(f"{API}/conversations?cursor={cursor}", headers=auth_headers(admin_token))
    assert response.status_code == 422


# extra: estado de configuración inicial -------------------------------------------
def test_setup_status(client: TestClient) -> None:
    before = client.get(f"{API}/system/setup").json()
    assert before == {"needs_setup": True, "registration_open": True, "profile": "local"}
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert client.get(f"{API}/system/setup").json()["needs_setup"] is False
