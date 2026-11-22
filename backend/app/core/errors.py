"""Jerarquía de errores de la aplicación y respuestas RFC 9457 (Problem Details)."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    """Error de dominio con su estado HTTP y un código estable para el cliente."""

    status_code: int = 500
    code: str = "internal_error"
    title: str = "Error interno del servidor"

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = errors
        self.headers: dict[str, str] = dict(headers or {})


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    title = "Solicitud incorrecta"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    title = "No autenticado"

    def __init__(self, detail: str | None = None, **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)
        self.headers.setdefault("WWW-Authenticate", "Bearer")


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    title = "Acceso denegado"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    title = "Recurso no encontrado"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    title = "Conflicto con el estado actual"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    title = "Contenido demasiado grande"


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_error"
    title = "Datos no válidos"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    title = "Demasiadas solicitudes"

    def __init__(self, retry_after: int, detail: str | None = None) -> None:
        super().__init__(detail, headers={"Retry-After": str(max(1, retry_after))})
        self.retry_after = retry_after


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    title = "Servicio no disponible"


_HTTP_CODES: dict[int, tuple[str, str]] = {
    400: ("bad_request", "Solicitud incorrecta"),
    401: ("unauthorized", "No autenticado"),
    403: ("forbidden", "Acceso denegado"),
    404: ("not_found", "Recurso no encontrado"),
    405: ("method_not_allowed", "Método no permitido"),
    413: ("payload_too_large", "Contenido demasiado grande"),
    415: ("unsupported_media_type", "Tipo de contenido no soportado"),
    429: ("rate_limited", "Demasiadas solicitudes"),
}


def problem_body(
    *,
    status: int,
    code: str,
    title: str,
    detail: str | None,
    instance: str | None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"urn:milt:error:{code}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "instance": instance,
    }
    if errors:
        body["errors"] = errors
    return body


def problem_response(
    *,
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    instance: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=problem_body(
            status=status, code=code, title=title, detail=detail, instance=instance, errors=errors
        ),
        media_type=PROBLEM_JSON,
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Registra los manejadores que convierten cualquier error en Problem Details."""

    async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AppError)  # noqa: S101 - garantizado por el registro
        if exc.status_code >= 500:
            log.error("app_error", code=exc.code, detail=exc.detail)
        return problem_response(
            status=exc.status_code,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            instance=request.url.path,
            errors=exc.errors,
            headers=exc.headers or None,
        )

    async def handle_validation(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)  # noqa: S101
        # Nunca se devuelve el valor recibido: podría contener contraseñas o tokens.
        errors = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type")}
            for err in exc.errors()
        ]
        return problem_response(
            status=422,
            code="validation_error",
            title="Datos no válidos",
            detail="La solicitud contiene datos no válidos.",
            instance=request.url.path,
            errors=errors,
        )

    async def handle_http(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)  # noqa: S101
        code, title = _HTTP_CODES.get(exc.status_code, ("http_error", "Error HTTP"))
        detail = exc.detail if isinstance(exc.detail, str) else None
        return problem_response(
            status=exc.status_code,
            code=code,
            title=title,
            detail=detail,
            instance=request.url.path,
            headers=dict(exc.headers) if exc.headers else None,
        )

    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_exception", path=request.url.path)
        return problem_response(
            status=500,
            code="internal_error",
            title="Error interno del servidor",
            detail="Se produjo un error inesperado.",
            instance=request.url.path,
        )

    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation)
    app.add_exception_handler(StarletteHTTPException, handle_http)
    app.add_exception_handler(Exception, handle_unexpected)
