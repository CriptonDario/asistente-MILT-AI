"""Regresiones de la Fase 5 que faltaban: cancelación real, copia suplantada e ioc_match."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.automation.models import AutomationScript
from app.modules.automation.scripts import DEFAULT_ARG_PATTERN, ScriptService
from app.tools.base import ToolContext, ToolError
from app.tools.builtin.automation import ScriptRunArgs, ScriptRunTool
from app.tools.builtin.files import FileWriteArgs, FileWriteTool
from app.tools.builtin.security import IocMatchArgs, IocMatchTool


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proyecto"
    root.mkdir()
    return root


def ctx_for(root: Path, tmp_path: Path, **state: Any) -> ToolContext:
    settings = SimpleNamespace(
        data_dir=tmp_path / "data",
        profile="local",
        script_python=sys.executable,
        script_memory_mb=512,
    )
    full: Any = SimpleNamespace(settings=settings, **state)
    return ToolContext(
        state=full,
        user_id=uuid.uuid4(),
        user_role="admin",
        conversation_id=None,
        allowed_roots=[root],
    )


def test_cancelling_the_turn_kills_the_running_script(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, finished = project / "empezo.txt", project / "termino.txt"
    path = project / "lento.py"
    path.write_text(
        "import time, pathlib\n"
        f"pathlib.Path(r'{started}').write_text('x')\n"
        "time.sleep(6)\n"
        f"pathlib.Path(r'{finished}').write_text('x')\n"
    )
    script = AutomationScript(
        name="lento",
        description="",
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        runner="python",
        arg_pattern=DEFAULT_ARG_PATTERN,
        max_args=0,
        timeout_seconds=30,
        created_by=uuid.uuid4(),
    )

    async def get_by_name(_self: Any, _name: str) -> AutomationScript:
        return script

    monkeypatch.setattr(ScriptService, "get_by_name", get_by_name)
    ctx = ctx_for(project, tmp_path, sessionmaker=lambda: contextlib.nullcontext())

    async def scenario() -> float:
        task = asyncio.create_task(ScriptRunTool().run(ScriptRunArgs(name="lento"), ctx))
        for _ in range(200):
            if started.exists():
                break
            await asyncio.sleep(0.05)
        assert started.exists(), "el script llegó a arrancar"
        before = time.perf_counter()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return time.perf_counter() - before

    assert asyncio.run(scenario()) < 3, "la cancelación no espera al script"
    time.sleep(7)
    assert not finished.exists(), "el proceso murió: no llegó a terminar"
    path.write_text("# libre")  # el bloqueo de escritura se soltó


@pytest.mark.skipif(sys.platform != "win32", reason="junctions de NTFS")
def test_backup_replaced_by_junction_is_not_written_through(project: Path, tmp_path: Path) -> None:
    import _winapi

    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "intacto.txt").write_text("intacto")
    target = project / "a.txt"
    target.write_text("original")
    _winapi.CreateJunction(str(outside), str(project / "a.txt.milt.bak"))
    asyncio.run(
        FileWriteTool().run(
            FileWriteArgs(path="a.txt", content="nuevo", overwrite=True),
            ctx_for(project, tmp_path),
        )
    )
    assert target.read_text() == "nuevo"
    backup = project / "a.txt.milt.bak"
    assert backup.is_file() and not backup.is_junction() and backup.read_text() == "original"
    assert [p.name for p in outside.iterdir()] == ["intacto.txt"]


def test_backup_path_that_is_a_real_folder_is_refused(project: Path, tmp_path: Path) -> None:
    (project / "a.txt").write_text("original")
    (project / "a.txt.milt.bak").mkdir()
    with pytest.raises(ToolError, match="copia"):
        asyncio.run(
            FileWriteTool().run(
                FileWriteArgs(path="a.txt", content="nuevo", overwrite=True),
                ctx_for(project, tmp_path),
            )
        )
    assert (project / "a.txt").read_text() == "original"


def test_ioc_match_hashes_by_chunks_and_finds_text_anywhere(project: Path, tmp_path: Path) -> None:
    binary = bytes(range(256)) * 2000  # sin saltos regulares, mayor que un fragmento
    (project / "muestra.bin").write_bytes(binary)
    # El indicador cae justo en la frontera entre dos fragmentos de 64 KB de una sola línea.
    straddling = "a " * (32 * 1024 - 3) + "malo.example.com " + "b" * 100
    (project / "una-linea.log").write_text(straddling)
    (project / ".oculta").mkdir()
    (project / ".oculta" / "x.log").write_text("203.0.113.9")
    (project / "normal.log").write_text("uno\ndos 203.0.113.9 tres\n")
    sha = hashlib.sha256(binary).hexdigest()
    result = asyncio.run(
        IocMatchTool().run(
            IocMatchArgs(indicators=[sha, "malo.example.com", "203.0.113.9"], path=str(project)),
            ctx_for(project, tmp_path),
        )
    )
    assert "muestra.bin (hash sha256)" in result.content
    assert "normal.log:2" in result.content
    assert result.content.count("una-linea.log:1") == 1
    assert ".oculta/x.log:1" in result.content, "las carpetas ocultas también se revisan"
