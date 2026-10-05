"""Extract plain text, and any column headings, from uploaded files."""

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import PurePath

from docx import Document
from pypdf import PdfReader

TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".json", ".md", ".xml", ".html", ".htm", ".log", ".hl7", ".yaml", ".yml"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}


class UnsupportedFileType(Exception):
    pass


class ExtractionError(Exception):
    pass


Columns = dict[str, list[str]]


@dataclass
class Extracted:
    text: str
    # Column heading (or JSON key) -> the non-empty values under it.
    columns: Columns = field(default_factory=dict)


def extract(filename: str, data: bytes) -> Extracted:
    ext = PurePath(filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(
            f"Unsupported file type '{ext or '(none)'}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    try:
        if ext == ".pdf":
            return Extracted(_pdf_text(data))
        if ext == ".docx":
            return _docx(data)
        text = _decode(data)
        if ext in (".csv", ".tsv"):
            return Extracted(text, _delimited_columns(text, "\t" if ext == ".tsv" else ","))
        if ext == ".json":
            return Extracted(text, _json_columns(text))
        return Extracted(text)
    except (UnsupportedFileType, ExtractionError):
        raise
    except Exception as exc:  # malformed PDFs/DOCX raise a variety of errors
        raise ExtractionError(f"Could not read {ext} file: {exc}") from exc


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if reader.pages and not text.strip():
        # Image-only (scanned) PDFs have no text layer; accepting them would
        # let PHI through unscanned, so refuse instead.
        raise ExtractionError("PDF has no extractable text (scanned image?); OCR is not supported")
    return text


def _docx(data: bytes) -> Extracted:
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    columns: Columns = {}
    for table in doc.tables:
        rows = [[cell.text for cell in row.cells] for row in table.rows]
        parts.extend("\t".join(row) for row in rows)
        _merge(columns, _table_columns(rows))
    for section in doc.sections:
        parts.extend(p.text for p in section.header.paragraphs)
        parts.extend(p.text for p in section.footer.paragraphs)
    return Extracted("\n".join(parts), columns)


def _delimited_columns(text: str, delimiter: str) -> Columns:
    try:
        return _table_columns(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error:
        # Not well-formed CSV; the text is still scanned by Presidio.
        return {}


def _table_columns(rows) -> Columns:
    """Treat the first row as headings and collect the non-empty values under each."""
    rows = iter(rows)
    header = [h.strip() for h in next(rows, None) or []]
    columns: Columns = {h: [] for h in header if h}
    for row in rows:
        for heading, value in zip(header, row):
            if heading and value.strip():
                columns[heading].append(value.strip())
    return columns


def _json_columns(text: str) -> Columns:
    try:
        doc = json.loads(text)
    except ValueError:
        return {}
    columns: Columns = {}
    stack = [doc]
    while stack:  # iterative, so deeply nested input can't hit the recursion limit
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                values = columns.setdefault(str(key), [])
                if isinstance(value, (dict, list)):
                    stack.append(value)
                    if isinstance(value, list):
                        values.extend(str(v).strip() for v in value if not isinstance(v, (dict, list)) and _filled(v))
                elif _filled(value):
                    values.append(str(value).strip())
        elif isinstance(node, list):
            stack.extend(v for v in node if isinstance(v, (dict, list)))
    return columns


def _merge(into: Columns, other: Columns) -> None:
    for heading, values in other.items():
        into.setdefault(heading, []).extend(values)


def _filled(value) -> bool:
    return value is not None and str(value).strip() != ""
