"""Recover official KAP mandate/governance text without assuming image-only PDFs are empty.

Layer order:
1. KAP notification HTML / structured disclosure
2. KAP file/download text layer (Word/Excel/export + unwrapped payload)
3. Embedded PDF text
4. OCR from the official document only as last resort

Do not mix text from different document versions.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Mapping, Optional

from services.turkiye_fund_kap_rsc import kap_file_url, parse_kap_bildirim_rsc
from services.turkiye_fund_ocr import TEXT_ORIGIN_OCR, ocr_official_pdf
from services.turkiye_fund_pdf_text import sha256_hex, try_extract_pdf_text, unwrap_kap_file_bytes
from services.official_kap_pdr import _fold

LAYER_NOTIFICATION_HTML = "KAP_NOTIFICATION_HTML"
LAYER_FILE_TEXT = "KAP_FILE_TEXT_LAYER"
LAYER_PDF_EMBEDDED = "PDF_EMBEDDED_TEXT"
LAYER_OCR = TEXT_ORIGIN_OCR
LAYER_UNAVAILABLE = "TEXT_LAYER_UNAVAILABLE"

_TAG = re.compile(r"<[^>]+>")
# Title-common tokens such as "kira sertifikaları" must not count as a KAP HTML body.
_HTML_BODY_TOKENS = (
    "katılım fonu statüsündedir",
    "katılım prensiplerine uygunluğu esas",
    "faizsiz/katılım finans ilkelerine uygun",
    "portföy yönetiminde katılım prensiplerine uygunluk",
    "danışma komitesi",
    "danışma kurulu",
    "icazet belgesi",
)


def html_to_text(html: str) -> str:
    body = _TAG.sub(" ", str(html or ""))
    return re.sub(r"\s+", " ", body).strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _has_official_body(text: str) -> bool:
    blob = _fold(text)
    if len(blob) < 40:
        return False
    return any(_fold(token) in blob for token in _HTML_BODY_TOKENS)


def notification_export_urls(disclosure_index: Any) -> dict[str, str]:
    index = str(disclosure_index or "").strip()
    if not index:
        return {}
    host = "https://www.kap.org.tr"
    return {
        "html": f"{host}/tr/Bildirim/{index}",
        "pdf": f"{host}/tr/api/BildirimPdf/{index}",
        "word": f"{host}/tr/api/notification/export/word/{index}",
        "excel": f"{host}/tr/api/notification/export/excel/{index}",
    }


def recover_official_document_text(
    session: Any,
    *,
    file_oid: str,
    disclosure_index: Any = None,
    document_type: str,
    published_at: str = "",
    referer: str = "",
    ocr_fn: Optional[Callable[[bytes], str]] = None,
    allow_ocr: bool = False,
) -> dict[str, Any]:
    """Recover one official document. Layers stay separate. No version mixing."""
    record: dict[str, Any] = {
        "document_type": document_type,
        "notification_id": str(disclosure_index or "") or None,
        "file_oid": file_oid or None,
        "published_at": published_at or None,
        "source_layer": LAYER_UNAVAILABLE,
        "text_available": False,
        "text_hash": None,
        "text_origin": None,
        "text": None,
        "layers_attempted": [],
        "layers_successful": [],
    }
    urls = notification_export_urls(disclosure_index)
    html_text = ""
    if urls.get("html"):
        record["layers_attempted"].append(LAYER_NOTIFICATION_HTML)
        try:
            raw_html = session.http_get_text(
                urls["html"],
                accept="text/html",
                referer="https://www.kap.org.tr/",
            )
            html_text = html_to_text(raw_html)
            rsc = session.kap_rsc(urls["html"])
            parsed = parse_kap_bildirim_rsc(rsc)
            if parsed.get("file_oid") and not record["file_oid"]:
                record["file_oid"] = parsed.get("file_oid")
        except Exception as exc:  # noqa: BLE001
            record["html_error"] = str(exc)[:240]
        if _has_official_body(html_text):
            record["source_layer"] = LAYER_NOTIFICATION_HTML
            record["text"] = html_text
            record["text_available"] = True
            record["text_hash"] = text_hash(html_text)
            record["text_origin"] = LAYER_NOTIFICATION_HTML
            record["layers_successful"].append(LAYER_NOTIFICATION_HTML)
            return record

    file_oid = str(record.get("file_oid") or file_oid or "").strip()
    raw_file = b""
    if file_oid:
        record["layers_attempted"].append(LAYER_FILE_TEXT)
        try:
            raw_file = session.http_get_bytes(
                kap_file_url(file_oid),
                accept="application/pdf,application/octet-stream,application/msword,*/*",
                referer=referer or urls.get("html") or "https://www.kap.org.tr/",
            )
            try:
                unwrapped = unwrap_kap_file_bytes(raw_file)
            except ValueError:
                unwrapped = raw_file
            if unwrapped[:1] in {b"<", b"{"} or unwrapped[:5] in {b"<html", b"<?xml"}:
                file_text = html_to_text(unwrapped.decode("utf-8", "replace"))
                if _has_official_body(file_text):
                    record["source_layer"] = LAYER_FILE_TEXT
                    record["text"] = file_text
                    record["text_available"] = True
                    record["text_hash"] = text_hash(file_text)
                    record["text_origin"] = LAYER_FILE_TEXT
                    record["layers_successful"].append(LAYER_FILE_TEXT)
                    return record
        except Exception as exc:  # noqa: BLE001
            record["file_error"] = str(exc)[:240]

    record["layers_attempted"].append(LAYER_PDF_EMBEDDED)
    pdf_text, pdf_error = try_extract_pdf_text(raw_file) if raw_file else (None, "no_file")
    if pdf_text and pdf_text.strip():
        record["source_layer"] = LAYER_PDF_EMBEDDED
        record["text"] = pdf_text
        record["text_available"] = True
        record["text_hash"] = text_hash(pdf_text)
        record["text_origin"] = LAYER_PDF_EMBEDDED
        record["sha256"] = sha256_hex(unwrap_kap_file_bytes(raw_file)) if raw_file else None
        record["layers_successful"].append(LAYER_PDF_EMBEDDED)
        return record
    if pdf_error:
        record["pdf_error"] = pdf_error

    if allow_ocr and raw_file:
        record["layers_attempted"].append(LAYER_OCR)
        ocr_text, ocr_meta = ocr_official_pdf(raw_file, ocr_fn=ocr_fn)
        if ocr_text:
            record["source_layer"] = LAYER_OCR
            record["text"] = ocr_text
            record["text_available"] = True
            record["text_hash"] = text_hash(ocr_text)
            record["text_origin"] = LAYER_OCR
            record["layers_successful"].append(LAYER_OCR)
            return record
        record["ocr_error"] = ocr_meta

    record["text_origin"] = LAYER_UNAVAILABLE
    return record
