"""Registro, login, bloqueo, rotación de refresh tokens, sesiones y cambio de contraseña."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    API,
    USER_EMAIL,
    USER_PASSWORD,
    auth_headers,
    login,
    register,
)


def test_first_user_is_admin_and_next_is_user(client: TestClient) -> None:
    first = register(client, ADMIN_EMAIL, ADMIN_PASSWORD, "Admin")
    assert first.status_code == 201, first.text
    assert first.json()["role"] == "admin"
    assert "password_hash" not in first.json()

    second = register(client, USER_EMAIL, USER_PASSWORD)
    assert second.status_code == 201
    assert second.json()["role"] == "user"

    duplicate = register(client, USER_EMAIL.upper(), USER_PASSWORD)
    assert duplicate.status_code == 409, "el correo se normaliza a minúsculas"


def test_registration_closed_after_first_user(client_factory: Callable[..., TestClient]) -> None:
    client = client_factory(allow_registration=False)
    assert register(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 201
    response = register(client, USER_EMAIL, USER_PASSWORD)
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_weak_password_rejected(client: TestClient) -> None:
    response = register(client, ADMIN_EMAIL, "password1234")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_login_success_sets_httponly_cookie(client: TestClient) -> None:
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    response = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert data["refresh_token"] is None, "con cookie, el refresh no viaja en el cuerpo"
    assert 0 < data["expires_in"] <= 900
    cookie = response.headers["set-cookie"]
    assert "milt_refresh=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie or "samesite=strict" in cookie.lower()
    assert "Path=/api/v1/auth" in cookie

    me = client.get(f"{API}/auth/me", headers=auth_headers(data["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN_EMAIL


def test_login_wrong_password_is_generic(client: TestClient) -> None:
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wrong = login(client, ADMIN_EMAIL, "contraseña-incorrecta-123")
    unknown = login(client, "nadie@milt.local", "contraseña-incorrecta-123")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"], "no se revela si la cuenta existe"


def test_lockout_after_repeated_failures(client_factory: Callable[..., TestClient]) -> None:
    client = client_factory(lockout_threshold=3, login_attempts_per_minute=50)
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    for _ in range(3):
        assert login(client, ADMIN_EMAIL, "contraseña-incorrecta-123").status_code == 401
    # Bloqueada: ni siquiera la contraseña correcta funciona.
    assert login(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 401


def test_login_rate_limited(client_factory: Callable[..., TestClient]) -> None:
    client = client_factory(login_attempts_per_minute=2, lockout_threshold=100)
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    login(client, ADMIN_EMAIL, "contraseña-incorrecta-1")
    login(client, ADMIN_EMAIL, "contraseña-incorrecta-2")
    response = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1


def test_refresh_rotation_with_cookie(client: TestClient) -> None:
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    first_cookie = client.cookies.get("milt_refresh")
    assert first_cookie

    refreshed = client.post(f"{API}/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    second_cookie = client.cookies.get("milt_refresh")
    assert second_cookie and second_cookie != first_cookie
    assert (
        client.get(
            f"{API}/auth/me", headers=auth_headers(refreshed.json()["access_token"])
        ).status_code
        == 200
    )


def test_refresh_reuse_revokes_whole_session(client: TestClient) -> None:
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    data = login(client, ADMIN_EMAIL, ADMIN_PASSWORD, use_cookie=False).json()
    old_refresh = data["refresh_token"]
    assert old_refresh

    rotated = client.post(f"{API}/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200
    new_access = rotated.json()["access_token"]
    new_refresh = rotated.json()["refresh_token"]

    # Un atacante reutiliza el refresh antiguo: se revoca toda la familia.
    reuse = client.post(f"{API}/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401
    assert (
        client.post(f"{API}/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401
    )
    assert client.get(f"{API}/auth/me", headers=auth_headers(new_access)).status_code == 401


def test_refresh_without_token(client: TestClient) -> None:
    assert client.post(f"{API}/auth/refresh").status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": "x" * 30}).status_code == 401


def test_logout_invalidates_access_token(client: TestClient, admin_token: str) -> None:
    headers = auth_headers(admin_token)
    assert client.post(f"{API}/auth/logout", headers=headers).status_code == 204
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 401
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_sessions_list_and_revoke(client: TestClient, admin_token: str) -> None:
    other = login(
        client,
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
        use_cookie=False,
        device_name="Móvil",
        platform="android",
    ).json()
    sessions = client.get(f"{API}/sessions", headers=auth_headers(admin_token)).json()
    assert len(sessions) == 2
    assert sum(1 for s in sessions if s["current"]) == 1
    mobile = next(s for s in sessions if s["device_name"] == "Móvil")

    revoke = client.delete(f"{API}/sessions/{mobile['id']}", headers=auth_headers(admin_token))
    assert revoke.status_code == 204
    assert (
        client.get(f"{API}/auth/me", headers=auth_headers(other["access_token"])).status_code == 401
    )
    assert client.get(f"{API}/auth/me", headers=auth_headers(admin_token)).status_code == 200


def test_cannot_revoke_foreign_session(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    admin_sessions = client.get(f"{API}/sessions", headers=auth_headers(admin_token)).json()
    response = client.delete(
        f"{API}/sessions/{admin_sessions[0]['id']}", headers=auth_headers(user_token)
    )
    assert response.status_code == 404


def test_change_password_revokes_other_sessions(client: TestClient, admin_token: str) -> None:
    other = login(client, ADMIN_EMAIL, ADMIN_PASSWORD, use_cookie=False).json()
    headers = auth_headers(admin_token)

    bad = client.patch(
        f"{API}/auth/me/password",
        json={"current_password": "incorrecta-123456", "new_password": "Nueva-Clave-Segura-99"},
        headers=headers,
    )
    assert bad.status_code == 401

    ok = client.patch(
        f"{API}/auth/me/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "Nueva-Clave-Segura-99"},
        headers=headers,
    )
    assert ok.status_code == 204
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 200
    assert (
        client.get(f"{API}/auth/me", headers=auth_headers(other["access_token"])).status_code == 401
    )
    assert login(client, ADMIN_EMAIL, "Nueva-Clave-Segura-99").status_code == 200


def test_local_exchange(client_factory: Callable[..., TestClient]) -> None:
    from pydantic import SecretStr

    bootstrap = "t" * 40
    client = client_factory(local_bootstrap_token=SecretStr(bootstrap))
    assert client.post(f"{API}/auth/local-exchange", json={"token": bootstrap}).status_code == 409

    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert client.post(f"{API}/auth/local-exchange", json={"token": "x" * 40}).status_code == 401
    response = client.post(f"{API}/auth/local-exchange", json={"token": bootstrap})
    assert response.status_code == 200
    assert response.json()["user"]["email"] == ADMIN_EMAIL
    assert response.json()["refresh_token"]


def test_local_exchange_disabled_without_token(client: TestClient) -> None:
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    response = client.post(f"{API}/auth/local-exchange", json={"token": "x" * 40})
    assert response.status_code == 401


def test_deactivated_user_loses_access(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    me = client.get(f"{API}/auth/me", headers=auth_headers(user_token)).json()
    response = client.patch(
        f"{API}/users/{me['id']}", json={"is_active": False}, headers=auth_headers(admin_token)
    )
    assert response.status_code == 200
    assert client.get(f"{API}/auth/me", headers=auth_headers(user_token)).status_code == 401
