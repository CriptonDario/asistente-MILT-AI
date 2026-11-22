"""Orquestación de un turno de chat: persistencia, contexto y streaming del modelo."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
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
from app.modules.chat.augment import gather_context
from app.modules.chat.context_builder import build_context, output_reserve
from app.modules.conversations import repository as conv_repo
from app.modules.conversations.models import Message
from app.modules.conversations.service import title_from_text
from app.modules.documents.models import MessageAttachment
from app.modules.documents.service import DocumentService
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
    attachments: tuple[uuid.UUID, ...] = ()
    use_memory: bool = True


@dataclass(frozen=True)
class PreparedTurn:
    model: str
    params: GenerationParams
    messages: list[ChatMessage]
    user_message_id: uuid.UUID
    dropped_messages: int
    replaces_message_id: uuid.UUID | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ChatService:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.settings = state.settings

    async def run_turn(self, req: TurnRequest, emit: Emit) -> None:
        """Ejecuta un turno completo. Nunca lanza errores de dominio: los emite como eventos."""
        try:
            prepared = await self._prepare(req)
        except asyncio.CancelledError:
            # Cancelado antes de empezar: el cliente debe recibir igualmente un evento final.
            await _shielded(_safe_emit(emit, _cancelled_event(req.request_id)))
            raise
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
        """Tres fases: lectura/validación, recuperación de contexto y escritura.

        La recuperación (embeddings en Ollama) se hace sin transacción abierta para no
        bloquear la escritura en SQLite mientras tanto.
        """
        # --- 1. Lectura y validación (nada se escribe todavía) -----------------------
        async with self.state.sessionmaker() as db:
            conv = await conv_repo.get_conversation(db, req.user_id, req.conversation_id)
            if conv is None:
                raise NotFoundError("Conversación no encontrada.")
            prefs = await db.get(UserSettings, req.user_id)

            model = req.model or conv.model or (prefs.default_model if prefs else None)
            model = model or self.settings.default_model
            # Un modelo inexistente o el motor apagado no deben dejar la conversación en un
            # estado inconsistente: se valida antes de escribir.
            await self.state.llm.get().get_model(model)
            base = base_generation_params(self.settings, prefs)
            if conv.params:
                base = GenerationParams(**conv.params).merged_over(base)
            params = (req.params or GenerationParams()).merged_over(base)

            replaces_message_id: uuid.UUID | None = None
            regenerate_user_id: uuid.UUID | None = None
            if req.regenerate:
                recent = await conv_repo.recent_messages(db, conv.id, limit=2)
                if recent and recent[-1].role == "assistant":
                    # La respuesta anterior se retira solo cuando la nueva se guarde.
                    replaces_message_id = recent[-1].id
                    recent = recent[:-1]
                if not recent or recent[-1].role != "user":
                    raise ValidationAppError("No hay ningún mensaje del usuario que regenerar.")
                regenerate_user_id = recent[-1].id
                query = recent[-1].content
            else:
                query = (req.content or "").strip()
                if not query:
                    raise ValidationAppError("El mensaje está vacío.")
                if len(query) > self.settings.chat_max_input_chars:
                    raise ValidationAppError(
                        f"El mensaje supera {self.settings.chat_max_input_chars} caracteres."
                    )

            new_attachments = list(dict.fromkeys(req.attachments))
            if new_attachments:
                ready = await DocumentService(db, self.state).ready_ids(
                    req.user_id, new_attachments
                )
                if len(ready) != len(new_attachments):
                    raise ValidationAppError(
                        "Algún documento adjunto no existe o todavía se está procesando."
                    )
            scope = list(
                dict.fromkeys(
                    [*await conv_repo.conversation_document_ids(db, conv.id), *new_attachments]
                )
            )
            use_memory = req.use_memory and (prefs.memory_enabled if prefs else True)

        # --- 2. Recuperación de contexto (memoria + documentos) -----------------------
        num_ctx = params.num_ctx or self.settings.default_num_ctx
        augmentation = await gather_context(
            self.state,
            req.user_id,
            query,
            use_memory=use_memory,
            document_ids=scope,
            num_ctx=num_ctx,
        )
        system_prompt = build_system_prompt(conv.agent_profile, user_name=req.user_name)
        if augmentation.system_addendum:
            system_prompt = f"{system_prompt}\n\n{augmentation.system_addendum}"

        # --- 3. Escritura -------------------------------------------------------------
        async with self.state.sessionmaker() as db:
            conv = await conv_repo.get_conversation(db, req.user_id, req.conversation_id)
            if conv is None:
                raise NotFoundError("Conversación no encontrada.")
            hlc = self.state.hlc.now()
            if regenerate_user_id is not None:
                user_message_id = regenerate_user_id
            else:
                user_message = Message(
                    id=uuid7(),
                    conversation_id=conv.id,
                    role="user",
                    content=query,
                    updated_hlc=hlc,
                )
                db.add(user_message)
                user_message_id = user_message.id
                db.add_all(
                    MessageAttachment(message_id=user_message.id, document_id=doc_id)
                    for doc_id in new_attachments
                )
                if conv.title is None:
                    conv.title = title_from_text(query)

            # El modelo de la petición es puntual: el de la conversación solo cambia con PATCH.
            conv.touch(hlc)
            await db.flush()
            history_rows = await conv_repo.recent_messages(db, conv.id, limit=HISTORY_LIMIT)
            history = [
                ChatMessage(role=m.role, content=m.content)
                for m in history_rows
                if m.role in ("user", "assistant")
                and m.status != "error"
                and m.content
                and m.id != replaces_message_id
            ]
            # Si el mensaje no cabe, se lanza aquí y no se guarda nada (rollback al salir).
            context = build_context(
                system_prompt,
                history,
                num_ctx=num_ctx,
                reserve_output=output_reserve(num_ctx, params.max_tokens),
            )
            await db.commit()

        return PreparedTurn(
            model=model,
            params=params,
            messages=context.messages,
            user_message_id=user_message_id,
            dropped_messages=context.dropped,
            replaces_message_id=replaces_message_id,
            sources=augmentation.sources,
            warnings=augmentation.warnings,
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
        if prepared.sources or prepared.warnings:
            await emit(
                {
                    "type": "chat.context",
                    "request_id": req.request_id,
                    "sources": prepared.sources,
                    "warnings": prepared.warnings,
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
            elapsed = _elapsed_ms(start)

            async def finish_cancelled() -> None:
                if parts:
                    await self._persist_assistant(
                        req, assistant_id, prepared, parts, usage, elapsed, "cancelled"
                    )
                await _safe_emit(emit, _cancelled_event(req.request_id))

            # Protegido: una segunda cancelación (p. ej. el usuario pulsa detener y cierra
            # la pestaña) no debe perder la respuesta parcial ni el evento final.
            await _shielded(finish_cancelled())
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
                    req, assistant_id, prepared, parts, usage, latency_ms, "error"
                )
            await emit(_error_event(req.request_id, failure.code, failure.detail or failure.title))
            return

        await self._persist_assistant(
            req, assistant_id, prepared, parts, usage, latency_ms, "complete"
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
        prepared: PreparedTurn,
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
                # Regeneración: la respuesta anterior se retira al guardar la nueva
                # (si la nueva acaba en error, se conservan las dos).
                if prepared.replaces_message_id is not None and status != "error":
                    old = await conv_repo.get_message(db, conv.id, prepared.replaces_message_id)
                    if old is not None:
                        old.soft_delete(hlc)
                db.add(
                    Message(
                        id=message_id,
                        conversation_id=conv.id,
                        role="assistant",
                        content="".join(parts),
                        model=prepared.model,
                        prompt_tokens=usage.prompt_tokens or None,
                        completion_tokens=usage.completion_tokens or None,
                        latency_ms=latency_ms,
                        status=status,
                        context_sources=prepared.sources or None,
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


def _cancelled_event(request_id: str) -> dict[str, Any]:
    return _error_event(request_id, "cancelled", "Generación cancelada.")


async def _safe_emit(emit: Emit, event: dict[str, Any]) -> None:
    with contextlib.suppress(Exception):
        await emit(event)


#: Referencias a tareas protegidas en curso (evita que el GC las destruya).
_background_tasks: set[asyncio.Task[None]] = set()


async def _shielded(coro: Coroutine[Any, Any, None]) -> None:
    """Ejecuta ``coro`` en una tarea propia que sobrevive a cancelaciones posteriores."""
    task = asyncio.ensure_future(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    await asyncio.shield(task)
