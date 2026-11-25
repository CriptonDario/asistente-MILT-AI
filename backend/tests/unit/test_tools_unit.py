"""Pruebas unitarias de herramientas: guardián de archivos, políticas, sandbox y herramientas."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.errors import ValidationAppError
from app.modules.automation.models import AutomationScript
from app.modules.automation.scripts import DEFAULT_ARG_PATTERN, build_argv, validate_args
from app.tools.base import Decision, RiskLevel, ToolContext, ToolError
from app.tools.builtin.files import (
    CodeSearchArgs,
    CodeSearchTool,
    FileReadArgs,
    FileReadTool,
    FileWriteArgs,
    FileWriteTool,
    ProjectTreeArgs,
    ProjectTreeTool,
)
from app.tools.builtin.security import (
    IocMatchArgs,
    IocMatchTool,
    LogsAnalyzeArgs,
    LogsAnalyzeTool,
    analyze_log_text,
    classify_indicator,
)
from app.tools.executor import ConfirmationRegistry
from app.tools.fs_guard import FsGuard, validate_root
from app.tools.policy import decide, validate_override
from app.tools.registry import default_registry
from app.tools.sandbox import run_sandboxed


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proyecto"
    (root / "app").mkdir(parents=True)
    (root / "node_modules" / "lib").mkdir(parents=True)
    (root / "app" / "main.py").write_text("def hola():\n    return 'MILT'\n", encoding="utf-8")
    (root / "app" / "routes.php").write_text("<?php\nRoute::get('/', fn() => 'ok');\n")
    (root / "node_modules" / "lib" / "x.js").write_text("ignorar")
    (root / ".env").write_text("SECRET=1")
    return root


def ctx_for(root: Path, data_dir: Path) -> ToolContext:
    state: Any = SimpleNamespace(settings=SimpleNamespace(data_dir=data_dir))
    return ToolContext(
        state=state,
        user_id=uuid.uuid4(),
        user_role="admin",
        conversation_id=None,
        allowed_roots=[root],
    )


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# --------------------------------------------------------------------------- fs_guard
def test_guard_allows_inside_and_blocks_outside(project: Path, tmp_path: Path) -> None:
    guard = FsGuard([project], data_dir=tmp_path / "data")
    assert guard.resolve(str(project / "app" / "main.py")).name == "main.py"
    assert guard.resolve("app/main.py").name == "main.py", "relativa a la primera raíz"
    outside = tmp_path / "fuera.txt"
    outside.write_text("x")
    with pytest.raises(ToolError, match="fuera de las carpetas"):
        guard.resolve(str(outside))
    with pytest.raises(ToolError, match="fuera de las carpetas"):
        guard.resolve(str(project / ".." / "fuera.txt"))


@pytest.mark.parametrize(
    "raw",
    [".env", "app/main.py:oculto", "\\\\servidor\\share\\x", "//servidor/share", "a\x00b"],
)
def test_guard_blocks_sensitive_and_tricky_paths(project: Path, tmp_path: Path, raw: str) -> None:
    guard = FsGuard([project], data_dir=tmp_path / "data")
    with pytest.raises(ToolError):
        guard.resolve(raw if raw.startswith(("\\", "/")) or "\x00" in raw else str(project / raw))


def test_guard_blocks_symlink_escape(project: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secreto.txt"
    secret.write_text("clave")
    link = project / "atajo.txt"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("Crear enlaces simbólicos requiere permisos en este sistema")
    with pytest.raises(ToolError, match="fuera de las carpetas"):
        FsGuard([project], data_dir=tmp_path / "data").resolve(str(link))


def test_guard_requires_roots(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="No hay carpetas autorizadas"):
        FsGuard([], data_dir=tmp_path).resolve("x")


def test_validate_root_rejects_dangerous_folders(project: Path, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    assert validate_root(str(project), data_dir=data_dir) == project.resolve()
    with pytest.raises(ToolError):
        validate_root(str(tmp_path / "no-existe"), data_dir=data_dir)
    with pytest.raises(ToolError):
        validate_root(str(Path(project.anchor)), data_dir=data_dir)
    with pytest.raises(ToolError):
        validate_root(str(data_dir), data_dir=data_dir)
    with pytest.raises(ToolError):
        validate_root(str(Path.home()), data_dir=data_dir)
    with pytest.raises(ToolError):
        validate_root("relativa/carpeta", data_dir=data_dir)


# --------------------------------------------------------------------------- políticas
def test_policy_defaults_overrides_and_limits() -> None:
    registry = default_registry()
    read = registry.get("file_read")
    write = registry.get("file_write")
    script = registry.get("script_run")
    assert read and write and script
    assert decide(read, None, remote=False) == Decision.AUTO
    assert decide(write, None, remote=False) == Decision.CONFIRM
    assert decide(read, {"file_read": "deny"}, remote=False) == Decision.DENY
    assert decide(write, {"file_write": "auto"}, remote=False) == Decision.AUTO
    # Una preferencia guardada no puede saltarse la confirmación obligatoria.
    assert decide(script, {"script_run": "auto"}, remote=False) == Decision.CONFIRM
    with pytest.raises(ValidationAppError):
        validate_override(script, Decision.AUTO)
    assert decide(write, None, remote=True) == Decision.DENY
    assert decide(read, None, remote=True) == Decision.AUTO


def test_registry_profiles_are_small() -> None:
    registry = default_registry()
    names = {t.name for t in registry.for_profile("security")}
    assert {"logs_analyze", "ioc_match", "net_diagnose", "security_report"} <= names
    assert "file_write" not in {t.name for t in registry.for_profile("general")}
    for tool in registry.all():
        spec = tool.spec()
        assert spec["function"]["name"] == tool.name
        assert "title" not in spec["function"]["parameters"]


# --------------------------------------------------------------------------- confirmaciones
def test_confirmation_only_resolvable_by_owner() -> None:
    async def scenario() -> tuple[bool | None, bool | None]:
        registry = ConfirmationRegistry()
        owner, intruder = uuid.uuid4(), uuid.uuid4()
        waiter = asyncio.create_task(registry.wait("c1", owner, 5))
        await asyncio.sleep(0)
        assert registry.resolve("c1", intruder, True) is False
        assert registry.resolve("c1", owner, True) is True
        approved = await waiter
        timed_out = await registry.wait("c2", owner, 0.05)
        return approved, timed_out

    assert run(scenario()) == (True, None)


# --------------------------------------------------------------------------- sandbox
def test_sandbox_runs_without_shell_and_with_clean_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MILT_SECRET_TOKEN", "no-debe-verse")
    result = run_sandboxed(
        [
            sys.executable,
            "-c",
            "import os,sys; print(sys.argv[1:], 'MILT_SECRET_TOKEN' in os.environ)",
            "a; rm -rf /",
            "$(x)",
        ],
        cwd=tmp_path,
        timeout=30,
    )
    assert result.exit_code == 0
    assert "['a; rm -rf /', '$(x)'] False" in result.stdout


def test_sandbox_timeout_and_output_limit(tmp_path: Path) -> None:
    slow = run_sandboxed(
        [sys.executable, "-c", "import time; time.sleep(20)"], cwd=tmp_path, timeout=1
    )
    assert slow.timed_out and slow.exit_code is None
    big = run_sandboxed(
        [sys.executable, "-c", "print('x'*100000)"], cwd=tmp_path, timeout=30, max_output_bytes=500
    )
    assert big.truncated and len(big.stdout) == 500


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects de Windows")
def test_sandbox_memory_limit_on_windows(tmp_path: Path) -> None:
    result = run_sandboxed(
        [sys.executable, "-c", "x = bytearray(600 * 1024 * 1024)"],
        cwd=tmp_path,
        timeout=30,
        memory_mb=128,
    )
    assert result.exit_code != 0
    assert result.killed_by_limit


# --------------------------------------------------------------------------- herramientas
def test_file_read_and_project_tree(project: Path, tmp_path: Path) -> None:
    ctx = ctx_for(project, tmp_path / "data")
    read = run(FileReadTool().run(FileReadArgs(path=str(project / "app" / "main.py")), ctx))
    assert "1 | def hola():" in read.content
    # Visto con qwen3:1.7b: pide max_lines=1 por error; se leen al menos 50 líneas.
    tiny = run(
        FileReadTool().run(FileReadArgs(path=str(project / "app" / "main.py"), max_lines=1), ctx)
    )
    assert "2 |     return 'MILT'" in tiny.content
    tree = run(ProjectTreeTool().run(ProjectTreeArgs(path=str(project)), ctx))
    assert "Python: 1" in tree.content and "PHP: 1" in tree.content
    assert "node_modules" not in tree.content


def test_file_read_rejects_binary_and_env(project: Path, tmp_path: Path) -> None:
    (project / "img.bin").write_bytes(b"\x00\x01\x02")
    ctx = ctx_for(project, tmp_path / "data")
    with pytest.raises(ToolError, match="binario"):
        run(FileReadTool().run(FileReadArgs(path=str(project / "img.bin")), ctx))
    with pytest.raises(ToolError, match="sensible"):
        run(FileReadTool().run(FileReadArgs(path=str(project / ".env")), ctx))


def test_code_search_skips_vendor_dirs(project: Path, tmp_path: Path) -> None:
    ctx = ctx_for(project, tmp_path / "data")
    found = run(CodeSearchTool().run(CodeSearchArgs(query="milt", path=str(project)), ctx))
    assert "main.py:2" in found.content
    nothing = run(CodeSearchTool().run(CodeSearchArgs(query="ignorar", path=str(project)), ctx))
    assert "Sin coincidencias" in nothing.content
    with pytest.raises(ToolError, match="regular"):
        run(CodeSearchTool().run(CodeSearchArgs(query="(", path=str(project), regex=True), ctx))


def test_file_write_creates_and_backs_up(project: Path, tmp_path: Path) -> None:
    ctx = ctx_for(project, tmp_path / "data")
    target = project / "app" / "nuevo.py"
    run(FileWriteTool().run(FileWriteArgs(path=str(target), content="print(1)\n"), ctx))
    assert target.read_text() == "print(1)\n"
    with pytest.raises(ToolError, match="ya existe"):
        run(FileWriteTool().run(FileWriteArgs(path=str(target), content="x"), ctx))
    run(
        FileWriteTool().run(
            FileWriteArgs(path=str(target), content="print(2)\n", overwrite=True), ctx
        )
    )
    assert target.read_text() == "print(2)\n"
    assert (project / "app" / "nuevo.py.milt.bak").read_text() == "print(1)\n"
    with pytest.raises(ToolError):
        run(FileWriteTool().run(FileWriteArgs(path=str(tmp_path / "fuera.py"), content="x"), ctx))


# --------------------------------------------------------------------------- seguridad
AUTH_LOG = [
    *[
        f"Nov 22 10:00:{i:02d} srv sshd[1]: Failed password for root from 203.0.113.9 port 22"
        for i in range(12)
    ],
    "Nov 22 10:01:00 srv sudo: dario : TTY=pts/0 ; COMMAND=/bin/ls",
    "198.51.100.7 - - [22/Nov/2026:10:02:00] "
    '"GET /index.php?id=1 UNION SELECT pass FROM users HTTP/1.1" 200 512',
    '198.51.100.8 - - [22/Nov/2026:10:02:01] "GET /../../etc/passwd HTTP/1.1" 404 0',
    "2026-11-22 ERROR Database connection lost",
]


def test_logs_analysis_detects_attacks() -> None:
    report = analyze_log_text(AUTH_LOG)
    assert report["severity"] == "high"
    assert report["brute_force"] == {"203.0.113.9": 12}
    counts = report["counts"]
    assert counts["auth_failure"] == 12  # type: ignore[index]
    assert counts["web_attack"] == 2  # type: ignore[index]
    assert counts["privilege"] == 1  # type: ignore[index]
    assert counts["error"] == 1  # type: ignore[index]


def test_logs_tool_reads_file(project: Path, tmp_path: Path) -> None:
    log = project / "auth.log"
    log.write_text("\n".join(AUTH_LOG))
    result = run(
        LogsAnalyzeTool().run(LogsAnalyzeArgs(path=str(log)), ctx_for(project, tmp_path / "d"))
    )
    assert "Severidad estimada: high" in result.content
    assert "fuerza bruta" in result.content


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("203.0.113.9", "ipv4"),
        ("evil[.]example.com", "domain"),
        ("hxxp://malo.example/x", "url"),
        ("d41d8cd98f00b204e9800998ecf8427e", "md5"),
        ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "sha256"),
        ("no es un indicador", None),
    ],
)
def test_classify_indicator(raw: str, kind: str | None) -> None:
    parsed = classify_indicator(raw)
    assert (parsed[0] if parsed else None) == kind


def test_ioc_match_finds_ip_and_file_hash(project: Path, tmp_path: Path) -> None:
    (project / "acceso.log").write_text("conexión desde 203.0.113.9\nnormal\n")
    payload = project / "app" / "payload.bin"
    payload.write_bytes(b"malware de prueba")
    sha = hashlib.sha256(b"malware de prueba").hexdigest()
    result = run(
        IocMatchTool().run(
            IocMatchArgs(indicators=["203.0.113.9", sha, "limpio.example.com"], path=str(project)),
            ctx_for(project, tmp_path / "d"),
        )
    )
    assert "acceso.log:1" in result.content
    assert "payload.bin (hash sha256)" in result.content
    assert "limpio.example.com (domain): sin apariciones" in result.content
    assert result.data == {"matched": 2}


# --------------------------------------------------------------------------- scripts
def test_script_args_whitelist_and_argv() -> None:
    script = AutomationScript(
        name="backup",
        path=r"C:\scripts\backup.py",
        sha256="x",
        runner="python",
        arg_pattern=DEFAULT_ARG_PATTERN,
        max_args=2,
        timeout_seconds=30,
    )
    validate_args(script, ["destino", "C:/copias"])
    for bad in (["a; del *"], ["$(calc)"], ['"x"'], ["a", "b", "c"]):
        with pytest.raises(ValidationAppError):
            validate_args(script, bad)
    settings: Any = SimpleNamespace(script_python="python")
    argv = build_argv(script, ["destino"], settings)
    assert argv[1:] == ["-I", r"C:\scripts\backup.py", "destino"]
    assert default_registry().get("script_run").risk == RiskLevel.EXECUTE  # type: ignore[union-attr]
