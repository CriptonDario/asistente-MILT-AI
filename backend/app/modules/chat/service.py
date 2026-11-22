"""Orquestación de un turno de chat: persistencia, contexto y streaming del modelo."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

from app.agents.profiles import build_system_prompt
from app.core.errors import AppError, NotFoundError, ValidationAppError
from app.core.ids import uuid7
from app.core.state import AppState
from app.llm.base import (
    ChatMessage,
    Done,
    GenerationParams,
    TextDelta,
    ThinkingDelta,
    ToolCallRequest,
    Usage,
)
from app.modules.chat.context_builder import build_context, output_reserve
from app.modules.conversations import repository as conv_repo
from app.modules.conversations.models import Message
from app.modules.conversations.service import title_from_text
from app.modules.settings.models import UserSettings
from app.modules.settings.service import base_generation_params

log = structlog.get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]

HISTORY_LIMIT = 200


@dataclass(frozen=True)
class TurnRequest:
    request_id: str
    user_id: uuid.UUID
    user_name: str
    conversation_id: uuid.UUID
    content: str | None
    model: str | None = None
    params: GenerationParams | None = None
    regenerate: bool = False


@dataclass(frozen=True)
class PreparedTurn:
    model: str
    params: GenerationParams
    messages: list[ChatMessage]
    user_message_id: uuid.UUID
    dropped_messages: int


class ChatService:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.settings = state.settings

    async def run_turn(self, req: TurnRequest, emit: Emit) -> None:
        """Ejecuta un turno completo. Nunca lanza errores de dominio: los emite como eventos."""
        try:
            prepared = await self._prepare(req)
        except AppError as exc:
            await emit(_error_event(req.request_id, exc.code, exc.detail or exc.title))
            return
        except Exception:
            log.exception("chat_prepare_failed", request_id=req.request_id)
            await emit(_error_event(req.request_id, "internal_error", "Error interno."))
            return
        await self._generate(req, prepared, emit)

    # ------------------------------------------------------------------ preparación
    async def _prepare(self, req: TurnRequest) -> PreparedTurn:
        async with self.state.sessionmaker() as db:
            conv = await conv_repo.get_conversation(db, req.user_id, req.conversation_id)
            if conv is None:
                raise NotFoundError("Conversación no encontrada.")
            prefs = await db.get(UserSettings, req.user_id)

            model = req.model or conv.model or (prefs.default_model if prefs else None)
            model = model or self.settings.default_model
            base = base_generation_params(self.settings, prefs)
            if conv.params:
                base = GenerationParams(**conv.params).merged_over(base)
            params = (req.params or GenerationParams()).merged_over(base)

            hlc = self.state.hlc.now()
            if req.regenerate:
                recent = await conv_repo.recent_messages(db, conv.id, limit=2)
                if recent and recent[-1].role == "assistant":
                    recent[-1].soft_delete(hlc)
                    recent = recent[:-1]
                if not recent or recent[-1].role != "user":
                    raise ValidationAppError("No hay ningún mensaje del usuario que regenerar.")
                user_message_id = recent[-1].id
            else:
                content = (req.content or "").strip()
                if not content:
                    raise ValidationAppError("El mensaje está vacío.")
                if len(content) > self.settings.chat_max_input_chars:
                    raise ValidationAppError(
                        f"El mensaje supera {self.settings.chat_max_input_chars} caracteres."
                    )
                user_message = Message(
                    id=uuid7(),
                    conversation_id=conv.id,
                    role="user",
                    content=content,
                    updated_hlc=hlc,
                )
                db.add(user_message)
                user_message_id = user_message.id
                if conv.title is None:
                    conv.title = title_from_text(content)

            conv.model = model
            conv.touch(hlc)
            await db.flush()
            history_rows = await conv_repo.recent_messages(db, conv.id, limit=HISTORY_LIMIT)
            agent_profile = conv.agent_profile
            await db.commit()

        history = [
            ChatMessage(role=m.role, content=m.content)
            for m in history_rows
            if m.role in ("user", "assistant") and m.status != "error" and m.content
        ]
        num_ctx = params.num_ctx or self.settings.default_num_ctx
        context = build_context(
            build_system_prompt(agent_profile, user_name=req.user_name),
            history,
            num_ctx=num_ctx,
            reserve_output=output_reserve(num_ctx, params.max_tokens),
        )
        return PreparedTurn(
            model=model,
            params=params,
            messages=context.messages,
            user_message_id=user_message_id,
            dropped_messages=context.dropped,
        )

    # ------------------------------------------------------------------ generación
    async def _generate(self, req: TurnRequest, prepared: PreparedTurn, emit: Emit) -> None:
        assistant_id = uuid7()
        provider = self.state.llm.get()
        await emit(
            {
                "type": "chat.started",
                "request_id": req.request_id,
                "conversation_id": str(req.conversation_id),
                "message_id": str(assistant_id),
                "user_message_id": str(prepared.user_message_id),
                "model": prepared.model,
                "context_dropped_messages": prepared.dropped_messages,
            }
        )

        parts: list[str] = []
        usage = Usage()
        start = time.perf_counter()
        first_token_ms: int | None = None
        failure: AppError | None = None

        try:
            async for chunk in provider.chat_stream(
                prepared.messages, model=prepared.model, params=prepared.params
            ):
                if isinstance(chunk, TextDelta):
                    if first_token_ms is None:
                        first_token_ms = _elapsed_ms(start)
                    parts.append(chunk.text)
                    await emit(
                        {"type": "chat.delta", "request_id": req.request_id, "text": chunk.text}
                    )
                elif isinstance(chunk, ThinkingDelta):
                    await emit(
                        {"type": "chat.thinking", "request_id": req.request_id, "text": chunk.text}
                    )
                elif isinstance(chunk, ToolCallRequest):
                    # Las herramientas se implementan en la Fase 5; ahora no se ejecuta nada.
                    log.warning("tool_call_ignored", tool=chunk.name, request_id=req.request_id)
                elif isinstance(chunk, Done):
                    usage = chunk.usage
        except asyncio.CancelledError:
            await self._persist_assistant(
                req, assistant_id, prepared.model, parts, usage, _elapsed_ms(start), "cancelled"
            )
            with contextlib.suppress(Exception):
                await emit(_error_event(req.request_id, "cancelled", "Generación cancelada."))
            raise
        except AppError as exc:
            failure = exc
        except Exception:
            log.exception("chat_generation_failed", request_id=req.request_id)
            failure = AppError("Error interno durante la generación.")

        latency_ms = _elapsed_ms(start)
        if failure is not None:
            if parts:
                await self._persist_assistant(
                    req, assistant_id, prepared.model, parts, usage, latency_ms, "error"
                )
            await emit(_error_event(req.request_id, failure.code, failure.detail or failure.title))
            return

        await self._persist_assistant(
            req, assistant_id, prepared.model, parts, usage, latency_ms, "complete"
        )
        await emit(
            {
                "type": "chat.done",
                "request_id": req.request_id,
                "message_id": str(assistant_id),
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "latency_ms": latency_ms,
                    "first_token_ms": first_token_ms,
                },
            }
        )

    async def _persist_assistant(
        self,
        req: TurnRequest,
        message_id: uuid.UUID,
        model: str,
        parts: list[str],
        usage: Usage,
        latency_ms: int,
        status: str,
    ) -> None:
        try:
            async with self.state.sessionmaker() as db:
                conv = await conv_repo.get_conversation(db, req.user_id, req.conversation_id)
                if conv is None:
                    return
                hlc = self.state.hlc.now()
                db.add(
                    Message(
                        id=message_id,
                        conversation_id=conv.id,
                        role="assistant",
                        content="".join(parts),
                        model=model,
                        prompt_tokens=usage.prompt_tokens or None,
                        completion_tokens=usage.completion_tokens or None,
                        latency_ms=latency_ms,
                        status=status,
                        updated_hlc=hlc,
                    )
                )
                conv.touch(hlc)
                await db.commit()
        except Exception:
            log.exception("chat_persist_failed", request_id=req.request_id)


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _error_event(request_id: str, code: str, detail: str) -> dict[str, Any]:
    return {"type": "chat.error", "request_id": request_id, "code": code, "detail": detail}
