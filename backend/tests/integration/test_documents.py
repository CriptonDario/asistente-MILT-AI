"""Documentos: subida, procesamiento en segundo plano, búsqueda, aislamiento y límites."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.llm.base import ModelNotFoundError
from app.llm.fake_provider import FakeLLMProvider
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, API, auth_headers, login, register
from tests.docfactory import make_docx, make_pdf, make_xlsx

TXT = (
    "Manual del proyecto Orion.\n\n"
    "El servidor de producción escucha en el puerto 8443 y usa certificados propios.\n\n"
    "La copia de seguridad se ejecuta cada noche a las 02:00 con restic."
)


def upload(client: TestClient, headers: dict[str, str], name: str, data: bytes) -> Any:
    return client.post(f"{API}/documents", files={"file": (name, data)}, headers=headers)


def wait_ready(client: TestClient, headers: dict[str, str], doc_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        doc: dict[str, Any] = client.get(f"{API}/documents/{doc_id}", headers=headers).json()
        if doc["status"] in ("ready", "failed"):
            return doc
        time.sleep(0.1)
    raise AssertionError("el documento no terminó de procesarse")


def test_upload_process_search_and_delete(client: TestClient, admin_token: str) -> None:
    h = auth_headers(admin_token)
    response = upload(client, h, "orion.txt", TXT.encode())
    assert response.status_code == 201, response.text
    doc = response.json()["document"]
    assert doc["status"] == "pending"
    ready = wait_ready(client, h, doc["id"])
    assert ready["status"] == "ready", ready
    assert ready["chunk_count"] >= 1

    hits = client.post(
        f"{API}/documents/search", json={"query": "¿En qué puerto escucha el servidor?"}, headers=h
    ).json()
    assert hits and "8443" in hits[0]["content"]
    assert hits[0]["filename"] == "orion.txt"
    assert hits[0]["location"].startswith("línea")

    file = client.get(f"{API}/documents/{doc['id']}/file", headers=h)
    assert file.status_code == 200
    assert file.content == TXT.encode()
    assert file.headers["content-disposition"].startswith("attachment")

    assert client.delete(f"{API}/documents/{doc['id']}", headers=h).status_code == 204
    assert (
        client.post(f"{API}/documents/search", json={"query": "puerto servidor"}, headers=h).json()
        == []
    )


def test_all_formats_are_processed(client: TestClient, admin_token: str) -> None:
    h = auth_headers(admin_token)
    files = {
        "informe.pdf": make_pdf(["Ventas del primer trimestre", "Clientes nuevos en Lima"]),
        "acta.docx": make_docx(
            ["Acta de la reunión de seguridad"], [["Tarea", "Dueño"], ["MFA", "Ana"]]
        ),
        "datos.xlsx": make_xlsx({"Inventario": [["Producto", "Stock"], ["Router", 12]]}),
        "clientes.csv": b"nombre,ciudad\nLuz,Quito\nPedro,Cusco\n",
    }
    ids = {
        name: upload(client, h, name, data).json()["document"]["id"] for name, data in files.items()
    }
    for name, doc_id in ids.items():
        doc = wait_ready(client, h, doc_id)
        assert doc["status"] == "ready", (name, doc["error"])

    hit = client.post(
        f"{API}/documents/search",
        json={"query": "stock del router en inventario", "document_ids": [ids["datos.xlsx"]]},
        headers=h,
    ).json()[0]
    assert hit["filename"] == "datos.xlsx"
    assert "Router" in hit["content"]
    assert "hoja Inventario" in hit["location"]


def test_duplicate_upload_is_not_reprocessed(client: TestClient, admin_token: str) -> None:
    h = auth_headers(admin_token)
    first = upload(client, h, "a.txt", TXT.encode()).json()
    second = upload(client, h, "copia.txt", TXT.encode())
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["document"]["id"] == first["document"]["id"]
    assert len(client.get(f"{API}/documents", headers=h).json()) == 1


def test_rejected_uploads(client_factory: Callable[..., TestClient]) -> None:
    client = client_factory(max_upload_bytes=2048)
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    h = auth_headers(login(client, ADMIN_EMAIL, ADMIN_PASSWORD).json()["access_token"])
    assert upload(client, h, "programa.exe", b"MZ\x90").status_code == 415
    assert upload(client, h, "falso.pdf", b"no soy un pdf").status_code == 415
    assert upload(client, h, "vacio.txt", b"").status_code == 422
    too_big = upload(client, h, "grande.txt", b"a" * 5000)
    assert too_big.status_code == 413
    assert client.get(f"{API}/documents", headers=h).json() == []


def test_documents_are_isolated(client: TestClient, admin_token: str, user_token: str) -> None:
    mine = upload(client, auth_headers(admin_token), "orion.txt", TXT.encode()).json()["document"]
    wait_ready(client, auth_headers(admin_token), mine["id"])
    other = auth_headers(user_token)
    assert client.get(f"{API}/documents", headers=other).json() == []
    assert client.get(f"{API}/documents/{mine['id']}", headers=other).status_code == 404
    assert client.get(f"{API}/documents/{mine['id']}/file", headers=other).status_code == 404
    assert client.delete(f"{API}/documents/{mine['id']}", headers=other).status_code == 404
    # Aunque pida explícitamente el documento ajeno, la búsqueda no lo devuelve.
    assert (
        client.post(
            f"{API}/documents/search",
            json={"query": "puerto del servidor", "document_ids": [mine["id"]]},
            headers=other,
        ).json()
        == []
    )


def test_failure_is_reported_and_reindex_recovers(
    client_factory: Callable[..., TestClient],
) -> None:
    llm = FakeLLMProvider()
    client = client_factory(provider=llm)
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    h = auth_headers(login(client, ADMIN_EMAIL, ADMIN_PASSWORD).json()["access_token"])
    llm.embed_fail_with = ModelNotFoundError("model 'nomic-embed-text' not found")
    doc = upload(client, h, "orion.txt", TXT.encode()).json()["document"]
    failed = wait_ready(client, h, doc["id"])
    assert failed["status"] == "failed"
    assert "ollama pull" in failed["error"]

    llm.embed_fail_with = None
    assert client.post(f"{API}/documents/{doc['id']}/reindex", headers=h).status_code == 200
    assert wait_ready(client, h, doc["id"])["status"] == "ready"


def test_scanned_pdf_without_text_fails_clearly(client: TestClient, admin_token: str) -> None:
    h = auth_headers(admin_token)
    doc = upload(client, h, "escaneado.pdf", make_pdf([""])).json()["document"]
    failed = wait_ready(client, h, doc["id"])
    assert failed["status"] == "failed"
    assert "OCR" in failed["error"]
