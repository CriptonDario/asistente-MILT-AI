"""Memoria persistente: CRUD, búsqueda semántica, sugerencias, aislamiento y fallos del motor."""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi.testclient import TestClient

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


def _admin(client: TestClient) -> dict[str, str]:
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    return auth_headers(login(client, ADMIN_EMAIL, ADMIN_PASSWORD).json()["access_token"])


def _create(client: TestClient, headers: dict[str, str], content: str, **extra: object) -> dict:
    response = client.post(f"{API}/memories", json={"content": content, **extra}, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_crud_and_semantic_search(client: TestClient, admin_token: str) -> None:
    h = auth_headers(admin_token)
    laravel = _create(client, h, "El usuario programa con Laravel y PHP", kind="project")
    _create(client, h, "Prefiere respuestas breves y directas", kind="preference")
    assert laravel["indexed"] is True and laravel["status"] == "active"

    hits = client.post(
        f"{API}/memories/search", json={"query": "proyecto con Laravel"}, headers=h
    ).json()
    assert hits[0]["memory"]["id"] == laravel["id"]
    assert hits[0]["score"] > hits[-1]["score"]

    updated = client.patch(
        f"{API}/memories/{laravel['id']}",
        json={"content": "El usuario programa con Kotlin"},
        headers=h,
    ).json()
    assert updated["content"] == "El usuario programa con Kotlin"
    hits = client.post(f"{API}/memories/search", json={"query": "Kotlin"}, headers=h).json()
    assert hits[0]["memory"]["id"] == laravel["id"], "el vector se actualiza al editar"

    assert (
        client.get(f"{API}/memories?kind=preference", headers=h).json()[0]["kind"] == "preference"
    )
    assert client.delete(f"{API}/memories/{laravel['id']}", headers=h).status_code == 204
    hits = client.post(f"{API}/memories/search", json={"query": "Kotlin"}, headers=h).json()
    assert all(hit["memory"]["id"] != laravel["id"] for hit in hits)


def test_memories_are_isolated(client: TestClient, admin_token: str, user_token: str) -> None:
    mine = _create(client, auth_headers(admin_token), "Dato privado del administrador")
    other = auth_headers(user_token)
    assert client.get(f"{API}/memories", headers=other).json() == []
    assert (
        client.post(
            f"{API}/memories/search", json={"query": "Dato privado administrador"}, headers=other
        ).json()
        == []
    )
    assert (
        client.patch(
            f"{API}/memories/{mine['id']}", json={"content": "hackeado"}, headers=other
        ).status_code
        == 404
    )
    assert client.delete(f"{API}/memories/{mine['id']}", headers=other).status_code == 404


def test_extract_suggestions_accept_reject_and_dedupe(
    client_factory: Callable[..., TestClient],
) -> None:
    llm = FakeLLMProvider(reply="Me llamo Dario y trabajo en un proyecto con Laravel.")
    client = client_factory(provider=llm)
    h = _admin(client)
    conv = create_conversation(client, h["Authorization"].split()[1])
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "auth", "token": h["Authorization"].split()[1]})
        ws.receive_json()
        ws.send_json(
            {
                "type": "chat.send",
                "request_id": "x",
                "conversation_id": conv["id"],
                "content": "Me llamo Dario y trabajo con Laravel",
            }
        )
        while ws.receive_json()["type"] != "chat.done":
            pass

    llm.reply = json.dumps(
        [
            {"content": "El usuario se llama Dario", "kind": "fact"},
            {"content": "El usuario trabaja con Laravel", "kind": "project"},
        ]
    )
    result = client.post(
        f"{API}/memories/extract", json={"conversation_id": conv["id"]}, headers=h
    ).json()
    assert [m["status"] for m in result["created"]] == ["suggested", "suggested"]
    assert all(m["indexed"] is False for m in result["created"]), "las sugerencias no se indexan"

    suggestions = client.get(f"{API}/memories/suggestions", headers=h).json()
    assert len(suggestions) == 2
    assert client.get(f"{API}/memories", headers=h).json() == [], "aún no están activas"

    accepted = client.post(
        f"{API}/memories/suggestions/{suggestions[0]['id']}/accept", headers=h
    ).json()
    assert accepted["status"] == "active" and accepted["indexed"] is True
    assert (
        client.post(
            f"{API}/memories/suggestions/{suggestions[1]['id']}/reject", headers=h
        ).status_code
        == 204
    )
    assert client.get(f"{API}/memories/stats", headers=h).json() == {
        "active": 1,
        "suggested": 0,
        "unindexed": 0,
    }

    again = client.post(
        f"{API}/memories/extract", json={"conversation_id": conv["id"]}, headers=h
    ).json()
    assert again["skipped_duplicates"] == 1


def test_memory_saved_even_if_embeddings_fail(client_factory: Callable[..., TestClient]) -> None:
    llm = FakeLLMProvider()
    client = client_factory(provider=llm)
    h = _admin(client)
    llm.embed_fail_with = ProviderUnavailableError("apagado")
    created = _create(client, h, "Recuerdo creado con Ollama apagado")
    assert created["indexed"] is False
    assert client.get(f"{API}/memories/stats", headers=h).json()["unindexed"] == 1

    llm.embed_fail_with = None
    stats = client.post(f"{API}/memories/reindex", headers=h).json()
    assert stats["unindexed"] == 0


def test_delete_all_requires_confirmation(client: TestClient, admin_token: str) -> None:
    h = auth_headers(admin_token)
    _create(client, h, "Uno")
    _create(client, h, "Dos")
    assert client.request("DELETE", f"{API}/memories", json={}, headers=h).status_code == 422
    assert (
        client.request(
            "DELETE", f"{API}/memories", json={"confirm": "DELETE"}, headers=h
        ).status_code
        == 204
    )
    assert client.get(f"{API}/memories", headers=h).json() == []
    actions = {e["action"] for e in client.get(f"{API}/audit", headers=h).json()}
    assert "memory.delete_all" in actions
