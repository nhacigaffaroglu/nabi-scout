"""Read-only discovery of public KAP annual financial-report notifications.

Parses official KAP bildirim-sorgu-sonuc HTML (embedded disclosureBasic
JSON and/or checkbox rows). Does not hardcode notification IDs.
Does not fetch paid KAP APIs.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Optional

from services.kap_financial_contract import PERIOD_FY, PERIOD_Q, PERIOD_YTD
from services.kap_financial_normalization import normalize_reporting_period
from services.kap_public_contract import (
    PERIOD_LABEL_3M,
    PERIOD_LABEL_6M,
    PERIOD_LABEL_9M,
    PERIOD_LABEL_ANNUAL,
    TITLE_FINANCIAL_REPORT,
    KapFrDiscovery,
    public_bildirim_url,
)

# Official KAP Detaylı Sorgulama / disclosureBasic period codes.
PERIOD_CODE_Q = "1"
PERIOD_CODE_6M = "2"
PERIOD_CODE_9M = "3"
PERIOD_CODE_FY = "4"
PERIOD_CODE_LABELS = {
    PERIOD_CODE_Q: PERIOD_LABEL_3M,
    PERIOD_CODE_6M: PERIOD_LABEL_6M,
    PERIOD_CODE_9M: PERIOD_LABEL_9M,
    PERIOD_CODE_FY: PERIOD_LABEL_ANNUAL,
}


_WS_RE = re.compile(r"\s+")
_DISCLOSURE_BASIC_RE = re.compile(
    r'\{\s*"disclosureBasic"\s*:\s*\{(?P<body>(?:[^{}]|\{[^{}]*\})*)\}',
    re.DOTALL,
)
_CHECKBOX_ROW_RE = re.compile(
    r'<input[^>]*\sid="(\d+)"[^>]*>.{0,800}?(?:Finansal Rapor).{0,400}?(20\d{2}).{0,120}?(Yıllık|\d+\s*Aylık)',
    re.IGNORECASE | re.DOTALL,
)


def _text(raw: object) -> str:
    return _WS_RE.sub(" ", str(raw or "")).strip()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _json_field(chunk: str, name: str) -> str:
    match = re.search(
        rf'"{re.escape(name)}"\s*:\s*(?:"((?:\\.|[^"\\])*)"|([^,}}\s]+))',
        chunk,
    )
    if not match:
        return ""
    raw = match.group(1) if match.group(1) is not None else (match.group(2) or "")
    return raw.replace(r"\"", '"').strip()


def classify_kap_period_label(label: object) -> str:
    text = _text(label)
    if text in PERIOD_CODE_LABELS:
        text = PERIOD_CODE_LABELS[text]
    folded = text.casefold()
    if text in {PERIOD_LABEL_ANNUAL, "Yillik"} or folded in {"annual", "yearly"}:
        return PERIOD_FY
    if PERIOD_LABEL_3M.casefold() in folded or folded in {"q", "quarter"}:
        return PERIOD_Q
    if PERIOD_LABEL_6M.casefold() in folded or PERIOD_LABEL_9M.casefold() in folded:
        return PERIOD_YTD
    return normalize_reporting_period(text)


def is_annual_financial_report(row: KapFrDiscovery) -> bool:
    return (
        row.title == TITLE_FINANCIAL_REPORT
        and row.disclosure_class == "FR"
        and row.period == PERIOD_FY
    )


def _iso_submission(raw: str) -> str:
    text = _text(raw)
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return text[:10]


def _from_json_chunk(chunk: str, notification_id: str, *, observed_at: str) -> Optional[KapFrDiscovery]:
    title = _json_field(chunk, "title")
    if title != TITLE_FINANCIAL_REPORT:
        return None
    klass = _json_field(chunk, "disclosureClass") or "FR"
    if klass != "FR":
        return None
    period_label = _json_field(chunk, "donem") or _json_field(chunk, "period")
    year = _json_field(chunk, "year")
    symbol = _json_field(chunk, "stockCode").upper()
    submitted = _iso_submission(_json_field(chunk, "publishDate"))
    period = classify_kap_period_label(period_label)
    return KapFrDiscovery(
        symbol=symbol,
        notification_id=str(notification_id),
        submission_date=submitted,
        year=year,
        period=period,
        period_label=_text(period_label) or period,
        title=title,
        source_url=public_bildirim_url(notification_id),
        disclosure_class=klass,
        observed_at=observed_at,
    )


def _from_checkbox_chunk(
    chunk: str,
    notification_id: str,
    *,
    observed_at: str,
    year: str = "",
    period_label: str = "",
) -> Optional[KapFrDiscovery]:
    if "Faaliyet Raporu" in chunk and TITLE_FINANCIAL_REPORT not in chunk:
        return None
    title_match = re.search(r">\s*(Finansal Rapor)\s*<", chunk)
    if not title_match and TITLE_FINANCIAL_REPORT not in chunk:
        return None
    if "Sorumluluk Beyanı" in chunk and TITLE_FINANCIAL_REPORT not in chunk:
        return None
    symbol_match = re.search(r">\s*([A-Z]{3,6})\s*<", chunk)
    year_match = re.search(r">\s*(20\d{2})\s*<", chunk)
    period_match = re.search(r"(Yıllık|\d+\s*Aylık)", chunk, re.IGNORECASE)
    date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", chunk)
    period_label = period_label or (period_match.group(1) if period_match else "")
    year = (year_match.group(1) if year_match else "") or year
    return KapFrDiscovery(
        symbol=(symbol_match.group(1) if symbol_match else "").upper(),
        notification_id=str(notification_id),
        submission_date=_iso_submission(date_match.group(1) if date_match else ""),
        year=year_match.group(1) if year_match else "",
        period=classify_kap_period_label(period_label),
        period_label=period_label,
        title=TITLE_FINANCIAL_REPORT,
        source_url=public_bildirim_url(notification_id),
        observed_at=observed_at,
    )


def _normalize_search_html(html: str) -> str:
    """KAP search pages embed disclosureBasic JSON inside an escaped JS string."""
    return str(html or "").replace('\\"', '"').replace("\\/", "/")


def _period_label_from_row(row: dict[str, Any]) -> str:
    donem = _text(row.get("donem") or row.get("periodLabel"))
    if donem:
        return donem
    code = _text(row.get("period"))
    return PERIOD_CODE_LABELS.get(code, code)


def _symbol_from_row(row: dict[str, Any]) -> str:
    for key in ("stockCode", "stockCodes", "relatedStocks"):
        text = _text(row.get(key)).upper()
        if text and text != "-" and "," not in text:
            return text
        if "," in text:
            return text.split(",")[0].strip()
    return ""


def parse_detailed_search_payload(
    payload: object,
    *,
    observed_at: str = "",
) -> tuple[KapFrDiscovery, ...]:
    """Parse official KAP Detaylı Sorgulama JSON (byCriteria). Not paid VYS."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, list):
        return ()
    observed = observed_at or _today()
    found: dict[str, KapFrDiscovery] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        title = _text(row.get("title") or row.get("subject"))
        if title != TITLE_FINANCIAL_REPORT:
            continue
        klass = _text(row.get("disclosureClass") or "FR") or "FR"
        if klass != "FR":
            continue
        notification_id = _text(row.get("disclosureIndex") or row.get("notification_id"))
        if not notification_id:
            continue
        period_label = _period_label_from_row(row)
        year = _text(row.get("year"))
        found[notification_id] = KapFrDiscovery(
            symbol=_symbol_from_row(row),
            notification_id=notification_id,
            submission_date=_iso_submission(_text(row.get("publishDate"))),
            year=year,
            period=classify_kap_period_label(period_label or _text(row.get("period"))),
            period_label=period_label,
            title=title,
            source_url=public_bildirim_url(notification_id),
            disclosure_class=klass,
            observed_at=observed,
        )
    return tuple(
        found[key]
        for key in sorted(found, key=lambda item: found[item].submission_date, reverse=True)
    )


