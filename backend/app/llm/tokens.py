"""Estimación conservadora de tokens (sin tokenizador del modelo).

En español un token equivale de media a unos 3,5–4 caracteres; se usa 3 para no
quedarse corto y evitar que Ollama recorte el contexto silenciosamente.
"""

from __future__ import annotations

import json
import math

from app.llm.base import ChatMessage

CHARS_PER_TOKEN = 3.0
MESSAGE_OVERHEAD_TOKENS = 4


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_message_tokens(message: ChatMessage) -> int:
    tokens = estimate_tokens(message.content) + MESSAGE_OVERHEAD_TOKENS
    if message.tool_calls:
        # Las llamadas a herramientas también ocupan contexto (nombre y argumentos en JSON).
        tokens += estimate_tokens(json.dumps(message.tool_calls, ensure_ascii=False))
    return tokens
