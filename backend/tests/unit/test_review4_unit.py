"""Regresiones de la revisión de la Fase 4 (parte unitaria)."""

from __future__ import annotations

import time
import zlib
from pathlib import Path

import pytest

from app.modules.documents.chunking import format_locator, merge_locators
from app.modules.documents.parsers import (
    DocumentParseError,
    parse_document,
    parse_isolated,
)
from app.modules.memory.extractor import looks_sensitive, parse_suggestions


def pdf_bomb(pages: int, chars: int) -> bytes:
    """PDF diminuto cuyas páginas comparten un flujo comprimido enorme."""
    content = zlib.compress(b"BT /F1 12 Tf 72 720 Td (" + b"A" * chars + b") Tj ET", 9)
    kids = " ".join(f"{5 + i} 0 R" for i in range(pages))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content)
        + content
        + b"\nendstream",
    ]
    objects += [
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 3 0 R >> >> /Contents 4 0 R >>"
    ] * pages
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out


# 1 --------------------------------------------------------------------------------
def test_pdf_expansion_bomb_is_stopped_quickly(tmp_path: Path) -> None:
    data = pdf_bomb(pages=20, chars=300_000)
    assert len(data) < 20_000, "el archivo es diminuto"
    path = tmp_path / "bomba"
    path.write_bytes(data)
    start = time.perf_counter()
    with pytest.raises(DocumentParseError, match=r"anormalmente grande|demasiado largo"):
        parse_document("pdf", path, max_chars=2_000_000)
    assert time.perf_counter() - start < 30


def test_total_character_budget(tmp_path: Path) -> None:
    path = tmp_path / "largo"
    path.write_bytes(("párrafo de prueba\n\n" * 2000).encode())
    with pytest.raises(DocumentParseError, match="demasiado largo"):
        parse_document("txt", path, max_chars=10_000)


def test_isolated_parser_returns_sections_and_honours_timeout(tmp_path: Path) -> None:
    path = tmp_path / "doc"
    path.write_bytes(b"hola\n\nmundo")
    sections = parse_isolated("txt", path, max_chars=1000, timeout=60)
    assert [s.text for s in sections] == ["hola", "mundo"]
    with pytest.raises(DocumentParseError, match="tardó"):
        parse_isolated("txt", path, max_chars=1000, timeout=0.001)


def test_isolated_parser_reports_parse_errors(tmp_path: Path) -> None:
    path = tmp_path / "roto"
    path.write_bytes(b"%PDF-1.4 roto")
    with pytest.raises(DocumentParseError, match="PDF"):
        parse_isolated("pdf", path, max_chars=1000, timeout=60)


def test_csv_with_huge_field_fails_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "csv"
    path.write_bytes(b'a,b\n"' + b"x" * 200_000 + b'",1\n')
    with pytest.raises(DocumentParseError, match="CSV"):
        parse_document("csv", path, max_chars=10_000_000)


def test_txt_line_numbers_with_many_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "txt"
    path.write_bytes(b"uno\n\n\n\n\ndos\n  \n\ntres")
    sections = parse_document("txt", path, max_chars=1000)
    assert [(s.text, s.locator["line"]) for s in sections] == [
        ("uno", 1),
        ("dos", 6),
        ("tres", 9),
    ]


# citas ----------------------------------------------------------------------------
def test_locators_across_sheets_and_from_paragraph_to_table() -> None:
    across = merge_locators({"sheet": "A", "row": 50}, {"sheet": "B", "row": 3})
    assert format_locator(across) == "hojas A–B"
    mixed = merge_locators({"paragraph": 5}, {"table": 1, "row": 2})
    assert format_locator(mixed) == "tabla 1, fila 2, párrafo 5"


# 10 -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "La clave del wifi de casa es Perro2024!",
        "Su contrasena del banco es hunter22",
        "Su tarjeta es 4111 1111 1111 1111",
        "Tarjeta 4111-1111-1111-1111",
        "El PIN del móvil es 4821",
        "Su IBAN es ES91 2100 0418 4502 0005 1332",
        "Usa la api key sk-abcdefghijklmnop1234",
        "Su token de GitHub es ghp_abcdefghijklmnopqrstuvwxyz1234",
        "AWS: AKIAIOSFODNN7EXAMPLE",
    ],
)
def test_sensitive_suggestions_are_blocked(text: str) -> None:
    assert looks_sensitive(text)
    raw = '[{"content": "' + text + '", "kind": "fact"}]'
    assert parse_suggestions(raw) == []


@pytest.mark.parametrize(
    "text",
    [
        "El usuario pinta cuadros los fines de semana",
        "Trabaja en el proyecto Orion desde 2021",
        "Su número de empleado es 12345",
        "Prefiere explicaciones con ejemplos de código",
    ],
)
def test_normal_suggestions_are_kept(text: str) -> None:
    assert not looks_sensitive(text)
