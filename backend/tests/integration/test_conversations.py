"""Conversaciones: CRUD, paginación, aislamiento entre usuarios, ajustes y modelos."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import API, auth_headers, create_conversation


def test_crud_conversation(client: TestClient, admin_token: str) -> None:
    headers = auth_headers(admin_token)
    conv = create_conversation(
        client,
        admin_token,
        title="  Mi primera  ",
        agent_profile="coder",
        params={"temperature": 0.2},
    )
    assert conv["title"] == "Mi primera"
    assert conv["agent_profile"] == "coder"
    assert conv["params"] == {"temperature": 0.2}

    updated = client.patch(
        f"{API}/conversations/{conv['id']}",
        json={"pinned": True, "title": "Nuevo"},
        headers=headers,
    ).json()
    assert updated["pinned"] is True
    assert updated["title"] == "Nuevo"
    assert updated["updated_at"] >= conv["updated_at"]

    assert client.delete(f"{API}/conversations/{conv['id']}", headers=headers).status_code == 204
    assert client.get(f"{API}/conversations/{conv['id']}", headers=headers).status_code == 404


def test_invalid_input_rejected(client: TestClient, admin_token: str) -> None:
    headers = auth_headers(admin_token)
    bad_params = client.post(
        f"{API}/conversations", json={"params": {"temperature": 9}}, headers=headers
    )
    assert bad_params.status_code == 422
    extra = client.post(f"{API}/conversations", json={"hack": True}, headers=headers)
    assert extra.status_code == 422
    bad_model = client.post(f"{API}/conversations", json={"model": "x; rm -rf /"}, headers=headers)
    assert bad_model.status_code == 422


def test_pagination_and_archive(client: TestClient, admin_token: str) -> None:
    headers = auth_headers(admin_token)
    ids = [create_conversation(client, admin_token, title=f"c{i}")["id"] for i in range(5)]
    client.patch(f"{API}/conversations/{ids[0]}", json={"archived": True}, headers=headers)

    # 4 conversaciones visibles (una archivada) -> dos páginas de 2.
    page1 = client.get(f"{API}/conversations?limit=2", headers=headers).json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]
    page2 = client.get(
        f"{API}/conversations?limit=2&cursor={page1['next_cursor']}", headers=headers
    ).json()
    assert page2["next_cursor"] is None
    seen = [c["id"] for p in (page1, page2) for c in p["items"]]
    assert len(seen) == 4 and len(set(seen)) == 4
    assert ids[0] not in seen
    assert seen == list(reversed(ids[1:])), "orden: más reciente primero"

    archived = client.get(f"{API}/conversations?archived=true", headers=headers).json()
    assert [c["id"] for c in archived["items"]] == [ids[0]]

    filtered = client.get(f"{API}/conversations?q=c3", headers=headers).json()
    assert [c["title"] for c in filtered["items"]] == ["c3"]

    assert client.get(f"{API}/conversations?cursor=basura", headers=headers).status_code == 422


def test_users_cannot_see_each_other(client: TestClient, admin_token: str, user_token: str) -> None:
    conv = create_conversation(client, admin_token, title="privada")
    other = auth_headers(user_token)
    assert client.get(f"{API}/conversations/{conv['id']}", headers=other).status_code == 404
    assert (
        client.patch(
            f"{API}/conversations/{conv['id']}", json={"title": "x"}, headers=other
        ).status_code
        == 404
    )
    assert client.delete(f"{API}/conversations/{conv['id']}", headers=other).status_code == 404
    assert (
        client.get(f"{API}/conversations/{conv['id']}/messages", headers=other).status_code == 404
    )
    assert client.get(f"{API}/conversations", headers=other).json()["items"] == []


def test_settings_defaults_and_update(client: TestClient, admin_token: str) -> None:
    headers = auth_headers(admin_token)
    initial = client.get(f"{API}/settings", headers=headers).json()
    assert initial["theme"] == "system"
    assert initial["effective_default_model"] == "fake-model"

    updated = client.patch(
        f"{API}/settings",
        json={"theme": "dark", "generation_defaults": {"temperature": 0.3}},
        headers=headers,
    ).json()
    assert updated["theme"] == "dark"
    assert updated["generation_defaults"]["temperature"] == 0.3
    assert updated["generation_defaults"]["num_ctx"] == 4096

    assert (
        client.patch(f"{API}/settings", json={"theme": "rosa"}, headers=headers).status_code == 422
    )


def test_models_endpoint(client: TestClient, admin_token: str) -> None:
    headers = auth_headers(admin_token)
    models = client.get(f"{API}/models", headers=headers).json()
    assert models[0]["name"] == "fake-model"
    assert models[0]["is_default"] is True
    assert client.get(f"{API}/models/fake-model", headers=headers).status_code == 200
    missing = client.get(f"{API}/models/no:existe", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "model_not_found"
