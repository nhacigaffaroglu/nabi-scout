"""Extract official KAP business-segment / revenue-composition evidence.

Uses observed taxonomy IDs and official note tables. Does not classify
Participation. Does not invent share from prose.
"""

from __future__ import annotations

import re
from typing import Optional

from services.kap_financial_contract import EXPLICIT_UNIT_SCALES, PERIOD_Q, PERIOD_YTD
from services.kap_public_business_contract import (
    BREAKDOWN_GEOGRAPHICAL,
    BREAKDOWN_OPERATING_SEGMENT,
    BREAKDOWN_SINGLE_SEGMENT,
    NON_SEGMENT_TEMPLATE_CONCEPTS,
    SEGMENT_TAXONOMY_SEARCH_TOKENS,
    SOURCE_PUBLIC_KAP_BUSINESS,
    SOURCE_TYPE_OFFICIAL_PDF_NOTES,
    STRUCTURED_SEGMENT_NO,
    STRUCTURED_SEGMENT_YES,
    KapPublicBusinessDocument,
    KapPublicSegmentEvidence,
)
from services.kap_public_contract import KAP_PUBLIC_HOST


_WS_RE = re.compile(r"\s+")
_CONCEPT_RE = re.compile(r"(?i)((?:ifrs-full|kap-fr)_[A-Za-z0-9]+)")
_TR_NUMBER_RE = re.compile(r"\(?\d{1,3}(?:\.\d{3})+(?:,\d+)?\)?|\(?\d+(?:,\d+)?\)?")
_YTD_HEADER_RE = re.compile(
    r"1\s*Ocak[- ]+\s*30\s*Haziran\s+(\d{4})\s+(.+?)\s+Konsolide\s+Toplam",
    re.IGNORECASE,
)
_HASILAT_LINE_RE = re.compile(
    r"(?im)^\s*Has[ıi]lat[ \t]+([0-9.(), \t]+)"
)
_GEO_DOMESTIC_RE = re.compile(
    r"Yurt\s+i[cç]i\s+sat[ıi][sş]lar\s+(" + _TR_NUMBER_RE.pattern + r")",
    re.IGNORECASE,
)
_GEO_FOREIGN_RE = re.compile(
    r"Yurt\s+d[ıi][sş][ıi]\s+sat[ıi][sş]lar\s+(" + _TR_NUMBER_RE.pattern + r")",
    re.IGNORECASE,
)
_SINGLE_SEGMENT_RE = re.compile(
    r"tek bir raporlanabilecek faaliyet b[öo]l[üu]m[üu]",
    re.IGNORECASE,
)
_INCOME_HASILAT_RE = re.compile(
    r"(?i)Has[ıi]lat\s+\d+\s+(\d{1,3}(?:\.\d{3})+)"
)
_BIN_TL_RE = re.compile(r"Bin T[uü]rk Liras|1\.000 TL|bin T[uü]rk Liras", re.IGNORECASE)


def _text(raw: object) -> str:
    return _WS_RE.sub(" ", str(raw or "")).strip()


def _finite_tr(raw: object) -> Optional[float]:
    text = _text(raw).replace(" ", "")
    if not text or text in {"-", "—"}:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    text = text.replace(".", "").replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return value


def _numbers(line: str) -> tuple[float, ...]:
    found: list[float] = []
    for token in _TR_NUMBER_RE.findall(line):
        value = _finite_tr(token)
        if value is not None:
            found.append(value)
    return tuple(found)


def observed_taxonomy_ids(html: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_CONCEPT_RE.findall(html or "")))


def observed_segment_taxonomy(html: str) -> tuple[str, ...]:
    """Record exact IDs that look like operating-segment taxonomy. No mapping."""
    found: list[str] = []
    for concept in observed_taxonomy_ids(html):
        lower = concept.lower()
        if "segment" in lower or any(
            token.lower() in lower for token in SEGMENT_TAXONOMY_SEARCH_TOKENS
        ):
            found.append(concept)
    return tuple(dict.fromkeys(found))


def observed_non_segment_template(html: str) -> tuple[str, ...]:
    present = set(observed_taxonomy_ids(html))
    return tuple(item for item in NON_SEGMENT_TEMPLATE_CONCEPTS if item in present)


