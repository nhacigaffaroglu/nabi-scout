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
    for page in reader.pages:
        text = str(page.extract_text() or "")
        if not text.strip():
            try:
                text = str(page.extract_text(extraction_mode="layout") or "")
            except TypeError:
                text = ""
        pages.append(text)
    text = "\n".join(pages).strip()
    if not text:
        raise ValueError("kap_pdf_text_empty")
    return text


def try_extract_pdf_text(payload: bytes) -> tuple[Optional[str], Optional[str]]:
    try:
        return extract_pdf_text(payload), None
    except Exception as exc:  # noqa: BLE001 — per-document isolation
        return None, str(exc)[:240]
