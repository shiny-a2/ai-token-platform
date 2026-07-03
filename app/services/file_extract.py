"""Text extraction from uploaded files so chat can answer questions about them.

Supported in v1: PDF (pypdf), plain text (txt/csv/md/json/log).
The extracted text is stored on the FileAsset row and billed as part of the
prompt context — the user pays for exactly the tokens the file adds.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("file_extract")

# keep prompts bounded: ~60k chars ≈ 15-20k tokens worst case
MAX_EXTRACT_CHARS = 60_000

TEXT_EXTENSIONS = {".txt", ".csv", ".md", ".json", ".log"}
PDF_EXTENSIONS = {".pdf"}


def extractable(filename: str) -> bool:
    ext = _ext(filename)
    return ext in TEXT_EXTENSIONS or ext in PDF_EXTENSIONS


def _ext(filename: str) -> str:
    name = (filename or "").lower()
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def extract_text(path: str | Path, filename: str) -> str | None:
    """Return extracted text (truncated) or None if unsupported/failed."""
    p = Path(path)
    if not p.exists():
        return None
    ext = _ext(filename or p.name)
    try:
        if ext in TEXT_EXTENSIONS:
            raw = p.read_bytes()
            for enc in ("utf-8", "utf-8-sig", "cp1256", "latin-1"):
                try:
                    return raw.decode(enc)[:MAX_EXTRACT_CHARS]
                except UnicodeDecodeError:
                    continue
            return None
        if ext in PDF_EXTENSIONS:
            from pypdf import PdfReader

            reader = PdfReader(str(p))
            parts: list[str] = []
            total = 0
            for page in reader.pages:
                text = page.extract_text() or ""
                parts.append(text)
                total += len(text)
                if total >= MAX_EXTRACT_CHARS:
                    break
            return "\n".join(parts)[:MAX_EXTRACT_CHARS] or None
    except Exception as exc:  # noqa: BLE001
        log.warning("extract failed for %s: %s", filename, exc)
    return None
