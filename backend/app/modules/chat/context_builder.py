"""Construcción de la ventana de contexto respetando el límite de tokens del modelo."""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.base import ChatMessage, ContextOverflowError
from app.llm.tokens import estimate_message_tokens

DEFAULT_OUTPUT_RESERVE = 1024


@dataclass(frozen=True)
class BuiltContext:
    messages: list[ChatMessage]
    dropped: int
    estimated_tokens: int


def output_reserve(num_ctx: int, max_tokens: int | None) -> int:
    """Tokens reservados para la respuesta del modelo."""
    if max_tokens is not None:
        return min(max_tokens, num_ctx // 2)
    return min(DEFAULT_OUTPUT_RESERVE, num_ctx // 4)


def build_context(
    system_prompt: str,
    history: list[ChatMessage],
    *,
    num_ctx: int,
    reserve_output: int,
) -> BuiltContext:
    """Incluye el prompt de sistema y los mensajes más recientes que quepan.

    El último mensaje (el del usuario) es obligatorio: si no cabe se lanza
    ``ContextOverflowError`` en lugar de truncarlo en silencio.
    """
    if not history:
        raise ValueError("El historial no puede estar vacío")

    system = ChatMessage(role="system", content=system_prompt)
    budget = num_ctx - reserve_output
    used = estimate_message_tokens(system)
    selected: list[ChatMessage] = []

    for message in reversed(history):
        cost = estimate_message_tokens(message)
        if used + cost > budget:
            if not selected:
                raise ContextOverflowError(
                    "El mensaje es demasiado largo para el contexto del modelo "
                    f"(~{cost} tokens; disponibles ~{max(0, budget - used)}). "
                    "Acórtalo o aumenta num_ctx."
                )
            break
        selected.append(message)
        used += cost

    selected.reverse()
    # El contexto no debe empezar con una respuesta del asistente huérfana.
    while len(selected) > 1 and selected[0].role == "assistant":
        used -= estimate_message_tokens(selected.pop(0))

    return BuiltContext(
        messages=[system, *selected],
        dropped=len(history) - len(selected),
        estimated_tokens=used,
    )
