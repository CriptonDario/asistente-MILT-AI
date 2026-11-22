"""Fragmentación de documentos para RAG, conservando la ubicación de cada fragmento."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.llm.tokens import estimate_tokens
from app.modules.documents.parsers import Section


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    locator: dict[str, Any]
    token_count: int


def merge_locators(first: dict[str, Any], last: dict[str, Any]) -> dict[str, Any]:
    """``{page: 3}`` + ``{page: 5}`` -> ``{page: 3, page_end: 5}``."""
    merged = dict(first)
    for key, value in last.items():
        if merged.get(key) != value:
            merged[f"{key}_end"] = value
    return merged


def format_locator(locator: dict[str, Any] | None) -> str:
    """Ubicación legible para citar la fuente."""
    if not locator:
        return ""

    def span(key: str, singular: str, plural: str) -> str | None:
        if key not in locator:
            return None
        end = locator.get(f"{key}_end")
        return f"{plural} {locator[key]}–{end}" if end is not None else f"{singular} {locator[key]}"

    parts: list[str] = []
    if "sheet" in locator:
        sheet = locator["sheet"]
        sheet_end = locator.get("sheet_end")
        parts.append(f"hojas {sheet}–{sheet_end}" if sheet_end else f"hoja {sheet}")
    for key, singular, plural in (
        ("page", "pág.", "págs."),
        ("table", "tabla", "tablas"),
        ("row", "fila", "filas"),
        ("paragraph", "párrafo", "párrafos"),
        ("line", "línea", "líneas"),
    ):
        text = span(key, singular, plural)
        if text:
            parts.append(text)
    return ", ".join(parts)


_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+|\n+")


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """Parte un texto largo en trozos de ~``size`` caracteres respetando frases."""
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            window = text[start:end]
            breaks = [m.end() for m in _SENTENCE_BREAK.finditer(window)]
            good = [b for b in breaks if b > size * 0.5]
            if good:
                end = start + good[-1]
            else:
                space = window.rfind(" ")
                if space > size * 0.5:
                    end = start + space
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [p for p in pieces if p]


def chunk_sections(sections: list[Section], *, size: int, overlap: int) -> list[Chunk]:
    """Agrupa secciones consecutivas en fragmentos de ~``size`` caracteres con solape."""
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_len = 0
    first_loc: dict[str, Any] | None = None
    last_loc: dict[str, Any] = {}

    def flush() -> None:
        nonlocal buffer, buffer_len, first_loc
        if not buffer or first_loc is None:
            return
        text = "\n".join(buffer).strip()
        if text:
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    text=text,
                    locator=merge_locators(first_loc, last_loc),
                    token_count=estimate_tokens(text),
                )
            )
        # Solape: el final de este fragmento abre el siguiente (continuidad de contexto).
        tail = text[-overlap:] if overlap else ""
        buffer = [tail] if tail else []
        buffer_len = len(tail)
        first_loc = dict(last_loc) if tail else None

    for section in sections:
        text = section.text.strip()
        if not text:
            continue
        if len(text) > size:
            flush()
            buffer, buffer_len, first_loc = [], 0, None
            for piece in _split_long(text, size, overlap):
                chunks.append(
                    Chunk(len(chunks), piece, dict(section.locator), estimate_tokens(piece))
                )
            last_loc = section.locator
            continue
        if buffer_len + len(text) + 1 > size and buffer_len > overlap:
            flush()
        if first_loc is None:
            first_loc = dict(section.locator)
        buffer.append(text)
        buffer_len += len(text) + 1
        last_loc = section.locator

    # Último fragmento: no se repite si solo contiene el solape del anterior.
    if buffer and (not chunks or buffer_len > overlap + 1 or len(buffer) > 1):
        flush()
    return chunks
