"""Limitador de peticiones en memoria (ventana deslizante).

Válido para un único proceso (perfil local). En el perfil servidor con varios workers
se sustituirá por una implementación respaldada por Redis con la misma interfaz.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque

from app.core.errors import RateLimitedError


class SlidingWindowRateLimiter:
    def __init__(self, *, max_keys: int = 50_000) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._max_keys = max_keys

    async def hit(self, key: str, *, limit: int, window_seconds: float) -> None:
        """Registra un intento; lanza ``RateLimitedError`` si se supera el límite."""
        now = time.monotonic()
        async with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                if len(self._hits) >= self._max_keys:
                    self._prune(now, window_seconds)
                bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] >= window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = math.ceil(window_seconds - (now - bucket[0]))
                raise RateLimitedError(
                    retry_after, "Demasiados intentos. Espera antes de volver a intentarlo."
                )
            bucket.append(now)

    async def reset(self, key: str) -> None:
        async with self._lock:
            self._hits.pop(key, None)

    def _prune(self, now: float, window_seconds: float) -> None:
        stale = [k for k, b in self._hits.items() if not b or now - b[-1] >= window_seconds]
        for k in stale:
            del self._hits[k]
