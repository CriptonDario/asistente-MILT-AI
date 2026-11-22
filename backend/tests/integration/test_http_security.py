"""Controles transversales: autenticación obligatoria, cabeceras, Host, tamaño, errores."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from tests.conftest import API, auth_headers

PUBLIC_ROUTES = {
    ("GET", f"{API}/health"),
    ("GET", f"{API}/system/setup"),
    ("POST", f"{API}/auth/register"),
    ("POST", f"{API}/auth/login"),
    ("POST", f"{API}/auth/refresh"),
    ("POST", f"{API}/auth/local-exchange"),
}


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _concrete_path(path: str) -> str:
    # Sustituye parámetros de ruta por valores sintácticamente válidos.
    return re.sub(r"\{[^}]+\}", "00000000-0000-7000-8000-000000000000", path)


def test_every_non_public_route_requires_auth(client: TestClient) -> None:
    """Recorre el OpenAPI completo: toda ruta no pública debe responder 401 sin token."""
    checked = 0
    paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]
    for path, operations in paths.items():
        if not path.startswith(API):
            continue
        for method in operations:
            if method not in HTTP_METHODS or (method.upper(), path) in PUBLIC_ROUTES:
                continue
            response = client.request(method.upper(), _concrete_path(path), json={})
            assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
            assert response.headers.get("www-authenticate") == "Bearer"
            checked += 1
    assert checked >= 25


def test_invalid_bearer_formats(client: TestClient) -> None:
    for header in ("Basic abc", "Bearer", "Bearer    ", "token"):
        response = client.get(f"{API}/auth/me", headers={"Authorization": header})
        assert response.status_code == 401


def test_security_headers_and_request_id(client: TestClient) -> None:
    response = client.get(f"{API}/health", headers={"X-Request-ID": "abc-123"})
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "abc-123"

    generated = client.get(f"{API}/health", headers={"X-Request-ID": "invalido con espacios"})
    assert re.fullmatch(r"[0-9a-f]{32}", generated.headers["x-request-id"])


def test_untrusted_host_rejected(client: TestClient) -> None:
    response = client.get(f"{API}/health", headers={"Host": "attacker.example"})
    assert response.status_code == 400


def test_cors_only_for_allowed_origins(client: TestClient) -> None:
    allowed = client.options(
        f"{API}/auth/login",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    denied = client.options(
        f"{API}/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in denied.headers


def test_body_too_large(client: TestClient) -> None:
    response = client.post(
        f"{API}/auth/login",
        content=b"x" * 2_000_000,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


def test_problem_details_format(client: TestClient, admin_token: str) -> None:
    response = client.get(f"{API}/no-existe", headers=auth_headers(admin_token))
    assert response.status_code == 404
    body = response.json()
    assert response.headers["content-type"].startswith("application/problem+json")
    assert set(body) >= {"type", "title", "status", "code", "detail", "instance"}

    invalid = client.post(
        f"{API}/auth/login", json={"email": "no-es-correo", "password": "secreto"}
    )
    assert invalid.status_code == 422
    assert "secreto" not in invalid.text, "los valores enviados no se devuelven en el error"


def test_system_info(client: TestClient, admin_token: str) -> None:
    info = client.get(f"{API}/system/info", headers=auth_headers(admin_token)).json()
    assert info["profile"] == "local"
    assert info["llm"]["ok"] is True
    assert info["database"] == {"ok": True, "detail": "sqlite", "version": None, "latency_ms": None}
    caps = client.get(f"{API}/system/capabilities", headers=auth_headers(admin_token)).json()
    assert caps["chat"] is True
    assert caps["tools"] is False
