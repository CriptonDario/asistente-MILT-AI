"""Ejecución aislada de procesos autorizados.

- Lista de argumentos sin shell (``shell=False``): no hay inyección de comandos.
- Entorno mínimo: no se heredan variables con secretos (tokens, claves de API...).
- Límite de tiempo y de salida, y terminación de todo el árbol de procesos.
- Windows: *Job Object* con límite de memoria, de número de procesos y
  ``KILL_ON_JOB_CLOSE`` (si MILT se cierra, el script muere con él).
- POSIX: ``setrlimit`` de memoria y CPU, en un grupo de procesos propio.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

_SAFE_ENV_KEYS = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "LANG",
    "HOME",
    "USERPROFILE",
)


@dataclass(frozen=True)
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool
    duration_ms: int
    killed_by_limit: bool = False
    cancelled: bool = False


def minimal_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in _SAFE_ENV_KEYS}
    # PATH reducido a directorios del sistema y del intérprete (sin rutas de usuario).
    system_paths = []
    if sys.platform == "win32":
        root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        system_paths = [rf"{root}\System32", root, rf"{root}\System32\WindowsPowerShell\v1.0"]
    else:
        system_paths = ["/usr/local/bin", "/usr/bin", "/bin"]
    env["PATH"] = os.pathsep.join(system_paths)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


# ------------------------------------------------------------------ Windows: Job Object
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _LIMIT_ACTIVE_PROCESS = 0x0008
    _LIMIT_JOB_MEMORY = 0x0200
    _LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x0400

    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtResumeProcess.restype = ctypes.c_long  # NTSTATUS
    _ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    _CREATE_SUSPENDED = 0x00000004

    def _create_job(memory_mb: int, max_processes: int) -> Any:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW falló")
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = (
            _LIMIT_JOB_MEMORY
            | _LIMIT_KILL_ON_JOB_CLOSE
            | _LIMIT_ACTIVE_PROCESS
            | _LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        )
        info.BasicLimitInformation.ActiveProcessLimit = max_processes
        info.JobMemoryLimit = memory_mb * 1024 * 1024
        ok = _kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            _kernel32.CloseHandle(job)
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject falló")
        return job


def _reader(stream: IO[bytes], sink: list[bytes], limit: int, flags: dict[str, bool]) -> None:
    """Lee la salida sin acumular más de ``limit`` bytes (el resto se descarta)."""
    total = 0
    while chunk := stream.read(65536):
        if total < limit:
            sink.append(chunk[: limit - total])
        if total + len(chunk) > limit:
            flags["truncated"] = True
        total += len(chunk)


def run_sandboxed(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float,
    max_output_bytes: int = 256 * 1024,
    memory_mb: int = 512,
    max_processes: int = 8,
    cancel: threading.Event | None = None,
) -> ExecResult:
    """Ejecuta ``argv`` con límites. Bloqueante: llamar desde un hilo.

    ``cancel``: si se activa (p. ej. el usuario cancela la respuesta), se mata el proceso
    y todo su árbol sin esperar al ``timeout``.
    """
    if not argv:
        raise ValueError("argv vacío")
    start = time.perf_counter()
    kwargs: dict[str, Any] = {}
    job = None
    if sys.platform == "win32":
        # CREATE_SUSPENDED: el proceso no ejecuta nada hasta estar dentro del Job; si no,
        # podría lanzar hijos que escapen de los límites antes de asignarlo.
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED
        )
    else:

        def _limits() -> None:  # pragma: no cover - solo POSIX
            import resource

            limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            cpu = int(timeout) + 5
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))

        kwargs["preexec_fn"] = _limits
        kwargs["start_new_session"] = True

    process = subprocess.Popen(  # noqa: S603 - argv validado, sin shell
        argv,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=minimal_env(),
        shell=False,
        **kwargs,
    )
    if sys.platform == "win32":
        try:
            job = _create_job(memory_mb, max_processes)
            handle = int(process._handle)  # type: ignore[attr-defined]
            if not _kernel32.AssignProcessToJobObject(job, handle):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject falló")
            status = _ntdll.NtResumeProcess(handle)
            if status != 0:
                raise OSError(status, "NtResumeProcess falló")
        except OSError:
            process.kill()
            process.wait()
            if job:
                _kernel32.CloseHandle(job)
            raise

    out: list[bytes] = []
    err: list[bytes] = []
    flags = {"truncated": False}
    assert process.stdout is not None and process.stderr is not None  # noqa: S101
    readers = [
        threading.Thread(target=_reader, args=(process.stdout, out, max_output_bytes, flags)),
        threading.Thread(target=_reader, args=(process.stderr, err, max_output_bytes, flags)),
    ]
    for t in readers:
        t.daemon = True
        t.start()

    timed_out = False
    cancelled = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                process.wait(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
    except BaseException:
        cancelled = True
        raise
    finally:
        stop = timed_out or cancelled
        if sys.platform == "win32" and job:
            if stop or process.poll() is None:
                _kernel32.TerminateJobObject(job, 1)
            _kernel32.CloseHandle(job)  # KILL_ON_JOB_CLOSE: mata cualquier proceso restante
        elif stop and sys.platform != "win32":  # pragma: no cover - solo POSIX
            import signal

            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        for t in readers:
            t.join(timeout=5)

    exit_code = process.returncode
    # En Windows, un proceso que supera el límite de memoria del Job termina con un
    # código de error de asignación (o 0xC0000017/0xE0434352 según el runtime).
    stopped = timed_out or cancelled
    killed_by_limit = not stopped and exit_code not in (0, None) and _looks_like_oom(err)
    return ExecResult(
        exit_code=None if stopped else exit_code,
        stdout=b"".join(out).decode("utf-8", errors="replace"),
        stderr=b"".join(err).decode("utf-8", errors="replace"),
        timed_out=timed_out,
        truncated=flags["truncated"],
        duration_ms=round((time.perf_counter() - start) * 1000),
        killed_by_limit=killed_by_limit,
        cancelled=cancelled,
    )


def _looks_like_oom(err: list[bytes]) -> bool:
    text = b"".join(err)[-2000:].lower()
    return b"memoryerror" in text or b"out of memory" in text or b"outofmemory" in text
