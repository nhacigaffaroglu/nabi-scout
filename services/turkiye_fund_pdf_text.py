"""Extract text from official KAP file downloads.

KAP `/tr/api/file/download/{id}` wraps a PDF in a Java serialized byte[].
This unwraps that official payload and reads text. No OCR. No invented rows.
"""

from __future__ import annotations

import hashlib
import io
from typing import Optional

PDF_MAGIC = b"%PDF"


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def unwrap_kap_file_bytes(payload: bytes) -> bytes:
    raw = bytes(payload or b"")
    if raw.startswith(PDF_MAGIC) or raw.startswith(b"PK"):
        return raw
    index = raw.find(PDF_MAGIC)
    if index >= 0:
        return raw[index:]
    zip_index = raw.find(b"PK\x03\x04")
    if zip_index >= 0:
        return raw[zip_index:]
    raise ValueError("unrecognized_kap_file_payload")


def extract_pdf_text(payload: bytes) -> str:
    from pypdf import PdfReader

    data = unwrap_kap_file_bytes(payload)
    if not data.startswith(PDF_MAGIC):
        raise ValueError("kap_file_is_not_pdf")
    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    layout_pages: list[str] = []
    for page in reader.pages:
        text = str(page.extract_text() or "")
        layout = ""
        try:
            layout = str(page.extract_text(extraction_mode="layout") or "")
        except TypeError:
            layout = ""
        pages.append(text)
        layout_pages.append(layout)
    default = "\n".join(pages).strip()
    layout = "\n".join(layout_pages).strip()
    chosen = _prefer_official_pdf_text(default, layout)
    if not chosen:
        raise ValueError("kap_pdf_text_empty")
    return chosen


def _prefer_official_pdf_text(default: str, layout: str) -> str:
    """Prefer the official extract with more table structure (ISINs), else longer text."""
    import re

    isin = re.compile(r"\b[A-Z]{2}[A-Z0-9]{10}\b")
    default_n = len(isin.findall(default))
    layout_n = len(isin.findall(layout))
    if layout_n > default_n + 1:
        return layout
    if default_n > layout_n + 1:
        return default
    if len(layout) > len(default) * 1.25:
        return layout
    return default or layout


def try_extract_pdf_text(payload: bytes) -> tuple[Optional[str], Optional[str]]:
    try:
        return extract_pdf_text(payload), None
    except Exception as exc:  # noqa: BLE001 — per-document isolation
        return None, str(exc)[:240]
