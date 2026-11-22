"""Middlewares ASGI puros (compatibles con streaming y WebSocket)."""

from __future__ import annotations

import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import problem_response

log = structlog.get_logger("milt.http")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware:
    """Asigna un ``request_id`` por petición, lo expone en la respuesta y registra el acceso."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming if incoming and _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if scope["type"] == "http":
                log.info(
                    "http_request",
                    method=scope.get("method"),
                    path=scope.get("path"),
                    status=status_holder.get("status"),
                    duration_ms=round((time.perf_counter() - start) * 1000, 1),
                )
            structlog.contextvars.clear_contextvars()


class SecurityHeadersMiddleware:
    """Cabeceras de seguridad para las respuestas de la API."""

    _DOC_PREFIXES = ("/docs", "/redoc", "/openapi.json")

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        is_docs = path.startswith(self._DOC_PREFIXES)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                if not is_docs:
                    headers.setdefault(
                        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
                    )
                    headers.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Rechaza cuerpos mayores que ``max_bytes`` (por Content-Length o contando bytes)."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared < 0 or declared > self.max_bytes:
                    response = problem_response(
                        status=413,
                        code="payload_too_large",
                        title="Contenido demasiado grande",
                        detail=f"El cuerpo supera el máximo de {self.max_bytes} bytes.",
                        instance=scope.get("path"),
                    )
                    await response(scope, receive, send)
                    return
                break

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Se corta la lectura: Starlette lo trata como desconexión del cliente.
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, limited_receive, send)