def _unit_from_text(text: str) -> tuple[str, Optional[int]]:
    if _BIN_TL_RE.search(text or ""):
        return "1.000 TL", EXPLICIT_UNIT_SCALES["1.000 TL"]
    return "", None


def _segment(
    *,
    symbol: str,
    name: str,
    raw_revenue: Optional[float],
    currency: str,
    period: str,
    period_end: Optional[str],
    period_start: Optional[str],
    unit_scale: Optional[int],
    unit_label: str,
    breakdown_kind: str,
    location: str,
    disclosure_id: str,
    source_url: str,
    activity_description: str = "",
) -> KapPublicSegmentEvidence:
    return KapPublicSegmentEvidence(
        symbol=symbol.upper(),
        segment_name=name,
        raw_revenue=raw_revenue,
        unit_scale=unit_scale,
        unit_label=unit_label,
        currency=currency,
        period=period,
        period_start=period_start,
        period_end=period_end,
        source=SOURCE_PUBLIC_KAP_BUSINESS,
        source_document_id=disclosure_id,
        source_url=source_url,
        breakdown_kind=breakdown_kind,
        location=location,
        activity_description=activity_description,
        provenance={
            "source": SOURCE_PUBLIC_KAP_BUSINESS,
            "breakdown_kind": breakdown_kind,
            "location": location,
        },
    )


def _extract_operating_ytd(
    text: str,
    *,
    symbol: str,
    disclosure_id: str,
    source_url: str,
    currency: str,
    unit_label: str,
    unit_scale: Optional[int],
) -> tuple[tuple[KapPublicSegmentEvidence, ...], Optional[float]]:
    header = _YTD_HEADER_RE.search(text)
    if header is None:
        return (), None
    year = header.group(1)
    names = [part for part in _text(header.group(2)).split() if part]
    # First Hasılat line after this header is the YTD table, not the Q table.
    tail = text[header.end() :]
    hasilat = _HASILAT_LINE_RE.search(tail)
    if hasilat is None:
        return (), None
    values = _numbers(hasilat.group(0))
    if len(values) < 2 or len(names) + 1 != len(values):
        return (), None
    *segment_values, total = values
    period_end = f"{year}-06-30"
    period_start = f"{year}-01-01"
    segments = tuple(
        _segment(
            symbol=symbol,
            name=name,
            raw_revenue=value,
            currency=currency,
            period=PERIOD_YTD,
            period_end=period_end,
            period_start=period_start,
            unit_scale=unit_scale,
            unit_label=unit_label,
            breakdown_kind=BREAKDOWN_OPERATING_SEGMENT,
            location="official note: Bölümlere göre raporlama / Hasılat YTD",
            disclosure_id=disclosure_id,
            source_url=source_url,
        )
        for name, value in zip(names, segment_values)
    )
    return segments, total


def _extract_geographic(
    text: str,
    *,
    symbol: str,
    disclosure_id: str,
    source_url: str,
    currency: str,
    unit_label: str,
    unit_scale: Optional[int],
    period: str,
    period_end: Optional[str],
    period_start: Optional[str],
) -> tuple[tuple[KapPublicSegmentEvidence, ...], Optional[float]]:
    domestic = _GEO_DOMESTIC_RE.search(text)
    foreign = _GEO_FOREIGN_RE.search(text)
    if domestic is None or foreign is None:
        return (), None
    domestic_v = _finite_tr(domestic.group(1))
    foreign_v = _finite_tr(foreign.group(1))
    if domestic_v is None or foreign_v is None:
        return (), None
    total = domestic_v + foreign_v
    location = "official note: Hasılat / yurt içi-yurt dışı"
    return (
        (
            _segment(
                symbol=symbol,
                name="Yurt içi satışlar",
                raw_revenue=domestic_v,
                currency=currency,
                period=period,
                period_end=period_end,
                period_start=period_start,
                unit_scale=unit_scale,
                unit_label=unit_label,
                breakdown_kind=BREAKDOWN_GEOGRAPHICAL,
                location=location,
                disclosure_id=disclosure_id,
                source_url=source_url,
            ),
            _segment(
                symbol=symbol,
                name="Yurt dışı satışlar",
                raw_revenue=foreign_v,
                currency=currency,
                period=period,
                period_end=period_end,
                period_start=period_start,
                unit_scale=unit_scale,
                unit_label=unit_label,
                breakdown_kind=BREAKDOWN_GEOGRAPHICAL,
                location=location,
                disclosure_id=disclosure_id,
                source_url=source_url,
            ),
        ),
        total,
    )


