"""Fixtures comunes: app de prueba con BD temporal (migrada) y proveedor de IA simulado."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.llm.fake_provider import DEFAULT_FAKE_MODEL, FakeLLMProvider
from app.main import create_app

API = "/api/v1"
ADMIN_EMAIL = "admin@milt.local"
ADMIN_PASSWORD = "Clave-Segura-Admin-2026"
USER_EMAIL = "usuario@milt.local"
USER_PASSWORD = "Clave-Segura-Usuario-2026"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "profile": "local",
        "env": "test",
        "data_dir": tmp_path,
        "allowed_hosts": ["testserver", "127.0.0.1", "localhost"],
        "cookie_secure": False,
        "jwt_secret": SecretStr("s" * 48),
        "argon2_time_cost": 1,
        "argon2_memory_cost_kib": 1024,
        "argon2_parallelism": 1,
        # Las embeddings simuladas (bolsa de palabras) puntúan más bajo que las reales.
        "rag_min_score": 0.2,
        # Un subproceso por documento es lento en equipos con poca RAM; se prueba aparte.
        "parse_isolated": False,
        "log_json": False,
        "log_level": "WARNING",
        "llm_provider": "fake",
        "default_model": DEFAULT_FAKE_MODEL,
        "allow_registration": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider(reply="Hola, soy MILT. ¿En qué puedo ayudarte?")


@pytest.fixture
def app(settings: Settings, fake_llm: FakeLLMProvider) -> FastAPI:
    return create_app(settings, provider_factory=lambda _s: fake_llm)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_factory(tmp_path: Path) -> Iterator[Callable[..., TestClient]]:
    """Crea clientes con configuración o proveedor personalizados."""
    opened: list[TestClient] = []

    def factory(provider: Any = None, **overrides: Any) -> TestClient:
        settings = make_settings(tmp_path, **overrides)
        llm = provider or FakeLLMProvider()
        test_client = TestClient(create_app(settings, provider_factory=lambda _s: llm))
        test_client.__enter__()
        opened.append(test_client)
        return test_client

    yield factory
    for test_client in opened:
        test_client.__exit__(None, None, None)


# --------------------------------------------------------------------------- helpers
def register(client: TestClient, email: str, password: str, name: str = "Tester") -> Any:
    return client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )


def login(client: TestClient, email: str, password: str, **extra: Any) -> Any:
    return client.post(f"{API}/auth/login", json={"email": email, "password": password, **extra})


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token(client: TestClient) -> str:
    assert register(client, ADMIN_EMAIL, ADMIN_PASSWORD, "Admin").status_code == 201
    response = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


@pytest.fixture
def user_token(client: TestClient, admin_token: str) -> str:
    assert register(client, USER_EMAIL, USER_PASSWORD, "Usuario").status_code == 201
    # Se usa un cliente "nativo" para no mezclar la cookie con la del admin.
    response = login(client, USER_EMAIL, USER_PASSWORD, use_cookie=False)
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def create_conversation(client: TestClient, token: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"{API}/conversations", json=body, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data
