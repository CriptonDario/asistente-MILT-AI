"""Administración de usuarios y auditoría."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import API, auth_headers, login


def test_non_admin_cannot_manage_users(client: TestClient, user_token: str) -> None:
    assert client.get(f"{API}/users", headers=auth_headers(user_token)).status_code == 403


def test_admin_crud_users(client: TestClient, admin_token: str) -> None:
    headers = auth_headers(admin_token)
    created = client.post(
        f"{API}/users",
        json={
            "email": "nuevo@milt.local",
            "display_name": "Nuevo",
            "password": "Clave-Del-Nuevo-2026",
            "role": "user",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    assert len(client.get(f"{API}/users", headers=headers).json()) == 2

    updated = client.patch(
        f"{API}/users/{user_id}", json={"display_name": "Renombrado"}, headers=headers
    )
    assert updated.json()["display_name"] == "Renombrado"

    assert client.delete(f"{API}/users/{user_id}", headers=headers).status_code == 204
    assert client.patch(f"{API}/users/{user_id}", json={}, headers=headers).status_code == 404


def test_last_admin_is_protected(client: TestClient, admin_token: str) -> None:
    headers = auth_headers(admin_token)
    me = client.get(f"{API}/auth/me", headers=headers).json()
    demote = client.patch(f"{API}/users/{me['id']}", json={"role": "user"}, headers=headers)
    assert demote.status_code == 422
    assert client.delete(f"{API}/users/{me['id']}", headers=headers).status_code == 422


def test_audit_trail_and_chain(client: TestClient, admin_token: str, user_token: str) -> None:
    login(client, "usuario@milt.local", "contraseña-mala-123")  # fallo auditado

    admin_view = client.get(f"{API}/audit", headers=auth_headers(admin_token)).json()
    actions = {e["action"] for e in admin_view}
    assert {"auth.register", "auth.login"} <= actions
    assert any(e["outcome"] == "failure" for e in admin_view)
    for entry in admin_view:
        assert "contraseña-mala" not in str(entry["details"] or {})

    user_view = client.get(f"{API}/audit", headers=auth_headers(user_token)).json()
    me = client.get(f"{API}/auth/me", headers=auth_headers(user_token)).json()
    assert user_view and all(e["user_id"] == me["id"] for e in user_view)

    verify = client.get(f"{API}/audit/verify", headers=auth_headers(admin_token))
    assert verify.status_code == 200
    assert verify.json()["valid"] is True
    assert verify.json()["checked"] == len(admin_view)
    assert client.get(f"{API}/audit/verify", headers=auth_headers(user_token)).status_code == 403


def test_audit_detects_tampering(client: TestClient, admin_token: str) -> None:
    import sqlite3

    state = client.app.state.milt  # type: ignore[attr-defined]
    db_path = state.settings.data_dir / "milt.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE audit_log SET outcome = 'success' WHERE id = 1")
        conn.execute("UPDATE audit_log SET ip = '6.6.6.6' WHERE id = 1")
    verify = client.get(f"{API}/audit/verify", headers=auth_headers(admin_token)).json()
    assert verify["valid"] is False
    assert verify["broken_at_id"] == 1
