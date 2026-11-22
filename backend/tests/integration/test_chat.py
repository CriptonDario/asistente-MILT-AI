"""Chat por WebSocket y SSE con el proveedor simulado."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.llm.base import ProviderUnavailableError
from app.llm.fake_provider import FakeLLMProvider
from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    API,
    auth_headers,
    create_conversation,
    login,
    register,
)

WS = f"{API}/ws/chat"


def ws_auth(ws: WebSocketTestSession, token: str) -> dict[str, Any]:
    ws.send_json({"type": "auth", "token": token})
    ready: dict[str, Any] = ws.receive_json()
    assert ready["type"] == "ready", ready
    return ready


def receive_until(ws: WebSocketTestSession, *types: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        event: dict[str, Any] = ws.receive_json()
        events.append(event)
        if event["type"] in types:
            return events


def test_ws_requires_auth(client: TestClient) -> None:
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "auth", "token": "token-invalido-123"})
        assert ws.receive_json()["code"] == "unauthorized"
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
        assert info.value.code == 4401


def test_ws_rejects_foreign_origin(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as info,
        client.websocket_connect(WS, headers={"origin": "https://evil.example"}) as ws,
    ):
        ws.receive_json()
    assert info.value.code == 1008


def test_ws_full_turn_streams_and_persists(
    client: TestClient, admin_token: str, fake_llm: FakeLLMProvider
) -> None:
    conv = create_conversation(client, admin_token)
    with client.websocket_connect(WS) as ws:
        ws_auth(ws, admin_token)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_json(
            {
                "type": "chat.send",
                "request_id": "r1",
                "conversation_id": conv["id"],
                "content": "¿Quién eres?",
                "params": {"temperature": 0.1},
            }
        )
        events = receive_until(ws, "chat.done", "chat.error")

    types = [e["type"] for e in events]
    assert types[0] == "chat.started"
    assert types[-1] == "chat.done"
    text = "".join(e["text"] for e in events if e["type"] == "chat.delta")
    assert text == fake_llm.reply
    assert events[-1]["usage"]["completion_tokens"] > 0

    # El prompt de sistema y los parámetros llegan al proveedor.
    call = fake_llm.calls[-1]
    assert call["messages"][0].role == "system"
    assert "MILT" in call["messages"][0].content
    assert call["messages"][-1].content == "¿Quién eres?"
    assert call["params"].temperature == 0.1
    assert call["params"].num_ctx == 4096

    headers = auth_headers(admin_token)
    messages = client.get(f"{API}/conversations/{conv['id']}/messages", headers=headers).json()
    assert [m["role"] for m in messages["items"]] == ["user", "assistant"]
    assert messages["items"][1]["content"] == fake_llm.reply
    assert messages["items"][1]["status"] == "complete"
    assert messages["items"][1]["id"] == events[0]["message_id"]

    refreshed = client.get(f"{API}/conversations/{conv['id']}", headers=headers).json()
    assert refreshed["title"] == "¿Quién eres?", "el título se genera con el primer mensaje"
    assert refreshed["model"] == "fake-model"


def test_ws_history_is_sent_as_context(
    client: TestClient, admin_token: str, fake_llm: FakeLLMProvider
) -> None:
    conv = create_conversation(client, admin_token)
    with client.websocket_connect(WS) as ws:
        ws_auth(ws, admin_token)
        for i, text in enumerate(["Me llamo Dario", "¿Cómo me llamo?"]):
            ws.send_json(
                {
                    "type": "chat.send",
                    "request_id": f"h{i}",
                    "conversation_id": conv["id"],
                    "content": text,
                }
            )
            receive_until(ws, "chat.done")
    roles = [m.role for m in fake_llm.calls[-1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_ws_regenerate_replaces_last_answer(
    client: TestClient, admin_token: str, fake_llm: FakeLLMProvider
) -> None:
    conv = create_conversation(client, admin_token)
    with client.websocket_connect(WS) as ws:
        ws_auth(ws, admin_token)
        ws.send_json(
            {
                "type": "chat.send",
                "request_id": "a",
                "conversation_id": conv["id"],
                "content": "Hola",
            }
        )
        receive_until(ws, "chat.done")
        fake_llm.reply = "Respuesta regenerada"
        ws.send_json({"type": "chat.regenerate", "request_id": "b", "conversation_id": conv["id"]})
        receive_until(ws, "chat.done")

    items = client.get(
        f"{API}/conversations/{conv['id']}/messages", headers=auth_headers(admin_token)
    ).json()["items"]
    assert [m["role"] for m in items] == ["user", "assistant"]
    assert items[1]["content"] == "Respuesta regenerada"


def test_ws_cancel_saves_partial_answer(client_factory: Callable[..., TestClient]) -> None:
    slow = FakeLLMProvider(reply=" ".join(f"palabra{i}" for i in range(200)), delay=0.02)
    client = client_factory(provider=slow)
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    token = login(client, ADMIN_EMAIL, ADMIN_PASSWORD).json()["access_token"]
    conv = create_conversation(client, token)

    with client.websocket_connect(WS) as ws:
        ws_auth(ws, token)
        ws.send_json(
            {
                "type": "chat.send",
                "request_id": "slow",
                "conversation_id": conv["id"],
                "content": "Escribe mucho",
            }
        )
        receive_until(ws, "chat.delta")
        receive_until(ws, "chat.delta")
        ws.send_json({"type": "chat.cancel", "request_id": "slow"})
        events = receive_until(ws, "chat.error", "chat.done")
    assert events[-1]["type"] == "chat.error"
    assert events[-1]["code"] == "cancelled"

    items = client.get(
        f"{API}/conversations/{conv['id']}/messages", headers=auth_headers(token)
    ).json()["items"]
    assert items[-1]["status"] == "cancelled"
    assert 0 < len(items[-1]["content"]) < len(slow.reply)


def test_ws_errors_are_reported(client: TestClient, admin_token: str, user_token: str) -> None:
    conv = create_conversation(client, admin_token)
    with client.websocket_connect(WS) as ws:
        ws_auth(ws, admin_token)

        ws.send_text("{no es json")
        assert ws.receive_json()["code"] == "invalid_message"

        ws.send_json({"type": "chat.send", "request_id": "x", "conversation_id": conv["id"]})
        assert ws.receive_json()["code"] == "invalid_message"

        ws.send_json(
            {
                "type": "chat.send",
                "request_id": "m",
                "conversation_id": conv["id"],
                "content": "hola",
                "model": "no-existe",
            }
        )
        events = receive_until(ws, "chat.error")
        assert events[-1]["code"] == "model_not_found"

        ws.send_json({"type": "chat.cancel", "request_id": "nada"})
        assert ws.receive_json()["code"] == "not_found"

        ws.send_json({"type": "auth", "token": user_token})
        assert ws.receive_json()["code"] == "unauthorized", "no se puede cambiar de usuario"

    # Conversación ajena: 404 como evento.
    with client.websocket_connect(WS) as ws:
        ws_auth(ws, user_token)
        ws.send_json(
            {
                "type": "chat.send",
                "request_id": "z",
                "conversation_id": conv["id"],
                "content": "hola",
            }
        )
        assert receive_until(ws, "chat.error")[-1]["code"] == "not_found"


def test_ws_provider_unavailable(client_factory: Callable[..., TestClient]) -> None:
    down = FakeLLMProvider(fail_with=ProviderUnavailableError("Ollama apagado"))
    client = client_factory(provider=down)
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    token = login(client, ADMIN_EMAIL, ADMIN_PASSWORD).json()["access_token"]
    conv = create_conversation(client, token)
    with client.websocket_connect(WS) as ws:
        ws_auth(ws, token)
        ws.send_json(
            {
                "type": "chat.send",
                "request_id": "d",
                "conversation_id": conv["id"],
                "content": "hola",
            }
        )
        events = receive_until(ws, "chat.error")
    assert events[-1]["code"] == "provider_unavailable"
    # El mensaje del usuario se conserva para poder reintentar con regenerate.
    items = client.get(
        f"{API}/conversations/{conv['id']}/messages", headers=auth_headers(token)
    ).json()["items"]
    assert [m["role"] for m in items] == ["user"]


def test_ws_logout_blocks_new_turns(client: TestClient, admin_token: str) -> None:
    conv = create_conversation(client, admin_token)
    with client.websocket_connect(WS) as ws:
        ws_auth(ws, admin_token)
        client.post(f"{API}/auth/logout", headers=auth_headers(admin_token))
        ws.send_json(
            {
                "type": "chat.send",
                "request_id": "q",
                "conversation_id": conv["id"],
                "content": "hola",
            }
        )
        assert ws.receive_json()["code"] == "unauthorized"


def test_context_overflow_reported(client: TestClient, admin_token: str) -> None:
    conv = create_conversation(client, admin_token, params={"num_ctx": 512})
    with client.websocket_connect(WS) as ws:
        ws_auth(ws, admin_token)
        ws.send_json(
            {
                "type": "chat.send",
                "request_id": "big",
                "conversation_id": conv["id"],
                "content": "x" * 5000,
            }
        )
        assert receive_until(ws, "chat.error")[-1]["code"] == "context_overflow"


# --------------------------------------------------------------------------- SSE
def parse_sse(body: str) -> list[dict[str, Any]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append(json.loads(lines["data"]))
    return events


def test_sse_completion(client: TestClient, admin_token: str, fake_llm: FakeLLMProvider) -> None:
    conv = create_conversation(client, admin_token)
    response = client.post(
        f"{API}/chat/completions",
        json={"conversation_id": conv["id"], "content": "Hola por SSE"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert events[0]["type"] == "chat.started"
    assert events[-1]["type"] == "chat.done"
    assert "".join(e["text"] for e in events if e["type"] == "chat.delta") == fake_llm.reply


def test_sse_validation(client: TestClient, admin_token: str, user_token: str) -> None:
    conv = create_conversation(client, admin_token)
    headers = auth_headers(admin_token)
    assert (
        client.post(
            f"{API}/chat/completions", json={"conversation_id": conv["id"]}, headers=headers
        ).status_code
        == 422
    )
    foreign = client.post(
        f"{API}/chat/completions",
        json={"conversation_id": conv["id"], "content": "hola"},
        headers=auth_headers(user_token),
    )
    assert foreign.status_code == 404
    assert client.post(f"{API}/chat/nada/cancel", headers=headers).status_code == 404