def _extract_single_segment(
    text: str,
    *,
    symbol: str,
    disclosure_id: str,
    source_url: str,
    currency: str,
    unit_label: str,
    unit_scale: Optional[int],
    period: str,
    period_end: Optional[str],
    period_start: Optional[str],
) -> tuple[tuple[KapPublicSegmentEvidence, ...], Optional[float]]:
    if _SINGLE_SEGMENT_RE.search(text) is None:
        return (), None
    match = _INCOME_HASILAT_RE.search(text)
    total = _finite_tr(match.group(1)) if match else None
    return (
        (
            _segment(
                symbol=symbol,
                name="Tek raporlanabilir faaliyet bölümü",
                raw_revenue=total,
                currency=currency,
                period=period,
                period_end=period_end,
                period_start=period_start,
                unit_scale=unit_scale,
                unit_label=unit_label,
                breakdown_kind=BREAKDOWN_SINGLE_SEGMENT,
                location="official note: Bölümlere Göre Raporlama",
                disclosure_id=disclosure_id,
                source_url=source_url,
                activity_description=(
                    "Official TFRS 8 statement: single reportable operating "
                    "segment; financials not reported by operating segment."
                ),
            ),
        ),
        total,
    )


def parse_official_business_notes(
    text: str,
    *,
    symbol: str,
    disclosure_id: str,
    source_url: str = "",
    html: str = "",
    cached: bool = False,
    period: str = PERIOD_YTD,
    period_end: Optional[str] = None,
    period_start: Optional[str] = None,
) -> KapPublicBusinessDocument:
    """Parse official note text. Taxonomy HTML is inspected, not classified."""
    unit_label, unit_scale = _unit_from_text(text)
    currency = "TRY" if unit_label else ""
    taxonomy = observed_segment_taxonomy(html)
    operating, operating_total = _extract_operating_ytd(
        text,
        symbol=symbol,
        disclosure_id=disclosure_id,
        source_url=source_url,
        currency=currency or "TRY",
        unit_label=unit_label,
        unit_scale=unit_scale,
    )
    if operating:
        segments, total = operating, operating_total
        limitation = ""
        period_end = period_end or segments[0].period_end
        period_start = period_start or segments[0].period_start
        period = PERIOD_YTD
    else:
        geographic, geo_total = _extract_geographic(
            text,
            symbol=symbol,
            disclosure_id=disclosure_id,
            source_url=source_url,
            currency=currency or "TRY",
            unit_label=unit_label,
            unit_scale=unit_scale,
            period=period,
            period_end=period_end,
            period_start=period_start,
        )
        if geographic:
            segments, total = geographic, geo_total
            limitation = "GEOGRAPHICAL_REVENUE_NOT_OPERATING_SEGMENT"
        else:
            single, single_total = _extract_single_segment(
                text,
                symbol=symbol,
                disclosure_id=disclosure_id,
                source_url=source_url,
                currency=currency or "TRY",
                unit_label=unit_label,
                unit_scale=unit_scale,
                period=period,
                period_end=period_end,
                period_start=period_start,
            )
            segments, total = single, single_total
            limitation = "SINGLE_REPORTABLE_SEGMENT" if single else "NO_OFFICIAL_SEGMENT_TABLE"
    return KapPublicBusinessDocument(
        symbol=symbol.upper(),
        disclosure_id=str(disclosure_id),
        source_url=source_url or f"{KAP_PUBLIC_HOST}/tr/Bildirim/{disclosure_id}",
        source_type=SOURCE_TYPE_OFFICIAL_PDF_NOTES,
        period=period,
        period_end=period_end,
        currency=currency or "TRY",
        unit_label=unit_label,
        unit_scale=unit_scale,
        structured_segment_taxonomy=STRUCTURED_SEGMENT_YES if taxonomy else STRUCTURED_SEGMENT_NO,
        observed_taxonomy=taxonomy,
        narrative_fallback_used=not bool(taxonomy),
        official_total_revenue=total,
        segments=segments,
        limitation=limitation,
        cached=cached,
        provenance={
            "parser": "kap_public_business_parser",
            "non_segment_template": list(observed_non_segment_template(html)),
            "quarter_tables_ignored": PERIOD_Q,
        },
    )
