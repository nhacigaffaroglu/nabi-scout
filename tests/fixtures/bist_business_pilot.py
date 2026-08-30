"""TEST-ONLY synthetic BIST business evidence. Not real issuer operations."""

from __future__ import annotations

from services.bist_business_contract import (
    BIST_BUSINESS_SOURCE_FIXTURE,
    BistRawBusinessSegment,
    BistRawBusinessTotals,
)

FIXTURE_DISCLAIMER = (
    "TEST-ONLY synthetic BIST business evidence. Not real ASELS/BIMAS/TUPRS operations."
)


def _segment(
    symbol: str,
    code: str,
    name: str,
    revenue: float,
    *,
    period: str = "FY",
    currency: str = "TRY",
    raw_category: str = "",
) -> BistRawBusinessSegment:
    return BistRawBusinessSegment(
        symbol=symbol,
        issuer_id=f"TEST-{symbol}",
        segment_code=code,
        segment_name=name,
        raw_category=raw_category,
        revenue=revenue,
        currency=currency,
        period=period,
        period_end="2024-12-31",
        source=BIST_BUSINESS_SOURCE_FIXTURE,
        source_document_id=f"TEST-BIZ-{symbol}",
        as_of="2024-12-31",
        provenance={"fixture": True, "disclaimer": FIXTURE_DISCLAIMER},
    )


def _totals(
    symbol: str,
    total_revenue,
    *,
    period: str = "FY",
    currency: str = "TRY",
) -> BistRawBusinessTotals:
    return BistRawBusinessTotals(
        symbol=symbol,
        total_revenue=total_revenue,
        currency=currency,
        period=period,
        period_end="2024-12-31",
        source=BIST_BUSINESS_SOURCE_FIXTURE,
        source_document_id=f"TEST-BIZ-{symbol}",
        as_of="2024-12-31",
    )


def asels_complete_mapped():
    """Fully mapped synthetic segments. Not a real Aselsan classification."""
    return (
        (
            _segment("ASELS", "NABI_TEST.BIZ.ELECTRONICS", "Fixture electronics", 80.0),
            _segment("ASELS", "NABI_TEST.BIZ.SERVICES", "Fixture services", 20.0),
        ),
        _totals("ASELS", 100.0),
    )


def bimas_mixed_unknown():
    """Known + unknown synthetic segments. Not a real BIM classification."""
    return (
        (
            _segment("BIMAS", "NABI_TEST.BIZ.RETAIL", "Fixture retail", 70.0),
            _segment("BIMAS", "NABI_TEST.BIZ.UNLISTED", "Fixture other", 30.0, raw_category="other"),
        ),
        _totals("BIMAS", 100.0),
    )


def tuprs_period_mismatch():
    """Same-currency segments with incompatible total period."""
    return (
        (
            _segment("TUPRS", "NABI_TEST.BIZ.RETAIL", "Fixture refining label", 50.0, period="FY"),
            _segment("TUPRS", "NABI_TEST.BIZ.SERVICES", "Fixture other label", 50.0, period="FY"),
        ),
        _totals("TUPRS", 100.0, period="YTD"),
    )


def missing_total_revenue_asels():
    segments, _ = asels_complete_mapped()
    return segments, _totals("ASELS", None)


def currency_mismatch_bimas():
    segments, _ = bimas_mixed_unknown()
    return segments, _totals("BIMAS", 100.0, currency="USD")


PILOT_FIXTURES = {
    "ASELS": asels_complete_mapped,
    "BIMAS": bimas_mixed_unknown,
    "TUPRS": tuprs_period_mismatch,
}
