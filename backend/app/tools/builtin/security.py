"""Herramientas de ciberseguridad DEFENSIVA sobre los sistemas del propio usuario.

- ``logs_analyze``: patrones de ataque y errores en logs propios.
- ``ioc_match``: busca indicadores de compromiso (IP, dominios, URL, hashes) en archivos.
- ``net_diagnose``: interfaces y puertos en escucha del propio equipo; comprobación de
  puertos SOLO en direcciones privadas o locales (nunca escanea Internet).
- ``security_report``: guarda un reporte en MILT.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Annotated, BinaryIO, ClassVar, Literal

import anyio.to_thread
from pydantic import Field
from sqlalchemy import func, select

from app.modules.automation.models import SecurityReport
from app.modules.documents.parsers import decode_text
from app.tools.base import RiskLevel, Tool, ToolArgs, ToolContext, ToolError, ToolResult, truncate
from app.tools.builtin.files import PathArg, TreeWalker, _guard, _is_binary
from app.tools.sandbox import run_sandboxed

#: Solo se analiza el final del log: memoria acotada aunque el archivo pese gigas.
MAX_LOG_BYTES = 20 * 1024 * 1024
MAX_LINE_BYTES = 8 * 1024
MAX_LINE_CHARS = 2000
MAX_IOC_FILES = 2000
MAX_IOC_TOTAL_BYTES = 200 * 1024 * 1024
MAX_IOC_FILE_BYTES = 20 * 1024 * 1024

IPV4 = re.compile(r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b")
CATEGORIES: dict[str, re.Pattern[str]] = {
    "auth_failure": re.compile(
        r"(failed password|authentication failure|invalid user|login failed|failed login|"
        r"\b4625\b|logon failure|access denied|unauthori[sz]ed|contraseña incorrecta)",
        re.IGNORECASE,
    ),
    "privilege": re.compile(
        r"(sudo:|\bsu\[|\b4672\b|\b4720\b|\b4728\b|\b4732\b|added to .{0,80}admin|privilege)",
        re.IGNORECASE,
    ),
    "web_attack": re.compile(
        r"(\.\./|%2e%2e|/etc/passwd|union(\s|%20|\+)+select|<script|%3cscript|wp-login\.php|"
        r"xmlrpc\.php|cmd\.exe|/bin/(ba)?sh|base64_decode|\$\{jndi:|sleep\(\d+\)|or\s+1=1)",
        re.IGNORECASE,
    ),
    "error": re.compile(r"\b(error|critical|fatal|exception|traceback|panic)\b", re.IGNORECASE),
}
CATEGORY_LABEL = {
    "auth_failure": "Fallos de autenticación",
    "privilege": "Cambios o uso de privilegios",
    "web_attack": "Patrones de ataque web",
    "error": "Errores",
}
HTTP_STATUS = re.compile(r'"\s(\d{3})\s')
BRUTE_FORCE_THRESHOLD = 10


# ------------------------------------------------------------------ logs_analyze
class LogsAnalyzeArgs(ToolArgs):
    path: PathArg
    max_lines: int = Field(default=20_000, ge=100, le=100_000, description="Últimas N líneas")


def _skip_rest_of_line(fh: BinaryIO, piece: bytes) -> None:
    while piece and not piece.endswith(b"\n"):
        piece = fh.readline(MAX_LINE_BYTES)


def tail_lines(path: Path, *, max_lines: int, max_bytes: int = MAX_LOG_BYTES) -> deque[str]:
    """Últimas ``max_lines`` líneas de los últimos ``max_bytes`` bytes, con memoria acotada.

    Se lee línea a línea (cada una como mucho ``MAX_LINE_BYTES``; el resto de una línea
    gigante se descarta) en lugar de cargar y decodificar el archivo entero.
    """
    size = path.stat().st_size
    start = max(0, size - max_bytes)
    lines: deque[str] = deque(maxlen=max_lines)
    with path.open("rb") as fh:
        fh.seek(start)
        if _is_binary(fh.read(8192)):
            raise ToolError("El archivo parece binario (¿un .evtx?). Expórtalo a texto.")
        fh.seek(start)
        if start:
            # Se empezó a mitad de una línea: se descarta ese fragmento.
            _skip_rest_of_line(fh, fh.readline(MAX_LINE_BYTES))
        while piece := fh.readline(MAX_LINE_BYTES):
            _skip_rest_of_line(fh, piece)
            lines.append(decode_text(piece).rstrip("\r\n")[:MAX_LINE_CHARS])
    return lines


def analyze_log_text(lines: list[str] | deque[str]) -> dict[str, object]:
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    ips: Counter[str] = Counter()
    auth_ips: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    for line in lines:
        found_ips = IPV4.findall(line)
        ips.update(found_ips)
        status = HTTP_STATUS.search(line)
        if status:
            statuses[status.group(1)] += 1
        for category, pattern in CATEGORIES.items():
            if pattern.search(line):
                counts[category] += 1
                if len(samples[category]) < 5:
                    samples[category].append(line.strip()[:220])
                if category == "auth_failure":
                    auth_ips.update(found_ips)
    brute = {ip: n for ip, n in auth_ips.items() if n >= BRUTE_FORCE_THRESHOLD}
    if counts["web_attack"] or brute:
        severity = "high"
    elif counts["auth_failure"] > 20 or counts["privilege"]:
        severity = "medium"
    else:
        severity = "low"
    return {
        "lines": len(lines),
        "counts": dict(counts),
        "samples": dict(samples),
        "top_ips": ips.most_common(10),
        "brute_force": brute,
        "http_status": dict(statuses.most_common(10)),
        "severity": severity,
    }


class LogsAnalyzeTool(Tool[LogsAnalyzeArgs]):
    name = "logs_analyze"
    description = (
        "Analiza un archivo de log del usuario: fallos de autenticación, posibles ataques "
        "web, uso de privilegios, errores, IP más frecuentes y posible fuerza bruta."
    )
    risk = RiskLevel.READ
    Args = LogsAnalyzeArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"security"})
    needs_roots = True

    def describe(self, args: LogsAnalyzeArgs) -> str:
        return f"Analizar el log {args.path}"

    async def run(self, args: LogsAnalyzeArgs, ctx: ToolContext) -> ToolResult:
        guard = _guard(ctx)
        path = guard.resolve(args.path)
        if not path.is_file():
            raise ToolError("La ruta no es un archivo.")

        def work() -> dict[str, object]:
            return analyze_log_text(tail_lines(path, max_lines=args.max_lines))

        report = await anyio.to_thread.run_sync(work)
        counts: dict[str, int] = report["counts"]  # type: ignore[assignment]
        samples: dict[str, list[str]] = report["samples"]  # type: ignore[assignment]
        out = [
            f"Análisis de {guard.display(path)} ({report['lines']} líneas). "
            f"Severidad estimada: {report['severity']}.",
        ]
        for category, label in CATEGORY_LABEL.items():
            if counts.get(category):
                out.append(f"\n{label}: {counts[category]}")
                out += [f"  · {s}" for s in samples.get(category, [])]
        brute: dict[str, int] = report["brute_force"]  # type: ignore[assignment]
        top_ips: list[tuple[str, int]] = report["top_ips"]  # type: ignore[assignment]
        if brute:
            out.append(f"\nPosible fuerza bruta (≥{BRUTE_FORCE_THRESHOLD} fallos por IP): {brute}")
        if top_ips:
            out.append("\nIP más frecuentes: " + ", ".join(f"{ip} ({n})" for ip, n in top_ips))
        if report["http_status"]:
            out.append(f"Códigos HTTP: {report['http_status']}")
        summary = (
            ", ".join(f"{CATEGORY_LABEL[c]}: {n}" for c, n in counts.items()) or "Sin hallazgos"
        )
        return ToolResult(
            content=truncate("\n".join(out)),
            summary=f"Severidad {report['severity']} — {summary}",
            data={"severity": report["severity"], "counts": counts},
        )


# ------------------------------------------------------------------ ioc_match
IocKind = Literal["ipv4", "ipv6", "domain", "url", "md5", "sha1", "sha256"]
_HASH_KINDS = {32: "md5", 40: "sha1", 64: "sha256"}
_DOMAIN = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9-]{1,63}\.)+[a-z]{2,63}$", re.IGNORECASE)


def classify_indicator(raw: str) -> tuple[IocKind, str] | None:
    value = raw.strip().strip("[]").replace("[.]", ".").replace("hxxp", "http")
    if not value:
        return None
    if re.fullmatch(r"[0-9a-fA-F]+", value) and len(value) in _HASH_KINDS:
        return _HASH_KINDS[len(value)], value.lower()  # type: ignore[return-value]
    if value.lower().startswith(("http://", "https://")):
        return "url", value.lower()
    try:
        ip = ipaddress.ip_address(value)
        return ("ipv4" if ip.version == 4 else "ipv6"), str(ip)
    except ValueError:
        pass
    if _DOMAIN.fullmatch(value):
        return "domain", value.lower()
    return None


class IocMatchArgs(ToolArgs):
    indicators: list[Annotated[str, Field(max_length=300)]] = Field(
        min_length=1, max_length=100, description="IP, dominios, URL o hashes (md5/sha1/sha256)"
    )
    path: PathArg


class IocMatchTool(Tool[IocMatchArgs]):
    name = "ioc_match"
    description = (
        "Busca indicadores de compromiso (IP, dominios, URL, hashes de archivos) en un "
        "archivo o carpeta del usuario: aparición en logs/textos y hashes de archivos."
    )
    risk = RiskLevel.READ
    Args = IocMatchArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"security"})
    needs_roots = True

    def describe(self, args: IocMatchArgs) -> str:
        return f"Buscar {len(args.indicators)} indicadores en {args.path}"

    async def run(self, args: IocMatchArgs, ctx: ToolContext) -> ToolResult:
        guard = _guard(ctx)
        root = guard.resolve(args.path)
        indicators: dict[str, IocKind] = {}
        invalid: list[str] = []
        for raw in args.indicators:
            parsed = classify_indicator(raw)
            if parsed:
                indicators[parsed[1]] = parsed[0]
            else:
                invalid.append(raw[:60])
        if not indicators:
            raise ToolError("Ningún indicador es válido (IP, dominio, URL o hash).")
        textual = {v for v, k in indicators.items() if k not in ("md5", "sha1", "sha256")}
        hashes = {v: k for v, k in indicators.items() if k in ("md5", "sha1", "sha256")}

        def scan(path: Path, hits: dict[str, list[str]]) -> None:
            # Lectura por fragmentos: hash incremental y búsqueda de texto línea a línea.
            hashers = {kind: hashlib.new(kind) for kind in set(hashes.values())}
            is_text = bool(textual)
            first = True
            number = 1
            with path.open("rb") as fh:
                while piece := fh.readline(64 * 1024):
                    for hasher in hashers.values():
                        hasher.update(piece)
                    if first:
                        is_text = is_text and not _is_binary(piece)
                        first = False
                    if is_text:
                        lowered = decode_text(piece).lower()
                        for value in textual:
                            if value in lowered and len(hits[value]) < 10:
                                hits[value].append(f"{guard.display(path)}:{number}")
                    if piece.endswith(b"\n"):
                        number += 1
            for value, kind in hashes.items():
                if hashers[kind].hexdigest() == value:
                    hits[value].append(f"{guard.display(path)} (hash {kind})")

        def work() -> tuple[dict[str, list[str]], int]:
            hits: dict[str, list[str]] = defaultdict(list)
            scanned = 0
            total = 0
            files: list[Path] = [root] if root.is_file() else []
            if root.is_dir():
                for current, _dirnames, filenames in TreeWalker(root):
                    files += [current / f for f in filenames]
                    if len(files) > MAX_IOC_FILES:
                        break
            for candidate in files[:MAX_IOC_FILES]:
                try:
                    path = guard.resolve(str(candidate))
                    size = path.stat().st_size
                except (ToolError, OSError):
                    continue
                if size > MAX_IOC_FILE_BYTES or total + size > MAX_IOC_TOTAL_BYTES:
                    continue
                total += size
                scanned += 1
                try:
                    scan(path, hits)
                except OSError:
                    continue
            return dict(hits), scanned

        hits, scanned = await anyio.to_thread.run_sync(work)
        lines = [f"Revisados {scanned} archivos con {len(indicators)} indicadores."]
        for value, kind in indicators.items():
            found = hits.get(value)
            lines.append(
                f"- {value} ({kind}): " + ("; ".join(found) if found else "sin apariciones")
            )
        if invalid:
            lines.append(f"No reconocidos: {', '.join(invalid)}")
        matched = sum(1 for v in indicators if hits.get(v))
        return ToolResult(
            content=truncate("\n".join(lines)),
            summary=f"{matched} de {len(indicators)} indicadores encontrados",
            data={"matched": matched},
        )


# ------------------------------------------------------------------ net_diagnose
class NetDiagnoseArgs(ToolArgs):
    check_host: Annotated[str, Field(max_length=253)] | None = Field(
        default=None, description="Host de tu red local a comprobar (opcional)"
    )
    ports: list[Annotated[int, Field(ge=1, le=65535)]] = Field(
        default_factory=list, max_length=10, description="Puertos a comprobar en ese host"
    )


#: Rangos que se consideran «tu red». ``ip.is_private`` es demasiado amplio: incluye
#: 0.0.0.0/8, rangos de documentación, 6to4/NAT64 o 100.64/10 (CGNAT del operador).
OWN_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "::1/128",
        "fe80::/10",
        "fc00::/7",
    )
)


def _is_own_network(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])  # quita el «%zona» de IPv6
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_unspecified or ip.is_multicast:
        return False
    return any(ip.version == net.version and ip in net for net in OWN_NETWORKS)


def _listening_ports() -> list[str]:
    if sys.platform == "win32":
        root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        argv = [str(Path(root) / "System32" / "netstat.exe"), "-ano", "-p", "TCP"]
    else:
        argv = ["/usr/bin/ss", "-ltn"]
    result = run_sandboxed(argv, cwd=Path.cwd(), timeout=15, memory_mb=128)
    listening = []
    for line in result.stdout.splitlines():
        if "LISTEN" in line.upper():
            parts = line.split()
            local = parts[1] if sys.platform == "win32" else parts[3]
            exposed = not local.startswith(("127.", "[::1]", "::1"))
            listening.append(f"{local}{' (expuesto a la red)' if exposed else ''}")
    return sorted(set(listening))[:80]


class NetDiagnoseTool(Tool[NetDiagnoseArgs]):
    name = "net_diagnose"
    description = (
        "Diagnóstico de la red del propio equipo: nombre, IP locales y puertos TCP en "
        "escucha. Opcionalmente comprueba puertos de un host de la red LOCAL (nunca de "
        "Internet). Requiere confirmación."
    )
    risk = RiskLevel.NETWORK
    Args = NetDiagnoseArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"security"})

    def describe(self, args: NetDiagnoseArgs) -> str:
        if args.check_host:
            return f"Diagnóstico de red local y comprobar {args.check_host} puertos {args.ports}"
        return "Diagnóstico de red del propio equipo (IP y puertos en escucha)"

    async def run(self, args: NetDiagnoseArgs, ctx: ToolContext) -> ToolResult:
        def work() -> list[str]:
            out = [f"Equipo: {socket.gethostname()}"]
            try:
                addresses = sorted(
                    {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)}
                )
                out.append("IP locales: " + ", ".join(str(a) for a in addresses))
            except OSError:
                out.append("IP locales: no disponibles")
            ports = _listening_ports()
            out.append(f"Puertos TCP en escucha ({len(ports)}):")
            out += [f"  {p}" for p in ports]
            if args.check_host:
                try:
                    resolved = sorted(
                        {str(i[4][0]) for i in socket.getaddrinfo(args.check_host, None)}
                    )
                except OSError:
                    out.append(f"No se pudo resolver {args.check_host}.")
                    return out
                out.append(f"{args.check_host} resuelve a: {', '.join(resolved)}")
                own = [a for a in resolved if _is_own_network(a)]
                if not own:
                    out.append(
                        "No es una dirección de tu red local: por seguridad no se comprueban "
                        "sus puertos."
                    )
                    return out
                for port in args.ports:
                    try:
                        with socket.create_connection((own[0], port), timeout=1.5):
                            state = "abierto"
                    except OSError:
                        state = "cerrado o filtrado"
                    out.append(f"  {own[0]}:{port} → {state}")
            return out

        lines = await anyio.to_thread.run_sync(work)
        exposed = sum(1 for line in lines if "expuesto" in line)
        return ToolResult(
            content=truncate("\n".join(lines)),
            summary=f"{exposed} puertos expuestos a la red",
        )


# ------------------------------------------------------------------ security_report
class SecurityReportArgs(ToolArgs):
    title: Annotated[str, Field(min_length=3, max_length=200)]
    severity: Literal["info", "low", "medium", "high", "critical"] = "info"
    content: Annotated[str, Field(min_length=10, max_length=20_000, description="Markdown")]


class SecurityReportTool(Tool[SecurityReportArgs]):
    name = "security_report"
    description = (
        "Guarda en MILT un reporte de seguridad en Markdown (hallazgos, severidad y "
        "recomendaciones) para que el usuario lo consulte o descargue."
    )
    risk = RiskLevel.INTERNAL
    Args = SecurityReportArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"security"})

    def describe(self, args: SecurityReportArgs) -> str:
        return f"Guardar el reporte «{args.title}» ({args.severity})"

    async def run(self, args: SecurityReportArgs, ctx: ToolContext) -> ToolResult:
        async with ctx.state.sessionmaker() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(SecurityReport)
                .where(SecurityReport.user_id == ctx.user_id)
            )
            if int(count or 0) >= 1000:
                raise ToolError("Has alcanzado el máximo de 1000 reportes. Elimina alguno.")
            report = SecurityReport(
                user_id=ctx.user_id,
                conversation_id=ctx.conversation_id,
                title=args.title,
                severity=args.severity,
                content=args.content,
            )
            db.add(report)
            await db.commit()
        return ToolResult(
            content=f"Reporte guardado: «{args.title}» (id {report.id}).",
            summary=f"Reporte «{args.title}» guardado",
            data={"report_id": str(report.id)},
        )