def parse_fr_disclosure_index(html: str, *, observed_at: str = "") -> tuple[KapFrDiscovery, ...]:
    """Parse official KAP FR search HTML. Checkbox id / disclosureIndex is Bildirim id."""
    observed = observed_at or _today()
    found: dict[str, KapFrDiscovery] = {}
    text = _normalize_search_html(html)
    for match in _DISCLOSURE_BASIC_RE.finditer(text):
        chunk = match.group(0)
        notification_id = _json_field(chunk, "disclosureIndex")
        if not notification_id:
            continue
        row = _from_json_chunk(chunk, notification_id, observed_at=observed)
        if row is not None:
            found[notification_id] = row
    if not found:
        for match in _CHECKBOX_ROW_RE.finditer(text):
            notification_id = match.group(1)
            row = _from_checkbox_chunk(
                match.group(0),
                notification_id,
                observed_at=observed,
                year=match.group(2),
                period_label=match.group(3),
            )
            if row is not None:
                found[notification_id] = row
    return tuple(found[key] for key in sorted(found, key=lambda item: found[item].submission_date, reverse=True))


def annual_fr_discoveries(rows: tuple[KapFrDiscovery, ...]) -> tuple[KapFrDiscovery, ...]:
    return tuple(row for row in rows if is_annual_financial_report(row))


def discoveries_for_years(
    rows: tuple[KapFrDiscovery, ...],
    years: tuple[int, ...],
) -> dict[int, Optional[KapFrDiscovery]]:
    wanted = {int(year) for year in years}
    by_year: dict[int, KapFrDiscovery] = {}
    for row in annual_fr_discoveries(rows):
        if not row.year or int(row.year) not in wanted:
            continue
        year = int(row.year)
        previous = by_year.get(year)
        if previous is None or row.submission_date > previous.submission_date:
            by_year[year] = row
    return {year: by_year.get(year) for year in years}


def discovery_refresh_key(row: KapFrDiscovery) -> tuple[str, str, str, str]:
    return (row.symbol, "FR", row.year, PERIOD_LABEL_ANNUAL)


def discovery_dedup_key(row: KapFrDiscovery) -> tuple[str, str, str]:
    return (row.symbol, row.year, row.notification_id)


def incremental_annual_targets(
    discovered: tuple[KapFrDiscovery, ...],
    known_notification_ids: set[str],
) -> tuple[KapFrDiscovery, ...]:
    """Skip refetch when the annual notification is already known."""
    return tuple(
        row
        for row in annual_fr_discoveries(discovered)
        if row.notification_id not in known_notification_ids
    )
