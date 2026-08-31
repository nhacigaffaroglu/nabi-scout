"""Turkish fund source-date semantics and future-publication firewall.

COMPUTE only. Distinguishes published_at, effective_at, report_period,
source_as_of, and document_version_date. Does not write.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Mapping, Optional

from services.official_kap_pdr import parse_tr_date, parse_tr_datetime
from services.turkiye_fund_refresh_contract import (
    LAYER_ECONOMIC_EXPOSURE,
    LAYER_EIGHT_E,
    LAYER_FUND_INTELLIGENCE,
    LAYER_IDENTITY,
    LAYER_PARTICIPATION,
)

SEMANTIC_PUBLISHED_AT = "PUBLISHED_AT"
SEMANTIC_EFFECTIVE_AT = "EFFECTIVE_AT"
SEMANTIC_REPORT_PERIOD = "REPORT_PERIOD"
SEMANTIC_SOURCE_AS_OF = "SOURCE_AS_OF"
SEMANTIC_DOCUMENT_VERSION_DATE = "DOCUMENT_VERSION_DATE"

CURRENT_EVIDENCE_SEMANTICS = frozenset({SEMANTIC_PUBLISHED_AT, SEMANTIC_SOURCE_AS_OF})

_ISO_DATE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_PDF_DATE = re.compile(r"D:(\d{8})")
_FILENAME_PERIOD = re.compile(r"(20\d{2})[._-](\d{2})")
_LAYER_DATE_FIELDS = {
    LAYER_IDENTITY: ("kap_mandate", "kap_izahname"),
    LAYER_PARTICIPATION: ("kap_mandate", "kap_izahname"),
    LAYER_FUND_INTELLIGENCE: ("tefas_price",),
    LAYER_ECONOMIC_EXPOSURE: ("kap_pdr",),
    LAYER_EIGHT_E: ("tefas_price", "kap_pdr"),
}


class FutureSourceDateError(ValueError):
    """Publication/source_as_of is after calculated_at."""


def parse_iso_date(value: Any) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    match = _ISO_DATE.search(text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def as_date(value: Any) -> Optional[date]:
    parsed = parse_iso_date(value)
    if parsed is not None:
        return parsed
    token = parse_official_date(value)
    return parse_iso_date(token) if token else None


def parse_pdf_info_date(raw: Any) -> Optional[str]:
    text = str(raw or "").strip()
    match = _PDF_DATE.search(text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def parse_official_date(raw: Any) -> Optional[str]:
    """Parse Turkish dd/mm/yyyy, ISO, or PDF Info dates. Never year-first yy/mm/dd."""
    text = str(raw or "").strip()
    if not text:
        return None
    iso = parse_iso_date(text)
    if iso is not None:
        return iso.isoformat()
    pdf = parse_pdf_info_date(text)
    if pdf:
        return pdf
    parsed = parse_tr_date(text)
    if parsed:
        return parsed
    dt = parse_tr_datetime(text)
    if dt is not None:
        return dt.date().isoformat()
    return None


def filename_period(name: Any) -> Optional[str]:
    match = _FILENAME_PERIOD.search(str(name or ""))
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def resolve_kap_document_date(
    *,
    structured_publish_date: Any = None,
    pdf_xmp_date: Any = None,
    filename: Any = None,
) -> tuple[Optional[str], Optional[str], str]:
    """Structured KAP metadata wins. Filename is never canonical."""
    structured = parse_official_date(structured_publish_date)
    if structured:
        return structured, SEMANTIC_PUBLISHED_AT, "structured_kap"
    pdf = parse_official_date(pdf_xmp_date)
    if pdf:
        return pdf, SEMANTIC_DOCUMENT_VERSION_DATE, "pdf_xmp"
    _ = filename_period(filename)
    return None, None, "unresolved"


def calculated_on(calculated_at: Any) -> Optional[date]:
    if calculated_at is None:
        return None
    if isinstance(calculated_at, date) and not isinstance(calculated_at, datetime):
        return calculated_at
    return as_date(calculated_at)


def assert_current_evidence_date(
    value: Any,
    *,
    calculated_at: Any,
    semantic: str,
    field: str,
) -> Optional[str]:
    """Reject future publication/source_as_of. Future EFFECTIVE_AT is allowed separately."""
    parsed = parse_official_date(value)
    if parsed is None:
        return None
    if semantic == SEMANTIC_REPORT_PERIOD:
        return parsed
    if semantic == SEMANTIC_EFFECTIVE_AT:
        return parsed
    if semantic not in CURRENT_EVIDENCE_SEMANTICS:
        day = as_date(parsed)
        calc = calculated_on(calculated_at)
        if day is not None and calc is not None and day > calc:
            return None
        return parsed
    day = as_date(parsed)
    calc = calculated_on(calculated_at)
    if day is not None and calc is not None and day > calc:
        raise FutureSourceDateError(f"future_{semantic.lower()}:{field}:{parsed}")
    return parsed


def date_entry(
    value: Optional[str],
    *,
    semantic: str,
    published_at: Optional[str] = None,
    effective_at: Optional[str] = None,
) -> dict[str, str]:
    payload: dict[str, str] = {"value": value or "", "semantic": semantic}
    if not payload["value"]:
        return {}
    if published_at:
        payload["published_at"] = published_at
    if effective_at:
        payload["effective_at"] = effective_at
    return payload


def source_as_of_bundle(
    *,
    tefas_price: Optional[str],
    kap_pdr: Optional[str],
    kap_mandate: Optional[str],
    kap_izahname: Optional[str],
    kap_pdr_published_at: Optional[str] = None,
    kap_mandate_effective_at: Optional[str] = None,
    calculated_at: Optional[str] = None,
) -> dict[str, Any]:
    pdr_period = str(kap_pdr or "") or None
    rejected: list[dict[str, str]] = []

    def _current(value: Optional[str], *, semantic: str, field: str) -> Optional[str]:
        if not value:
            return None
        try:
            return assert_current_evidence_date(
                value, calculated_at=calculated_at, semantic=semantic, field=field
            )
        except FutureSourceDateError as exc:
            rejected.append({"field": field, "value": str(value), "reason": str(exc)})
            return None

    tefas = _current(tefas_price, semantic=SEMANTIC_SOURCE_AS_OF, field="tefas_price")
    mandate = _current(kap_mandate, semantic=SEMANTIC_PUBLISHED_AT, field="kap_mandate")
    izahname = str(kap_izahname or "") or None
    pdr_published = _current(
        kap_pdr_published_at, semantic=SEMANTIC_PUBLISHED_AT, field="kap_pdr_published_at"
    )
    effective = parse_official_date(kap_mandate_effective_at) if kap_mandate_effective_at else None
    model = {}
    tefas_row = date_entry(tefas, semantic=SEMANTIC_SOURCE_AS_OF)
    if tefas_row:
        model["tefas_price"] = tefas_row
    pdr_row = date_entry(pdr_period, semantic=SEMANTIC_REPORT_PERIOD, published_at=pdr_published)
    if pdr_row:
        model["kap_pdr"] = pdr_row
    mandate_row = date_entry(mandate, semantic=SEMANTIC_PUBLISHED_AT, effective_at=effective)
    if mandate_row:
        model["kap_mandate"] = mandate_row
    izahname_row = date_entry(izahname, semantic=SEMANTIC_DOCUMENT_VERSION_DATE)
    if izahname_row:
        model["kap_izahname"] = izahname_row
    payload: dict[str, Any] = {
        "tefas_price": tefas,
        "kap_pdr": pdr_period,
        "kap_mandate": mandate,
        "kap_izahname": izahname,
        "date_model": model,
    }
    if rejected:
        payload["rejected"] = rejected
    return payload


def layer_idempotency_dates(layer: str, source_as_of: Mapping[str, Any]) -> dict[str, Optional[str]]:
    fields = _LAYER_DATE_FIELDS.get(layer, ())
    return {key: source_as_of.get(key) for key in fields}


def source_value(source_as_of: Mapping[str, Any], key: str) -> Optional[str]:
    value = source_as_of.get(key)
    if isinstance(value, Mapping):
        return str(value.get("value") or "") or None
    return str(value) if value else None
