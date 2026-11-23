"""Detección de tipo, parsers, fragmentación, nombres seguros y sugerencias de memoria."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.modules.documents.chunking import chunk_sections, format_locator, merge_locators
from app.modules.documents.parsers import (
    Section,
    UnsupportedDocumentError,
    detect_kind,
    parse_document,
)
from app.modules.documents.service import safe_filename
from app.modules.memory.extractor import parse_suggestions
from tests.docfactory import make_docx, make_pdf, make_xlsx


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --------------------------------------------------------------------------- detección
def test_detects_real_types(tmp_path: Path) -> None:
    assert detect_kind(write(tmp_path, "a.pdf", make_pdf(["Hola"])), "a.pdf") == "pdf"
    assert detect_kind(write(tmp_path, "b.docx", make_docx(["x"])), "b.docx") == "docx"
    assert detect_kind(write(tmp_path, "c.xlsx", make_xlsx({"S": [[1]]})), "c.xlsx") == "xlsx"
    assert detect_kind(write(tmp_path, "d.csv", b"a,b\n1,2\n"), "d.csv") == "csv"
    assert detect_kind(write(tmp_path, "e.md", "# Título\nñandú".encode()), "e.md") == "txt"


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("virus.exe", b"MZ\x90\x00"),
        ("falso.pdf", b"esto no es un pdf"),
        ("falso.docx", b"%PDF-1.4 en realidad pdf"),
        ("binario.txt", b"\x00\x01\x02\x03"),
    ],
)
def test_rejects_unsupported_or_mismatched(tmp_path: Path, name: str, data: bytes) -> None:
    with pytest.raises(UnsupportedDocumentError):
        detect_kind(write(tmp_path, name, data), name)


def test_rejects_zip_bomb(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"0" * 5_000_000)  # comprime ~1000:1
    path = write(tmp_path, "bomba.docx", buffer.getvalue())
    with pytest.raises(UnsupportedDocumentError, match="bomba"):
        detect_kind(path, "bomba.docx")


# --------------------------------------------------------------------------- parsers
def test_parse_pdf_pages(tmp_path: Path) -> None:
    path = write(tmp_path, "c4d5e6", make_pdf(["Primera pagina", "Segunda pagina"]))
    sections = parse_document("pdf", path, max_chars=1_000_000)
    assert [s.locator for s in sections] == [{"page": 1}, {"page": 2}]
    assert "Segunda" in sections[1].text


def test_parse_docx_paragraphs_and_tables(tmp_path: Path) -> None:
    data = make_docx(["Introducción", "", "Conclusión"], table=[["Nombre", "Edad"], ["Ana", "30"]])
    sections = parse_document("docx", write(tmp_path, "7b21e0", data), max_chars=1_000_000)
    texts = [s.text for s in sections]
    assert texts[:2] == ["Introducción", "Conclusión"]
    assert "Ana | 30" in texts
    assert sections[-1].locator == {"table": 1, "row": 2}


def test_parse_xlsx_uses_header_and_ignores_formulas(tmp_path: Path) -> None:
    data = make_xlsx({"Ventas": [["Producto", "Total"], ["Café", 12.5], ["Té", "=1+1"]]})
    # En disco el archivo se guarda con un nombre UUID sin extensión.
    sections = parse_document("xlsx", write(tmp_path, "0f3a9c", data), max_chars=1_000_000)
    assert sections[1].text == "Producto: Café; Total: 12.5"
    assert sections[1].locator == {"sheet": "Ventas", "row": 2}
    # data_only=True: la fórmula no se evalúa ni se expone; sin valor calculado queda vacía.
    assert sections[2].text == "Producto: Té"


def test_parse_csv_semicolon_and_latin1(tmp_path: Path) -> None:
    data = "ciudad;población\nMadrid;3300000\nSevilla;680000\n".encode("cp1252")
    sections = parse_document("csv", write(tmp_path, "a.csv", data), max_chars=1_000_000)
    assert sections[1].text == "ciudad: Madrid; población: 3300000"
    assert sections[2].locator == {"row": 3}


def test_parse_txt_paragraph_lines(tmp_path: Path) -> None:
    sections = parse_document(
        "txt", write(tmp_path, "a.txt", b"uno\ndos\n\ntres\n"), max_chars=1_000_000
    )
    assert [(s.text, s.locator["line"]) for s in sections] == [("uno\ndos", 1), ("tres", 4)]


# --------------------------------------------------------------------------- fragmentación
def test_chunks_respect_size_overlap_and_locators() -> None:
    sections = [Section(f"Párrafo {i}. " + "texto " * 40, {"page": i // 3 + 1}) for i in range(12)]
    chunks = chunk_sections(sections, size=800, overlap=100)
    assert len(chunks) > 2
    assert all(len(c.text) <= 800 + 400 for c in chunks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert chunks[0].locator["page"] == 1
    assert any("page_end" in c.locator for c in chunks)
    # Solape: el inicio de cada fragmento repite el final del anterior.
    assert chunks[1].text.startswith(chunks[0].text[-100:].strip()[:20])


def test_long_section_is_split_on_sentences() -> None:
    long_text = " ".join(f"Frase número {i}." for i in range(300))
    chunks = chunk_sections([Section(long_text, {"page": 7})], size=500, overlap=50)
    assert len(chunks) > 5
    assert all(c.locator == {"page": 7} for c in chunks)
    assert all(c.text.endswith(".") for c in chunks[:-1])


def test_small_document_is_one_chunk() -> None:
    chunks = chunk_sections([Section("Hola", {"line": 1})], size=2000, overlap=250)
    assert [c.text for c in chunks] == ["Hola"]


def test_locator_formatting() -> None:
    assert format_locator({"page": 3}) == "pág. 3"
    assert format_locator(merge_locators({"page": 3}, {"page": 5})) == "págs. 3–5"
    assert format_locator({"sheet": "Ventas", "row": 2, "row_end": 40}) == "hoja Ventas, filas 2–40"
    assert format_locator(None) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Windows\\system32\\evil.pdf", "evil.pdf"),
        ("informe<script>.pdf", "informe_script_.pdf"),
        ("", "documento"),
        (None, "documento"),
    ],
)
def test_safe_filename(raw: str | None, expected: str) -> None:
    assert safe_filename(raw) == expected


# --------------------------------------------------------------------------- sugerencias
def test_parse_suggestions_is_tolerant_and_filters_secrets() -> None:
    raw = """<think>pienso...</think> Claro, aquí está:
    [{"content": "El usuario trabaja con Laravel", "kind": "project"},
     {"content": "Su contraseña es hunter2", "kind": "fact"},
     {"content": "Prefiere respuestas breves", "kind": "rara"},
     {"content": "x"}]"""
    items = parse_suggestions(raw)
    assert items == [
        {"content": "El usuario trabaja con Laravel", "kind": "project"},
        {"content": "Prefiere respuestas breves", "kind": "fact"},
    ]
    assert parse_suggestions("no hay json") == []
    assert parse_suggestions("[mal json") == []
