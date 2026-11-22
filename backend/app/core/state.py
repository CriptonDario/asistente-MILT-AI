"""Contenedor de servicios compartidos durante la vida de la aplicación."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.hlc import HybridLogicalClock
from app.core.rate_limit import SlidingWindowRateLimiter
from app.security.passwords import PasswordService
from app.security.tokens import TokenService

if TYPE_CHECKING:
    from app.llm.registry import ProviderRegistry
    from app.modules.audit.service import AuditService
    from app.modules.chat.turns import TurnRegistry


@dataclass
class AppState:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    passwords: PasswordService
    tokens: TokenService
    rate_limiter: SlidingWindowRateLimiter
    hlc: HybridLogicalClock
    audit: AuditService
    llm: ProviderRegistry
    turns: TurnRegistry
