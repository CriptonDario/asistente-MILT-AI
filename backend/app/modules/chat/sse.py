"""Fallback HTTP con Server-Sent Events para entornos donde el WebSocket no está disponible."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.core.deps import AuthDep, DetachedAuthDep, StateDep
from app.core.errors import NotFoundError
from app.modules.chat.schemas import ChatCompletionRequest, RequestId
from app.modules.chat.service import ChatService, TurnRequest
from app.modules.conversations.service import ConversationService

router = APIRouter(prefix="/chat", tags=["chat"])


def format_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event['type']}\ndata: {data}\n\n"


@router.post(
    "/completions",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat_completions(
    body: ChatCompletionRequest, state: StateDep, auth: DetachedAuthDep
) -> StreamingResponse:
    """Mismo contrato de eventos que el WebSocket, en formato ``text/event-stream``."""
    # Sesiones de BD cortas (no DbDep/AuthDep): las dependencias de la petición vivirían
    # durante todo el stream y retendrían una conexión del pool mientras el modelo genera.
    async with state.sessionmaker() as db:
        await ConversationService(db, state.hlc).get(auth.user.id, body.conversation_id)

    request_id = body.request_id or uuid.uuid4().hex
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    turn = TurnRequest(
        request_id=request_id,
        user_id=auth.user.id,
        user_name=auth.user.display_name,
        user_role=auth.user.role,
        # SSE no admite confirmaciones a mitad del turno: solo herramientas automáticas.
        can_confirm=False,
        conversation_id=body.conversation_id,
        content=body.content,
        model=body.model,
        params=body.params,
        regenerate=body.regenerate,
        attachments=tuple(body.attachments),
        use_memory=body.use_memory,
    )

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def runner() -> None:
        try:
            await ChatService(state).run_turn(turn, emit)
        finally:
            queue.put_nowait(None)

    task = state.turns.start(request_id, auth.user.id, runner)

    async def stream() -> AsyncIterator[str]:
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield format_sse(event)
        finally:
            # El cliente cerró la conexión: se cancela la generación.
            if not task.done():
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{request_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_completion(request_id: RequestId, state: StateDep, auth: AuthDep) -> None:
    if not state.turns.cancel(request_id, auth.user.id):
        raise NotFoundError("No hay ninguna generación en curso con ese id.")
