"""Extract plain text from uploaded files so it can be scanned."""

import io
from pathlib import PurePath

from docx import Document
from pypdf import PdfReader

TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".json", ".md", ".xml", ".html", ".htm", ".log", ".hl7", ".yaml", ".yml"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}


class UnsupportedFileType(Exception):
    pass


class ExtractionError(Exception):
    pass


def extract_text(filename: str, data: bytes) -> str:
    ext = PurePath(filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(
            f"Unsupported file type '{ext or '(none)'}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    try:
        if ext == ".pdf":
            return _pdf_text(data)
        if ext == ".docx":
            return _docx_text(data)
        return _decode(data)
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


def _docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append("\t".join(cell.text for cell in row.cells))
    for section in doc.sections:
        parts.extend(p.text for p in section.header.paragraphs)
        parts.extend(p.text for p in section.footer.paragraphs)
    return "\n".join(parts)
