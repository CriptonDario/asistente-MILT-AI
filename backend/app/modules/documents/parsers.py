"""Detección del tipo real de archivo y extracción de texto (PDF, DOCX, XLSX, CSV, TXT).

Se ejecuta en un hilo (operaciones bloqueantes). Seguridad:
- El tipo se decide por el CONTENIDO (firma), no por la extensión declarada.
- DOCX/XLSX son ZIP: se rechazan bombas de descompresión antes de abrirlos.
- Se leen como datos: sin macros, sin fórmulas (``data_only``), sin recursos externos.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.errors import AppError

DocumentKind = Literal["pdf", "docx", "xlsx", "csv", "txt"]

EXTENSIONS: dict[str, DocumentKind] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".txt": "txt",
    ".md": "txt",
    ".log": "txt",
    ".json": "txt",
}
MIME_TYPES: dict[DocumentKind, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "txt": "text/plain",
}

MAX_PDF_PAGES = 1000
MAX_ROWS = 100_000
MAX_CELLS = 500_000
MAX_ZIP_ENTRIES = 5000
MAX_UNZIPPED_BYTES = 300 * 1024 * 1024
MAX_COMPRESSION_RATIO = 150


class UnsupportedDocumentError(AppError):
    status_code = 415
    code = "unsupported_media_type"
    title = "Tipo de archivo no soportado"


class DocumentParseError(AppError):
    status_code = 422
    code = "document_unreadable"
    title = "No se pudo leer el documento"


@dataclass(frozen=True)
class Section:
    """Fragmento de texto con su ubicación en el original."""

    text: str
    locator: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ detección
def _check_zip(path: Path) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise UnsupportedDocumentError(
            "El archivo está dañado o no es un documento válido."
        ) from exc
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise UnsupportedDocumentError("El documento contiene demasiados elementos internos.")
    total = sum(i.file_size for i in infos)
    compressed = sum(i.compress_size for i in infos) or 1
    if total > MAX_UNZIPPED_BYTES or total / compressed > MAX_COMPRESSION_RATIO:
        raise UnsupportedDocumentError("El documento parece una bomba de descompresión.")
    if any(i.flag_bits & 0x1 for i in infos):
        raise UnsupportedDocumentError("Los documentos cifrados no están soportados.")
    return archive


def _looks_like_text(head: bytes) -> bool:
    return b"\x00" not in head


def detect_kind(path: Path, filename: str) -> DocumentKind:
    """Tipo real del archivo. Lanza 415 si no es soportado o no coincide con la extensión."""
    expected = EXTENSIONS.get(Path(filename).suffix.lower())
    if expected is None:
        allowed = ", ".join(sorted(EXTENSIONS))
        raise UnsupportedDocumentError(f"Extensión no soportada. Formatos admitidos: {allowed}.")
    with path.open("rb") as fh:
        head = fh.read(8192)

    actual: DocumentKind
    if head.startswith(b"%PDF-"):
        actual = "pdf"
    elif head.startswith(b"PK\x03\x04"):
        with _check_zip(path) as archive:
            names = set(archive.namelist())
        if "word/document.xml" in names:
            actual = "docx"
        elif "xl/workbook.xml" in names:
            actual = "xlsx"
        else:
            raise UnsupportedDocumentError("Archivo ZIP no reconocido como DOCX ni XLSX.")
    elif _looks_like_text(head):
        actual = "csv" if expected == "csv" else "txt"
    else:
        raise UnsupportedDocumentError("El contenido no corresponde a un formato soportado.")

    if actual != expected:
        raise UnsupportedDocumentError(
            f"El contenido del archivo ({actual}) no coincide con su extensión ({expected})."
        )
    return actual


# ------------------------------------------------------------------ texto
def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _parse_pdf(path: Path) -> list[Section]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentParseError("El PDF está protegido con contraseña.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentParseError(f"El PDF supera {MAX_PDF_PAGES} páginas.")
        sections = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                sections.append(Section(text, {"page": number}))
        return sections
    except DocumentParseError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise DocumentParseError("El PDF está dañado o no se puede leer.") from exc


def _parse_docx(path: Path) -> list[Section]:
    import docx

    try:
        document = docx.Document(str(path))
    except Exception as exc:  # python-docx lanza varios tipos según el daño
        raise DocumentParseError("El DOCX está dañado o no se puede leer.") from exc
    sections = [
        Section(p.text.strip(), {"paragraph": n})
        for n, p in enumerate(document.paragraphs, start=1)
        if p.text.strip()
    ]
    for t, table in enumerate(document.tables, start=1):
        for r, row in enumerate(table.rows, start=1):
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                sections.append(Section(" | ".join(cells), {"table": t, "row": r}))
    return sections


def _row_text(header: list[str] | None, values: list[Any]) -> str:
    cells = ["" if v is None else str(v).strip() for v in values]
    if not any(cells):
        return ""
    if header and len(header) >= len(cells):
        return "; ".join(
            f"{h or f'col{i + 1}'}: {v}"
            for i, (h, v) in enumerate(zip(header, cells, strict=False))
            if v
        )
    return " | ".join(cells)


def _parse_xlsx(path: Path) -> list[Section]:
    from openpyxl import load_workbook

    # Se abre como objeto de archivo: en disco el nombre es un UUID sin extensión y
    # openpyxl rechaza las rutas que no terminan en .xlsx.
    handle = path.open("rb")
    try:
        workbook = load_workbook(handle, read_only=True, data_only=True)
    except Exception as exc:
        handle.close()
        raise DocumentParseError("El XLSX está dañado o no se puede leer.") from exc
    sections: list[Section] = []
    cells = 0
    try:
        for sheet in workbook.worksheets:
            header: list[str] | None = None
            for r, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = list(row)
                cells += len(values)
                if cells > MAX_CELLS or len(sections) > MAX_ROWS:
                    raise DocumentParseError("La hoja de cálculo es demasiado grande.")
                if header is None:
                    header = ["" if v is None else str(v).strip() for v in values]
                    text = " | ".join(h for h in header if h)
                else:
                    text = _row_text(header, values)
                if text:
                    sections.append(Section(text, {"sheet": sheet.title, "row": r}))
    finally:
        workbook.close()
        handle.close()
    return sections


def _parse_csv(path: Path) -> list[Section]:
    text = decode_text(path.read_bytes())
    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    sections: list[Section] = []
    header: list[str] | None = None
    for r, row in enumerate(reader, start=1):
        if r > MAX_ROWS:
            raise DocumentParseError(f"El CSV supera {MAX_ROWS} filas.")
        if header is None:
            header = [h.strip() for h in row]
            line = " | ".join(h for h in header if h)
        else:
            line = _row_text(header, list(row))
        if line:
            sections.append(Section(line, {"row": r}))
    return sections


def _parse_txt(path: Path) -> list[Section]:
    text = decode_text(path.read_bytes()).replace("\r\n", "\n")
    sections: list[Section] = []
    line_number = 1
    for block in text.split("\n\n"):
        stripped = block.strip()
        if stripped:
            sections.append(Section(stripped, {"line": line_number}))
        line_number += block.count("\n") + 2
    return sections


_PARSERS = {
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "xlsx": _parse_xlsx,
    "csv": _parse_csv,
    "txt": _parse_txt,
}


def parse_document(kind: DocumentKind, path: Path) -> list[Section]:
    return _PARSERS[kind](path)
