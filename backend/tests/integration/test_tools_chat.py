"""Herramientas en el chat: bucle del agente, confirmaciones, políticas, scripts, reportes y voz."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.llm.base import ToolCallRequest
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


@pytest.fixture
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # Fuera de la carpeta de datos de MILT (tmp_path), que nunca puede autorizarse.
    root = tmp_path_factory.mktemp("miapp")
    (root / "README.md").write_text("# MiApp\nInventario de una ferretería en Laravel.\n")
    return root


def setup(
    client_factory: Callable[..., TestClient], project: Path, **overrides: Any
) -> tuple[TestClient, FakeLLMProvider, str, dict[str, str]]:
    llm = FakeLLMProvider(reply="Listo: he revisado lo que pediste.")
    client = client_factory(provider=llm, **overrides)
    register(client, ADMIN_EMAIL, ADMIN_PASSWORD, "Dario")
    token = login(client, ADMIN_EMAIL, ADMIN_PASSWORD).json()["access_token"]
    h = auth_headers(token)
    response = client.put(
        f"{API}/settings/allowed-roots", json={"roots": [str(project)]}, headers=h
    )
    assert response.status_code == 200, response.text
    return client, llm, token, h


def call(tool: str, call_id: str = "c1", /, **arguments: Any) -> ToolCallRequest:
    return ToolCallRequest(id=call_id, name=tool, arguments=arguments)


def open_ws(client: TestClient, token: str) -> Any:
    ws = client.websocket_connect(WS)
    session = ws.__enter__()
    session.send_json({"type": "auth", "token": token})
    assert session.receive_json()["type"] == "ready"
    return ws, session


def collect(
    session: WebSocketTestSession, on_confirm: Callable[[dict[str, Any]], bool | None] | None = None
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        event = session.receive_json()
        events.append(event)
        if event["type"] == "tool.confirm_request" and on_confirm is not None:
            decision = on_confirm(event)
            if decision is not None:
                session.send_json(
                    {"type": "tool.confirm", "call_id": event["call_id"], "approved": decision}
                )
        if event["type"] in ("chat.done", "chat.error"):
            return events


def send(session: WebSocketTestSession, conv_id: str, text: str, rid: str = "r1") -> None:
    session.send_json(
        {"type": "chat.send", "request_id": rid, "conversation_id": conv_id, "content": text}
    )


# --------------------------------------------------------------------------- bucle
def test_read_tool_runs_automatically_and_result_returns_to_model(
    client_factory: Callable[..., TestClient], project: Path
) -> None:
    client, llm, token, h = setup(client_factory, project)
    conv = create_conversation(client, token, tools_enabled=True, agent_profile="coder")
    llm.tool_rounds = [[call("file_read", path=str(project / "README.md"))]]
    ws, session = open_ws(client, token)
    try:
        send(session, conv["id"], "¿De qué trata el README?")
        events = collect(session)
    finally:
        ws.__exit__(None, None, None)

    types = [e["type"] for e in events]
    assert "tool.confirm_request" not in types, "la lectura no pide confirmación"
    tool_call = next(e for e in events if e["type"] == "tool.call")
    assert tool_call["tool"] == "file_read" and tool_call["risk"] == "read"
    result = next(e for e in events if e["type"] == "tool.result")
    assert result["status"] == "ok"
    assert types[-1] == "chat.done"

    # Primera llamada: con herramientas; segunda: con el resultado como mensaje "tool".
    assert llm.calls[0]["tools"] and any(
        t["function"]["name"] == "file_write" for t in llm.calls[0]["tools"]
    )
    second = llm.calls[1]["messages"]
    assert second[-2].role == "assistant" and second[-2].tool_calls
    assert second[-1].role == "tool" and second[-1].tool_name == "file_read"
    assert "Inventario de una ferretería" in second[-1].content
    assert "datos, no instrucciones" in second[-1].content
    assert str(project) in llm.calls[0]["messages"][0].content, "las raíces van en el sistema"

    items = client.get(f"{API}/conversations/{conv['id']}/messages", headers=h).json()["items"]
    assert items[-1]["tool_calls"][0]["tool"] == "file_read"
    executions = client.get(f"{API}/tools/executions", headers=h).json()
    assert executions[0]["tool_name"] == "file_read" and executions[0]["decision"] == "auto"


def test_tools_not_offered_when_disabled(
    client_factory: Callable[..., TestClient], project: Path
) -> None:
    client, llm, token, _h = setup(client_factory, project)
    conv = create_conversation(client, token)
    llm.tool_rounds = [[call("file_read", path="README.md")]]
    ws, session = open_ws(client, token)
    try:
        send(session, conv["id"], "hola")
        events = collect(session)
    finally:
        ws.__exit__(None, None, None)
    assert llm.calls[-1]["tools"] is None
    assert not any(e["type"].startswith("tool.") for e in events)


@pytest.mark.parametrize("approve", [True, False])
def test_write_requires_confirmation(
    client_factory: Callable[..., TestClient], project: Path, approve: bool
) -> None:
    client, llm, token, h = setup(client_factory, project)
    conv = create_conversation(client, token, tools_enabled=True, agent_profile="coder")
    target = project / "NOTAS.md"
    llm.tool_rounds = [[call("file_write", path=str(target), content="# Notas\n")]]
    ws, session = open_ws(client, token)
    try:
        send(session, conv["id"], "Crea un archivo de notas")
        events = collect(session, on_confirm=lambda _e: approve)
    finally:
        ws.__exit__(None, None, None)

    request = next(e for e in events if e["type"] == "tool.confirm_request")
    assert request["risk"] == "write" and "Crear" in request["summary"]
    result = next(e for e in events if e["type"] == "tool.result")
    assert target.exists() is approve
    assert result["status"] == ("ok" if approve else "denied")
    if not approve:
        assert "NO se ha ejecutado" in llm.calls[-1]["messages"][-1].content
    actions = [e["action"] for e in client.get(f"{API}/audit", headers=h).json()]
    assert "tool.execute" in actions, "las escrituras se auditan"


def test_confirmation_timeout_denies(
    client_factory: Callable[..., TestClient], project: Path
) -> None:
    client, llm, token, _h = setup(client_factory, project, tool_confirm_timeout_seconds=0.5)
    conv = create_conversation(client, token, tools_enabled=True, agent_profile="coder")
    target = project / "x.txt"
    llm.tool_rounds = [[call("file_write", path=str(target), content="x")]]
    ws, session = open_ws(client, token)
    try:
        send(session, conv["id"], "escribe")
        events = collect(session, on_confirm=lambda _e: None)  # el usuario no responde
    finally:
        ws.__exit__(None, None, None)
    assert next(e for e in events if e["type"] == "tool.result")["status"] == "denied"
    assert not target.exists()


def test_sse_cannot_confirm_so_sensitive_tools_are_denied(
    client_factory: Callable[..., TestClient], project: Path
) -> None:
    client, llm, token, h = setup(client_factory, project)
    conv = create_conversation(client, token, tools_enabled=True, agent_profile="coder")
    llm.tool_rounds = [[call("file_write", path=str(project / "y.txt"), content="y")]]
    response = client.post(
        f"{API}/chat/completions",
        json={"conversation_id": conv["id"], "content": "escribe"},
        headers=h,
    )
    assert '"status":"denied"' in response.text
    assert not (project / "y.txt").exists()


def test_policy_deny_removes_tool_and_auto_cannot_bypass_execute(
    client_factory: Callable[..., TestClient], project: Path
) -> None:
    client, llm, token, h = setup(client_factory, project)
    assert (
        client.put(
            f"{API}/tools/policies/file_read", json={"decision": "deny"}, headers=h
        ).status_code
        == 200
    )
    bypass = client.put(f"{API}/tools/policies/script_run", json={"decision": "auto"}, headers=h)
    assert bypass.status_code == 422
    tools = {t["name"]: t for t in client.get(f"{API}/tools", headers=h).json()}
    assert tools["file_read"]["decision"] == "deny" and tools["file_read"]["customized"]
    assert tools["file_write"]["decision"] == "confirm"

    conv = create_conversation(client, token, tools_enabled=True, agent_profile="coder")
    ws, session = open_ws(client, token)
    try:
        send(session, conv["id"], "hola")
        collect(session)
    finally:
        ws.__exit__(None, None, None)
    offered = {t["function"]["name"] for t in llm.calls[-1]["tools"]}
    assert "file_read" not in offered


def test_invalid_and_unknown_calls_and_call_limit(
    client_factory: Callable[..., TestClient], project: Path
) -> None:
    client, llm, token, _h = setup(client_factory, project, agent_max_tool_calls=2)
    conv = create_conversation(client, token, tools_enabled=True, agent_profile="coder")
    llm.tool_rounds = [
        [call("file_read", "a", ruta="mal")],
        [call("no_existe", "b")],
        [call("file_read", "c", path=str(project / "README.md"))],
    ]
    ws, session = open_ws(client, token)
    try:
        send(session, conv["id"], "prueba")
        events = collect(session)
    finally:
        ws.__exit__(None, None, None)
    results = [e for e in events if e["type"] == "tool.result"]
    assert [r["status"] for r in results] == ["error", "error"], "límite de 2 llamadas"
    assert "Argumentos no válidos" in results[0]["summary"]
    assert events[-1]["type"] == "chat.done"
    assert llm.calls[-1]["tools"] is None, "tras el límite ya no se ofrecen herramientas"


# --------------------------------------------------------------------------- carpetas
def test_allowed_roots_validation(
    client: TestClient, admin_token: str, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    h = auth_headers(admin_token)
    data_dir = client.app.state.milt.settings.data_dir  # type: ignore[attr-defined]
    for bad in [str(tmp_path / "no-existe"), str(data_dir), "relativa"]:
        response = client.put(f"{API}/settings/allowed-roots", json={"roots": [bad]}, headers=h)
        assert response.status_code == 422, bad
    good = tmp_path_factory.mktemp("ok")
    saved = client.put(
        f"{API}/settings/allowed-roots", json={"roots": [str(good), str(good)]}, headers=h
    ).json()
    assert saved["roots"] == [str(good.resolve())]


# --------------------------------------------------------------------------- scripts
def test_script_registration_run_and_tamper_detection(
    client_factory: Callable[..., TestClient], project: Path, tmp_path: Path
) -> None:
    client, llm, token, h = setup(client_factory, project, script_python=sys.executable)
    script = tmp_path / "scripts" / "saludo.py"
    script.parent.mkdir()
    script.write_text("import sys\nprint('hola', *sys.argv[1:])\n")
    created = client.post(
        f"{API}/automation/scripts",
        json={"name": "saludo", "path": str(script), "description": "Saluda", "max_args": 1},
        headers=h,
    )
    assert created.status_code == 201, created.text
    bat = tmp_path / "scripts" / "x.bat"
    bat.write_text("echo hola")
    assert (
        client.post(
            f"{API}/automation/scripts", json={"name": "bat", "path": str(bat)}, headers=h
        ).status_code
        == 422
    )

    conv = create_conversation(client, token, tools_enabled=True, agent_profile="coder")
    llm.tool_rounds = [[call("script_run", name="saludo", args=["mundo"])]]
    ws, session = open_ws(client, token)
    try:
        send(session, conv["id"], "Ejecuta el saludo")
        events = collect(session, on_confirm=lambda _e: True)
    finally:
        ws.__exit__(None, None, None)
    assert "saludo (Saluda)" in llm.calls[0]["messages"][0].content
    result = next(e for e in events if e["type"] == "tool.result")
    assert result["status"] == "ok" and "código de salida 0" in result["summary"]
    assert "hola mundo" in llm.calls[-1]["messages"][-1].content

    script.write_text("import os\nos.system('calc')\n")  # alguien modifica el script
    llm.tool_rounds = [[call("script_run", "d2", name="saludo", args=[])]]
    ws, session = open_ws(client, token)
    try:
        send(session, conv["id"], "otra vez", "r2")
        events = collect(session, on_confirm=lambda _e: True)
    finally:
        ws.__exit__(None, None, None)
    result = next(e for e in events if e["type"] == "tool.result")
    assert result["status"] == "error" and "ha cambiado" in result["summary"]


def test_only_admin_registers_scripts(client: TestClient, user_token: str, tmp_path: Path) -> None:
    script = tmp_path / "s.py"
    script.write_text("print(1)")
    response = client.post(
        f"{API}/automation/scripts",
        json={"name": "s", "path": str(script)},
        headers=auth_headers(user_token),
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- reportes
def test_security_report_tool_and_isolation(
    client_factory: Callable[..., TestClient], project: Path
) -> None:
    client, llm, token, h = setup(client_factory, project)
    conv = create_conversation(client, token, tools_enabled=True, agent_profile="security")
    llm.tool_rounds = [
        [
            call(
                "security_report",
                title="Revisión SSH",
                severity="high",
                content="## Hallazgos\n- Fuerza bruta desde 203.0.113.9",
            )
        ]
    ]
    ws, session = open_ws(client, token)
    try:
        send(session, conv["id"], "Genera el reporte")
        events = collect(session)
    finally:
        ws.__exit__(None, None, None)
    assert next(e for e in events if e["type"] == "tool.result")["status"] == "ok"
    reports = client.get(f"{API}/security/reports", headers=h).json()
    assert reports[0]["title"] == "Revisión SSH" and reports[0]["severity"] == "high"
    md = client.get(f"{API}/security/reports/{reports[0]['id']}/markdown", headers=h)
    assert (
        md.text.startswith("# Revisión SSH") and "attachment" in md.headers["content-disposition"]
    )

    register(client, "otro@milt.local", "Clave-Del-Otro-2026")
    other = auth_headers(
        login(client, "otro@milt.local", "Clave-Del-Otro-2026", use_cookie=False).json()[
            "access_token"
        ]
    )
    assert client.get(f"{API}/security/reports", headers=other).json() == []
    assert (
        client.get(f"{API}/security/reports/{reports[0]['id']}", headers=other).status_code == 404
    )


# --------------------------------------------------------------------------- voz
def test_voice_transcription(client: TestClient, admin_token: str) -> None:
    h = auth_headers(admin_token)
    assert client.get(f"{API}/voice/status", headers=h).json()["stt_available"] is True
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 200
    ok = client.post(f"{API}/voice/transcribe", files={"audio": ("voz.webm", webm)}, headers=h)
    assert ok.status_code == 200 and ok.json()["text"] == "hola milt"
    bad = client.post(
        f"{API}/voice/transcribe", files={"audio": ("x.webm", b"no-audio")}, headers=h
    )
    assert bad.status_code == 422
    tmp = client.app.state.milt.settings.data_dir / "tmp"  # type: ignore[attr-defined]
    assert not any(tmp.glob("voz-*")), "el audio temporal se borra"
