"""Punto de entrada de la aplicación FastAPI de MILT AI.

Ejecución en desarrollo (desde ``backend/``)::

    uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import anyio.to_thread
import structlog
from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.core.config import Settings
from app.core.errors import register_exception_handlers
from app.core.hlc import HybridLogicalClock
from app.core.logging import configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.state import AppState
from app.db.migrate import run_migrations
from app.db.session import create_engine, create_sessionmaker
from app.llm.base import LLMProvider
from app.llm.registry import ProviderRegistry, build_default_provider
from app.modules.audit.router import router as audit_router
from app.modules.audit.service import AuditService
from app.modules.auth.router import router as auth_router
from app.modules.auth.router import sessions_router
from app.modules.chat.sse import router as chat_sse_router
from app.modules.chat.turns import TurnRegistry
from app.modules.chat.ws import router as chat_ws_router
from app.modules.conversations.router import router as conversations_router
from app.modules.conversations.router import search_router
from app.modules.models_catalog.router import router as models_router
from app.modules.settings.router import router as settings_router
from app.modules.system.router import router as system_router
from app.modules.users.router import router as users_router
from app.security.passwords import PasswordService
from app.security.secrets_store import load_or_create_jwt_secret
from app.security.tokens import TokenService

API_PREFIX = "/api/v1"

log = structlog.get_logger("milt")

ProviderFactory = Callable[[Settings], LLMProvider]


def create_app(
    settings: Settings | None = None, *, provider_factory: ProviderFactory | None = None
) -> FastAPI:
    settings = settings or Settings()
    factory = provider_factory or build_default_provider

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        if settings.auto_migrate:
            await anyio.to_thread.run_sync(run_migrations, settings.resolved_database_url)

        engine = create_engine(settings)
        sessionmaker = create_sessionmaker(engine)
        provider = factory(settings)
        registry = ProviderRegistry([provider], default=provider.name)
        turns = TurnRegistry(max_per_user=settings.chat_max_turns_per_user)
        app.state.milt = AppState(
            settings=settings,
            engine=engine,
            sessionmaker=sessionmaker,
            passwords=PasswordService(
                time_cost=settings.argon2_time_cost,
                memory_cost_kib=settings.argon2_memory_cost_kib,
                parallelism=settings.argon2_parallelism,
            ),
            tokens=TokenService(
                secret=load_or_create_jwt_secret(settings),
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
                access_ttl_seconds=settings.access_token_ttl_seconds,
            ),
            rate_limiter=SlidingWindowRateLimiter(),
            hlc=HybridLogicalClock(node="local" if settings.profile == "local" else "server"),
            audit=AuditService(sessionmaker),
            llm=registry,
            turns=turns,
        )
        log.info(
            "startup",
            version=__version__,
            profile=settings.profile,
            database=engine.dialect.name,
            llm_provider=provider.name,
            default_model=settings.default_model,
        )
        try:
            yield
        finally:
            await turns.cancel_all()
            await registry.aclose()
            await engine.dispose()
            log.info("shutdown")

    is_prod = settings.env == "production"
    app = FastAPI(
        title="MILT AI",
        version=__version__,
        description="API del asistente personal MILT AI (local-first).",
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/openapi.json",
    )

    register_exception_handlers(app)

    # Orden: el último añadido es el más externo.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.profile == "server")
    # Protección frente a DNS rebinding sobre el backend local.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(RequestContextMiddleware)

    api = APIRouter(prefix=API_PREFIX)
    for router in (
        system_router,
        auth_router,
        sessions_router,
        users_router,
        settings_router,
        models_router,
        conversations_router,
        search_router,
        chat_sse_router,
        chat_ws_router,
        audit_router,
    ):
        api.include_router(router)
    app.include_router(api)
    return app


def _create_default_app() -> FastAPI:
    return create_app()


app = _create_default_app()
