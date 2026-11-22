"""Salud del sistema, información del nodo y capacidades habilitadas."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.core.deps import AuthDep, DbDep, StateDep

router = APIRouter(tags=["system"])


class HealthOut(BaseModel):
    status: Literal["ok"]


class ComponentStatus(BaseModel):
    ok: bool
    detail: str | None = None
    version: str | None = None
    latency_ms: int | None = None


class SystemInfoOut(BaseModel):
    app: str
    version: str
    profile: Literal["local", "server"]
    env: str
    default_model: str
    llm_provider: str
    llm: ComponentStatus
    database: ComponentStatus
    active_generations: int


class CapabilitiesOut(BaseModel):
    chat: bool
    streaming: list[str]
    providers: list[str]
    memory: bool
    documents: bool
    tools: bool
    voice: bool
    sync: bool
    remote_access: bool


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """*Liveness* público: no revela información interna."""
    return HealthOut(status="ok")


@router.get("/system/info", response_model=SystemInfoOut)
async def system_info(db: DbDep, state: StateDep, _auth: AuthDep) -> SystemInfoOut:
    provider = state.llm.get()
    llm_health = await provider.health()
    try:
        await db.execute(text("SELECT 1"))
        database = ComponentStatus(ok=True, detail=state.engine.dialect.name)
    except Exception as exc:  # pragma: no cover - depende del entorno
        database = ComponentStatus(ok=False, detail=type(exc).__name__)
    return SystemInfoOut(
        app=state.settings.app_name,
        version=__version__,
        profile=state.settings.profile,
        env=state.settings.env,
        default_model=state.settings.default_model,
        llm_provider=provider.name,
        llm=ComponentStatus(
            ok=llm_health.ok,
            detail=llm_health.detail,
            version=llm_health.version,
            latency_ms=llm_health.latency_ms,
        ),
        database=database,
        active_generations=state.turns.active_count(),
    )


@router.get("/system/capabilities", response_model=CapabilitiesOut)
async def capabilities(state: StateDep, _auth: AuthDep) -> CapabilitiesOut:
    # Se irán activando a medida que se implementen las fases 4–7.
    return CapabilitiesOut(
        chat=True,
        streaming=["websocket", "sse"],
        providers=[p.name for p in state.llm.all()],
        memory=False,
        documents=False,
        tools=False,
        voice=False,
        sync=False,
        remote_access=False,
    )
