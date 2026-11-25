"""Regresiones de la revisión de la Fase 5: cada prueba reproduce un hallazgo corregido."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import struct
import sys
import threading
import time
import uuid
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.errors import ValidationAppError
from app.llm.base import ChatMessage, ToolCallRequest
from app.llm.tokens import estimate_message_tokens
from app.modules.automation.models import AutomationScript
from app.modules.automation.scripts import DEFAULT_ARG_PATTERN, locked_verified, validate_args
from app.modules.chat.service import _compact_tool_results, _history_tool_calls
from app.tools.base import ToolContext, ToolError
from app.tools.builtin.automation import ScriptRunArgs, ScriptRunTool
from app.tools.builtin.files import (
    CodeSearchArgs,
    CodeSearchTool,
    FileWriteArgs,
    FileWriteTool,
    ProjectTreeArgs,
    ProjectTreeTool,
    TreeWalker,
)
from app.tools.builtin.security import _is_own_network, analyze_log_text, tail_lines
from app.tools.executor import stored_arguments
from app.tools.fs_guard import FsGuard
from app.tools.sandbox import run_sandboxed


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proyecto"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("def hola():\n    return 'MILT'\n", encoding="utf-8")
    return root


def ctx_for(root: Path, data_dir: Path, *, role: str = "admin", profile: str = "local") -> Any:
    state: Any = SimpleNamespace(settings=SimpleNamespace(data_dir=data_dir, profile=profile))
    return ToolContext(
        state=state,
        user_id=uuid.uuid4(),
        user_role=role,
        conversation_id=None,
        allowed_roots=[root],
    )


# ----------------------------------------------------------------- 1. ReDoS en code_search
def test_catastrophic_regex_does_not_freeze_the_event_loop(project: Path, tmp_path: Path) -> None:
    (project / "app" / "datos.txt").write_text(("a" * 40 + "b\n") * 50)
    args = CodeSearchArgs(query="(a|aa)+$", path=str(project), regex=True)

    async def scenario() -> tuple[Any, int, float]:
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        task = asyncio.create_task(ticker())
        started = time.perf_counter()
        result = await CodeSearchTool().run(args, ctx_for(project, tmp_path / "data"))
        elapsed = time.perf_counter() - started
        task.cancel()
        return result, ticks, elapsed

    result, ticks, elapsed = asyncio.run(scenario())
    assert "demasiado costosa" in result.content
    assert elapsed < 10, "se corta por tiempo en vez de colgarse"
    assert ticks >= 3, "el bucle de eventos siguió atendiendo mientras se buscaba"


def test_code_search_invalid_regex_is_a_tool_error(project: Path, tmp_path: Path) -> None:
    args = CodeSearchArgs(query="(sin cerrar", path=str(project), regex=True)
    with pytest.raises(ToolError, match="no válida"):
        asyncio.run(CodeSearchTool().run(args, ctx_for(project, tmp_path / "data")))


# ----------------------------------------------------------------- 4. junctions
@pytest.mark.skipif(sys.platform != "win32", reason="junctions de NTFS")
def test_walkers_do_not_follow_junctions(project: Path, tmp_path: Path) -> None:
    import _winapi

    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "secreto.py").write_text("CLAVE_FUERA = 1\n")
    _winapi.CreateJunction(str(outside), str(project / "enlace"))
    assert (project / "enlace" / "secreto.py").exists(), "la junction funciona"

    names = [name for _cur, _dirs, files in TreeWalker(project) for name in files]
    assert "secreto.py" not in names
    ctx = ctx_for(project, tmp_path / "data")
    tree = asyncio.run(ProjectTreeTool().run(ProjectTreeArgs(path=str(project)), ctx))
    assert "secreto.py" not in tree.content and "enlace" not in tree.content
    search = asyncio.run(
        CodeSearchTool().run(CodeSearchArgs(query="CLAVE_FUERA", path=str(project)), ctx)
    )
    assert "Sin coincidencias" in search.content


def test_tree_walker_stops_at_entry_cap(project: Path) -> None:
    for i in range(30):
        (project / f"f{i}.txt").write_text("x")
    walker = TreeWalker(project, max_entries=10)
    list(walker)
    assert walker.truncated


# ----------------------------------------------------------------- 6. nombres de Windows
@pytest.mark.parametrize(
    "name",
    [".env.", ".env ", "id_rsa.", "notas.txt ", "NUL.txt", "con", "COM1.log", "lpt9"],
)
def test_write_rejects_names_windows_would_rewrite(
    project: Path, tmp_path: Path, name: str
) -> None:
    args = FileWriteArgs(path=f"app/{name}", content="x")
    with pytest.raises(ToolError):
        asyncio.run(FileWriteTool().run(args, ctx_for(project, tmp_path / "data")))
    assert not (project / "app" / ".env").exists()


@pytest.mark.parametrize("path", [".git/config", ".git/hooks/pre-commit", "a.txt.milt.bak"])
def test_write_rejects_repo_internals_and_backups(project: Path, tmp_path: Path, path: str) -> None:
    (project / ".git" / "hooks").mkdir(parents=True)
    args = FileWriteArgs(path=path, content="x")
    with pytest.raises(ToolError, match="denegado"):
        asyncio.run(FileWriteTool().run(args, ctx_for(project, tmp_path / "data")))


def test_write_leaves_no_temp_files_and_keeps_backup(project: Path, tmp_path: Path) -> None:
    target = project / "app" / "main.py"
    ctx = ctx_for(project, tmp_path / "data")
    args = FileWriteArgs(path="app/main.py", content="nuevo\r\n", overwrite=True)
    asyncio.run(FileWriteTool().run(args, ctx))
    asyncio.run(FileWriteTool().run(args, ctx))  # segunda vez: la copia ya existe
    assert target.read_bytes() == b"nuevo\r\n"
    assert (project / "app" / "main.py.milt.bak").read_bytes() == b"nuevo\r\n"
    assert not list((project / "app").glob("*.milt.tmp"))


def test_reading_still_allows_normal_names(project: Path, tmp_path: Path) -> None:
    guard = FsGuard([project], data_dir=tmp_path / "data")
    (project / "app" / "console.py").write_text("x")
    (project / "app" / "auxiliar.py").write_text("x")
    assert guard.resolve("app/console.py").name == "console.py"
    assert guard.resolve("app/auxiliar.py").name == "auxiliar.py"


# ----------------------------------------------------------------- 2/3. logs
def test_privilege_pattern_is_not_quadratic() -> None:
    line = "user added to " + "grupo " * 20_000
    started = time.perf_counter()
    analyze_log_text([line[:2000]] * 200)
    assert time.perf_counter() - started < 2


def test_tail_lines_bounded_memory(tmp_path: Path) -> None:
    log = tmp_path / "acceso.log"
    with log.open("wb") as fh:
        fh.write(b"X" * 100_000 + b"\n")  # línea gigante: se recorta
        for i in range(5000):
            fh.write(f"linea {i} Failed password from 10.0.0.{i % 250}\n".encode())
    lines = tail_lines(log, max_lines=100)
    assert len(lines) == 100
    assert lines[-1].startswith("linea 4999")
    small = tail_lines(log, max_lines=10_000, max_bytes=50_000)
    assert all(len(line) <= 2000 for line in small)
    assert not small[0].startswith("X"), "se empieza en una línea completa"


def test_tail_lines_rejects_binary(tmp_path: Path) -> None:
    log = tmp_path / "eventos.evtx"
    log.write_bytes(b"ElfFile\x00\x00\x00" * 100)
    with pytest.raises(ToolError, match="binario"):
        tail_lines(log, max_lines=100)


# ----------------------------------------------------------------- 12. red local
@pytest.mark.parametrize(
    ("address", "own"),
    [
        ("192.168.1.10", True),
        ("10.1.2.3", True),
        ("172.20.0.5", True),
        ("127.0.0.1", True),
        ("::1", True),
        ("fe80::1%12", True),
        ("fd00::5", True),
        ("::ffff:192.168.1.4", True),
        ("0.0.0.0", False),  # noqa: S104 - es un dato de prueba
        ("::", False),
        ("8.8.8.8", False),
        ("100.64.0.1", False),
        ("192.0.2.1", False),
        ("2002:c0a8:0101::1", False),
        ("64:ff9b::808:808", False),
        ("::ffff:8.8.8.8", False),
        ("224.0.0.1", False),
        ("no-es-ip", False),
    ],
)
def test_own_network_ranges(address: str, own: bool) -> None:
    assert _is_own_network(address) is own


# ----------------------------------------------------------------- 5/8. sandbox
def test_sandbox_cancel_kills_process_quickly(tmp_path: Path) -> None:
    script = tmp_path / "lento.py"
    script.write_text("import time\ntime.sleep(60)\n")
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    started = time.perf_counter()
    result = run_sandboxed([sys.executable, str(script)], cwd=tmp_path, timeout=60, cancel=cancel)
    assert result.cancelled and not result.timed_out
    assert result.exit_code is None
    assert time.perf_counter() - started < 10


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects de Windows")
def test_sandbox_child_processes_die_with_the_job(tmp_path: Path) -> None:
    # El proceso arranca suspendido y se asigna al Job antes de ejecutar nada: un hijo
    # lanzado de inmediato también queda dentro y muere al terminar el padre.
    marker = tmp_path / "hijo-vivo.txt"
    child = tmp_path / "hijo.py"
    child.write_text(
        f"import time, pathlib\ntime.sleep(2)\npathlib.Path(r'{marker}').write_text('sigo vivo')\n"
    )
    parent = tmp_path / "padre.py"
    parent.write_text(
        f"import subprocess, sys\nsubprocess.Popen([sys.executable, r'{child}'])\nprint('ok')\n"
    )
    result = run_sandboxed([sys.executable, str(parent)], cwd=tmp_path, timeout=20)
    assert result.exit_code == 0
    time.sleep(3)
    assert not marker.exists(), "el hijo murió al cerrarse el Job"


# ----------------------------------------------------------------- scripts
def _script(path: Path) -> AutomationScript:
    return AutomationScript(
        name="saludo",
        description="",
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        runner="python",
        arg_pattern=DEFAULT_ARG_PATTERN,
        max_args=5,
        timeout_seconds=10,
        created_by=uuid.uuid4(),
    )


def test_default_arg_pattern_rejects_options() -> None:
    script = SimpleNamespace(name="s", max_args=5, arg_pattern=DEFAULT_ARG_PATTERN)
    validate_args(script, ["informe.txt", "a-b"])  # type: ignore[arg-type]
    for bad in ["-rf", "--output=x", "-"]:
        with pytest.raises(ValidationAppError):
            validate_args(script, [bad])  # type: ignore[arg-type]


def test_locked_script_detects_tampering_and_blocks_writes(tmp_path: Path) -> None:
    path = tmp_path / "saludo.py"
    path.write_bytes(b"print('hola')\r\n")
    script = _script(path)
    with locked_verified(script) as locked:
        assert locked == path
        if sys.platform == "win32":
            with pytest.raises(PermissionError):
                path.write_text("print('malicioso')")
    path.write_text("print('cambiado')")
    with pytest.raises(ValidationAppError, match="ha cambiado"), locked_verified(script):
        pass


def test_script_run_requires_admin(tmp_path: Path) -> None:
    tool = ScriptRunTool()
    ctx = ctx_for(tmp_path, tmp_path / "data", role="user")
    with pytest.raises(ToolError, match="administrador"):
        asyncio.run(tool.run(ScriptRunArgs(name="saludo"), ctx))
    shown = tool.describe(ScriptRunArgs(name="saludo", args=["a b", "c"]))
    assert '["a b", "c"]' in shown, "los argumentos se muestran sin ambigüedad"


# ----------------------------------------------------------------- 11. contexto
def test_tool_calls_count_towards_tokens_and_big_content_is_omitted() -> None:
    big = "x" * 30_000
    calls = [ToolCallRequest(id="1", name="file_write", arguments={"path": "a", "content": big})]
    history = _history_tool_calls(calls)
    assert history[0]["function"]["arguments"]["content"] == "[30000 caracteres omitidos]"
    assert history[0]["function"]["arguments"]["path"] == "a"
    with_calls = ChatMessage(role="assistant", content="", tool_calls=[{"function": {"x": big}}])
    assert estimate_message_tokens(with_calls) > 10_000


def test_compaction_trims_last_result_by_the_actual_overflow() -> None:
    messages = [
        ChatMessage(role="system", content="s" * 300),
        ChatMessage(role="tool", tool_name="file_read", content="a" * 3000),
        ChatMessage(role="tool", tool_name="file_read", content="b" * 9000),
    ]
    budget = 2500
    out = _compact_tool_results(messages, budget)
    total = sum(estimate_message_tokens(m) for m in out)
    assert total <= budget
    assert out[-1].content.startswith("b") and len(out[-1].content) > 6000, "no se recorta de más"


def test_stored_arguments_never_keep_file_contents() -> None:
    stored = stored_arguments(
        {"path": "a.txt", "content": "secreto " * 10, "args": ["x" * 900], "token": "abc"}
    )
    assert stored["content"] == "[80 caracteres]"
    assert len(stored["args"][0]) <= 501
    assert stored["path"] == "a.txt"


# ----------------------------------------------------------------- 9. voz
@pytest.mark.skipif(importlib.util.find_spec("av") is None, reason="extra [voice] no instalado")
def test_voice_decoding_stops_at_max_duration(tmp_path: Path) -> None:
    from app.modules.voice.service import AudioTooLongError, decode_limited

    def make_wav(path: Path, seconds: int) -> None:
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(struct.pack("<h", 0) * 8000 * seconds)

    short = tmp_path / "corto.wav"
    make_wav(short, 2)
    audio = decode_limited(short, "wav", 10)
    assert abs(audio.shape[0] - 32_000) < 2000 and str(audio.dtype) == "float32"

    long = tmp_path / "largo.wav"
    make_wav(long, 30)
    with pytest.raises(AudioTooLongError):
        decode_limited(long, "wav", 10)
