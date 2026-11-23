"""Propuesta de recuerdos a partir de una conversación (el usuario los aprueba después)."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import structlog
from sqlalchemy import select

from app.core.errors import NotFoundError, ValidationAppError
from app.core.state import AppState
from app.llm.base import ChatMessage, GenerationParams, TextDelta
from app.modules.conversations import repository as conv_repo
from app.modules.memory.models import Memory
from app.modules.memory.schemas import MemoryCreate
from app.modules.memory.service import MemoryService

log = structlog.get_logger(__name__)

MAX_SUGGESTIONS = 5
MAX_TRANSCRIPT_CHARS = 9000
VALID_KINDS = {"fact", "preference", "project", "instruction"}

EXTRACTION_PROMPT = """Analiza la conversación y extrae información DURADERA sobre el usuario
que convenga recordar en futuras conversaciones: datos personales que él mismo comparte,
preferencias, proyectos en curso o instrucciones sobre cómo quiere que respondas.

Reglas:
- Solo hechos afirmados por el USUARIO, no por el asistente.
- Nada temporal ni trivial ("hoy estoy cansado", saludos).
- Nunca contraseñas, tokens, números de tarjeta ni datos de terceros.
- Cada recuerdo en una frase corta en tercera persona ("El usuario trabaja con Laravel").
- Como máximo {max_items}.

Responde SOLO con un array JSON, sin texto adicional:
[{{"content": "...", "kind": "fact|preference|project|instruction"}}]
Si no hay nada que recordar, responde [].

CONVERSACIÓN:
{transcript}"""

_SECRET_WORDS = re.compile(
    r"(contrase[nñ]a|password|passwd|\bclaves?\b|\bpin\b|\biban\b|\bcvv\b|\bcvc\b|"
    r"token|api[_ -]?key|secret|credencial|\bseed\b|semilla|mnem[oó]nic)",
    re.IGNORECASE,
)
# Prefijos habituales de claves de API y tokens (OpenAI, GitHub, AWS, Slack, JWT...).
_TOKEN_PATTERN = re.compile(
    r"(\bsk-[A-Za-z0-9_-]{10,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b|"
    r"\bxox[abpr]-[A-Za-z0-9-]{10,}|\beyJ[A-Za-z0-9_-]{10,}\.)"
)
_DIGIT_RUN = re.compile(r"(?:\d[ -]?){13,19}")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def looks_sensitive(text: str) -> bool:
    """Heurística conservadora: ante la duda, no se propone como recuerdo."""
    if _SECRET_WORDS.search(text) or _TOKEN_PATTERN.search(text):
        return True
    for match in _DIGIT_RUN.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return True
    return False


def parse_suggestions(raw: str) -> list[dict[str, str]]:
    """Extrae el primer array JSON de la respuesta del modelo (tolerante a texto extra)."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data: Any = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    out: list[dict[str, str]] = []
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        kind = str(item.get("kind", "fact")).strip().lower()
        if not 4 <= len(content) <= 500 or looks_sensitive(content):
            continue
        out.append({"content": content, "kind": kind if kind in VALID_KINDS else "fact"})
        if len(out) >= MAX_SUGGESTIONS:
            break
    return out


async def extract_suggestions(
    state: AppState, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[list[Memory], int]:
    """Genera sugerencias de recuerdo. Devuelve (creadas, duplicadas omitidas)."""
    async with state.sessionmaker() as db:
        conv = await conv_repo.get_conversation(db, user_id, conversation_id)
        if conv is None:
            raise NotFoundError("Conversación no encontrada.")
        messages = await conv_repo.recent_messages(db, conv.id, limit=60)
        existing = {
            content.lower()
            for content in (
                await db.scalars(
                    select(Memory.content).where(
                        Memory.user_id == user_id, Memory.deleted_at.is_(None)
                    )
                )
            ).all()
        }

    turns = [m for m in messages if m.role in ("user", "assistant") and m.content]
    if not any(m.role == "user" for m in turns):
        raise ValidationAppError("La conversación no tiene mensajes del usuario.")
    transcript = "\n".join(
        f"{'USUARIO' if m.role == 'user' else 'ASISTENTE'}: {m.content}" for m in turns
    )[-MAX_TRANSCRIPT_CHARS:]

    provider = state.llm.get()
    prompt = EXTRACTION_PROMPT.format(max_items=MAX_SUGGESTIONS, transcript=transcript)
    parts: list[str] = []
    async for chunk in provider.chat_stream(
        [ChatMessage(role="user", content=prompt)],
        model=state.settings.default_model,
        params=GenerationParams(temperature=0.1, num_ctx=4096, max_tokens=400, think=False),
    ):
        if isinstance(chunk, TextDelta):
            parts.append(chunk.text)

    suggestions = parse_suggestions("".join(parts))
    created: list[Memory] = []
    skipped = 0
    async with state.sessionmaker() as db:
        service = MemoryService(db, state)
        for item in suggestions:
            if item["content"].lower() in existing:
                skipped += 1
                continue
            existing.add(item["content"].lower())
            created.append(
                await service.create(
                    user_id,
                    MemoryCreate(content=item["content"], kind=item["kind"]),
                    status="suggested",
                    source="extracted",
                    conversation_id=conversation_id,
                )
            )
    log.info("memory_suggestions", created=len(created), skipped=skipped)
    return created, skipped
