"""Map explicit BIST business codes and derive compatible revenue shares.

No name/headline guessing. No Participation verdicts. No annualization.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from services.bist_business_contract import (
    BistBusinessBundle,
    BistBusinessSegmentFact,
    BistRawBusinessSegment,
    BistRawBusinessTotals,
    CANONICAL_BUSINESS_CATEGORIES,
    CATEGORY_UNKNOWN,
    READINESS_COMPLETE,
    READINESS_NONE,
    READINESS_PARTIAL,
)


# Test-only explicit codes. Not official KAP taxonomy. Not label inference.
BIST_BUSINESS_CODE_MAP = {
    "NABI_TEST.BIZ.ELECTRONICS": "technology",
    "NABI_TEST.BIZ.SERVICES": "general_services",
    "NABI_TEST.BIZ.RETAIL": "general_product",
    "NABI_TEST.BIZ.ALCOHOL": "alcohol",
    "NABI_TEST.BIZ.GAMBLING": "gambling",
}

SHARE_MISSING_TOTAL = "MISSING_TOTAL_REVENUE"
SHARE_ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
SHARE_PERIOD_MISMATCH = "PERIOD_MISMATCH"
SHARE_CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
SHARE_MISSING_SEGMENT_REVENUE = "MISSING_SEGMENT_REVENUE"


def _text(raw: object) -> str:
    return str(raw or "").strip()


def _finite(raw: object) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return value


def map_business_code(segment_code: object) -> Optional[str]:
    code = _text(segment_code).upper()
    if not code:
        return None
    category = BIST_BUSINESS_CODE_MAP.get(code)
    if category is None or category not in CANONICAL_BUSINESS_CATEGORIES:
        return None
    return category


def derive_revenue_share(
    *,
    segment_revenue: Optional[float],
    total_revenue: Optional[float],
    segment_period: str,
    total_period: str,
    segment_currency: str,
    total_currency: str,
) -> tuple[Optional[float], str]:
    if segment_revenue is None:
        return None, SHARE_MISSING_SEGMENT_REVENUE
    if total_revenue is None:
        return None, SHARE_MISSING_TOTAL
    if total_revenue == 0:
        return None, SHARE_ZERO_DENOMINATOR
    if _text(segment_period).upper() != _text(total_period).upper() or not _text(total_period):
        return None, SHARE_PERIOD_MISMATCH
    if _text(segment_currency).upper() != _text(total_currency).upper() or not _text(total_currency):
        return None, SHARE_CURRENCY_MISMATCH
    return segment_revenue / total_revenue * 100.0, ""


def normalize_business_segment(
    segment: BistRawBusinessSegment,
    totals: Optional[BistRawBusinessTotals],
) -> BistBusinessSegmentFact:
    mapped = map_business_code(segment.segment_code)
    category = mapped or CATEGORY_UNKNOWN
    rule = "EXPLICIT_CODE_MAP" if mapped else "UNKNOWN_UNMAPPED_CODE"
    total_revenue = _finite(totals.total_revenue) if totals is not None else None
    share, limitation = derive_revenue_share(
        segment_revenue=_finite(segment.revenue),
        total_revenue=total_revenue,
        segment_period=segment.period,
        total_period=totals.period if totals is not None else "",
        segment_currency=segment.currency,
        total_currency=totals.currency if totals is not None else "",
    )
    return BistBusinessSegmentFact(
        symbol=_text(segment.symbol).upper(),
        issuer_id=_text(segment.issuer_id) or None,
        segment_code=_text(segment.segment_code).upper() or None,
        segment_name=segment.segment_name,
        raw_category=_text(segment.raw_category),
        canonical_category=category,
        mapping_rule=rule,
        revenue=_finite(segment.revenue),
        revenue_share=share,
        share_limitation=limitation,
        currency=_text(segment.currency).upper(),
        period=_text(segment.period).upper(),
        source=segment.source,
        source_document_id=segment.source_document_id,
        as_of=segment.as_of or segment.period_end,
        provenance=dict(segment.provenance or {}),
    )


def _readiness(facts: Sequence[BistBusinessSegmentFact]) -> tuple[str, str]:
    if not facts:
        return READINESS_NONE, "NO_BUSINESS_SEGMENTS"
    unknown = any(item.canonical_category == CATEGORY_UNKNOWN for item in facts)
    missing_share = any(item.revenue_share is None for item in facts)
    if unknown or missing_share:
        return READINESS_PARTIAL, "PARTIAL_OR_UNKNOWN_EVIDENCE"
    return READINESS_COMPLETE, ""


def normalize_bist_business(
    *,
    symbol: str,
    identity_source: str,
    segments: Iterable[BistRawBusinessSegment],
    totals: Optional[BistRawBusinessTotals],
) -> BistBusinessBundle:
    facts = tuple(normalize_business_segment(item, totals) for item in segments)
    unknown_rev = 0.0
    mapped_share_total = 0.0
    unknown_share_total = 0.0
    has_unknown_rev = False
    has_mapped_share = False
    has_unknown_share = False
    for item in facts:
        if item.canonical_category == CATEGORY_UNKNOWN and item.revenue is not None:
            unknown_rev += item.revenue
            has_unknown_rev = True
        if item.revenue_share is None:
            continue
        if item.canonical_category == CATEGORY_UNKNOWN:
            unknown_share_total += item.revenue_share
            has_unknown_share = True
        else:
            mapped_share_total += item.revenue_share
            has_mapped_share = True
    readiness, limitation = _readiness(facts)
    return BistBusinessBundle(
        symbol=_text(symbol).upper(),
        identity_source=identity_source,
        segments=facts,
        total_revenue=_finite(totals.total_revenue) if totals is not None else None,
        total_currency=_text(totals.currency).upper() if totals is not None else "",
        total_period=_text(totals.period).upper() if totals is not None else "",
        unknown_revenue=unknown_rev if has_unknown_rev else None,
        unknown_share=unknown_share_total if has_unknown_share else None,
        mapped_share=mapped_share_total if has_mapped_share else None,
        readiness=readiness,
        limitation=limitation,
        source=totals.source if totals is not None else (facts[0].source if facts else ""),
        source_document_id=totals.source_document_id
        if totals is not None
        else (facts[0].source_document_id if facts else None),
        as_of=totals.as_of if totals is not None else (facts[0].as_of if facts else None),
    )
