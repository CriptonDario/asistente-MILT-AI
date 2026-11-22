"""Registro de turnos de generación en curso (cancelación y límite por usuario)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from app.core.errors import ConflictError


class BusyError(ConflictError):
    code = "busy"
    title = "Ya hay generaciones en curso"


class TurnRegistry:
    def __init__(self, *, max_per_user: int) -> None:
        self._max_per_user = max_per_user
        self._turns: dict[str, tuple[uuid.UUID, asyncio.Task[None]]] = {}

    def start(
        self,
        request_id: str,
        user_id: uuid.UUID,
        factory: Callable[[], Coroutine[Any, Any, None]],
    ) -> asyncio.Task[None]:
        if request_id in self._turns:
            raise ConflictError("Ya existe una generación con ese request_id.")
        active = sum(1 for owner, _ in self._turns.values() if owner == user_id)
        if active >= self._max_per_user:
            raise BusyError("Espera a que termine la respuesta en curso o cancélala.")
        task = asyncio.create_task(factory(), name=f"chat-turn-{request_id}")
        self._turns[request_id] = (user_id, task)

        def _cleanup(done: asyncio.Task[None]) -> None:
            current = self._turns.get(request_id)
            if current is not None and current[1] is done:
                del self._turns[request_id]

        task.add_done_callback(_cleanup)
        return task

    def cancel(self, request_id: str, user_id: uuid.UUID) -> bool:
        entry = self._turns.get(request_id)
        if entry is None or entry[0] != user_id:
            return False
        entry[1].cancel()
        return True

    def active_count(self) -> int:
        return len(self._turns)

    async def cancel_all(self) -> None:
        tasks = [task for _, task in self._turns.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
