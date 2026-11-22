"""WebSocket ``/api/v1/ws/chat``: streaming de respuestas, cancelación y re-autenticación."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.errors import AppError, UnauthorizedError
from app.core.state import AppState
from app.db.types import utcnow
from app.modules.auth.context import AuthContext, authenticate_claims
from app.modules.chat.schemas import (
    WsAuth,
    WsChatCancel,
    WsChatRegenerate,
    WsChatSend,
    WsPing,
    client_message_adapter,
)
from app.modules.chat.service import ChatService, TurnRequest

log = structlog.get_logger(__name__)

router = APIRouter(tags=["chat"])

AUTH_TIMEOUT_SECONDS = 10.0
MAX_FRAME_CHARS = 200_000
CLOSE_POLICY_VIOLATION = 1008
CLOSE_UNAUTHORIZED = 4401


class _Sender:
    """Serializa los envíos: varias tareas pueden emitir eventos a la vez."""

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket
        self._lock = asyncio.Lock()
        self.closed = False

    async def send(self, payload: dict[str, Any]) -> None:
        if self.closed:
            return
        async with self._lock:
            try:
                await self._ws.send_json(payload)
            except Exception:
                self.closed = True


async def _authenticate(state: AppState, token: str) -> AuthContext:
    claims = state.tokens.decode_access_token(token)
    async with state.sessionmaker() as db:
        return await authenticate_claims(db, claims)


def _error(code: str, detail: str, request_id: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"type": "error", "code": code, "detail": detail}
    if request_id:
        event["request_id"] = request_id
    return event


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket) -> None:
    state: AppState = websocket.app.state.milt

    # CORS no protege WebSockets: se valida el Origin (protección CSWSH).
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in state.settings.cors_origins:
        await websocket.close(code=CLOSE_POLICY_VIOLATION)
        return

    await websocket.accept()
    sender = _Sender(websocket)

    # 1) Autenticación en el primer mensaje (el token nunca viaja en la URL).
    token: str
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT_SECONDS)
        token = WsAuth.model_validate_json(raw).token
        auth = await _authenticate(state, token)
    except (TimeoutError, ValidationError, UnauthorizedError) as exc:
        detail = exc.detail if isinstance(exc, UnauthorizedError) else "Autenticación requerida."
        await sender.send(_error("unauthorized", detail or "Autenticación requerida."))
        with contextlib.suppress(Exception):
            await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    except WebSocketDisconnect:
        return

    await sender.send({"type": "ready", "user_id": str(auth.user.id)})
    connection_tasks: set[asyncio.Task[None]] = set()

    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_FRAME_CHARS:
                await sender.send(_error("frame_too_large", "Mensaje demasiado grande."))
                continue
            try:
                message = client_message_adapter.validate_json(raw)
            except ValidationError as exc:
                fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors()[:5])
                await sender.send(_error("invalid_message", f"Mensaje no válido: {fields}"))
                continue

            if isinstance(message, WsPing):
                await sender.send({"type": "pong"})
                continue

            if isinstance(message, WsAuth):
                try:
                    new_auth = await _authenticate(state, message.token)
                except UnauthorizedError as exc:
                    await sender.send(_error("unauthorized", exc.detail or "Token no válido."))
                    continue
                if new_auth.user.id != auth.user.id:
                    await sender.send(_error("unauthorized", "El token pertenece a otro usuario."))
                    continue
                auth, token = new_auth, message.token
                await sender.send({"type": "ready", "user_id": str(auth.user.id)})
                continue

            if isinstance(message, WsChatCancel):
                if not state.turns.cancel(message.request_id, auth.user.id):
                    await sender.send(
                        _error(
                            "not_found", "No hay ninguna generación con ese id.", message.request_id
                        )
                    )
                continue

            # chat.send / chat.regenerate: se revalida la sesión antes de cada turno.
            assert isinstance(message, WsChatSend | WsChatRegenerate)  # noqa: S101
            if auth.expires_at <= utcnow():
                await sender.send(
                    _error("token_expired", "Envía un nuevo {type:'auth'}.", message.request_id)
                )
                continue
            try:
                auth = await _authenticate(state, token)
            except UnauthorizedError as exc:
                await sender.send(_error("unauthorized", exc.detail or "", message.request_id))
                continue

            turn = TurnRequest(
                request_id=message.request_id,
                user_id=auth.user.id,
                user_name=auth.user.display_name,
                conversation_id=message.conversation_id,
                content=message.content if isinstance(message, WsChatSend) else None,
                model=message.model,
                params=message.params,
                regenerate=isinstance(message, WsChatRegenerate),
                attachments=tuple(message.attachments) if isinstance(message, WsChatSend) else (),
                use_memory=message.use_memory if isinstance(message, WsChatSend) else True,
            )

            def factory(turn: TurnRequest = turn) -> Any:
                return ChatService(state).run_turn(turn, sender.send)

            try:
                task = state.turns.start(message.request_id, auth.user.id, factory)
            except AppError as exc:
                await sender.send(_error(exc.code, exc.detail or exc.title, message.request_id))
                continue
            connection_tasks.add(task)
            task.add_done_callback(connection_tasks.discard)
    except WebSocketDisconnect:
        pass
    finally:
        sender.closed = True
        # Si el cliente se desconecta, se cancelan sus generaciones para liberar la CPU.
        for task in list(connection_tasks):
            if not task.cancelling():
                task.cancel()
        if connection_tasks:
            await asyncio.gather(*connection_tasks, return_exceptions=True)
