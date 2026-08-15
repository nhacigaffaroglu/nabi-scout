from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional, Tuple

from services.company_intelligence_utils import safe_float

ALIGNMENT_ALIGNED = "ALIGNED"
ALIGNMENT_ACCEPTABLE_LAG = "ACCEPTABLE_LAG"
ALIGNMENT_STALE = "STALE"
ALIGNMENT_MIXED_PERIOD = "MIXED_PERIOD"
ALIGNMENT_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# Hybrid annual fundamentals + current market cap: reject when lag exceeds this.
MAX_FUNDAMENTAL_TO_MARKET_LAG_DAYS = 400
# MEDIUM confidence only when lag is within this window.
MEDIUM_CONFIDENCE_MAX_LAG_DAYS = 200


@dataclass(frozen=True)
class ValuationAlignmentAssessment:
    status: str
    fundamental_period_end: str
    market_data_as_of: str
    lag_days: int
    confidence: str
    limitations: Tuple[str, ...]
    balance_sheet_period_end: Optional[str] = None
    ev_components_period_aligned: bool = False


def _parse_iso_date(value: str) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def resolve_fundamental_period_end(sec_financials: Mapping[str, Any]) -> Optional[str]:
    raw = sec_financials.get("financial_period_end")
    if raw in (None, ""):
        return None
    return str(raw)[:10]


def resolve_balance_sheet_period_end(sec_financials: Mapping[str, Any]) -> Optional[str]:
    raw = sec_financials.get("balance_sheet_period_end") or sec_financials.get(
        "financial_period_end",
    )
    if raw in (None, ""):
        return None
    return str(raw)[:10]


def ev_balance_sheet_aligned(sec_financials: Mapping[str, Any]) -> bool:
    fundamental = resolve_fundamental_period_end(sec_financials)
    balance_sheet = resolve_balance_sheet_period_end(sec_financials)
    if not fundamental or not balance_sheet:
        return False
    return fundamental == balance_sheet


def assess_sec_market_hybrid_alignment(
    sec_financials: Mapping[str, Any],
    *,
    market_cap: Optional[float],
    retrieved_at: str,
) -> Optional[ValuationAlignmentAssessment]:
    fundamental_period_end = resolve_fundamental_period_end(sec_financials)
    if not fundamental_period_end:
        return None

    market_data_as_of = str(retrieved_at or "").strip()
    if len(market_data_as_of) < 10:
        return None
    market_date = _parse_iso_date(market_data_as_of)
    fiscal_end = _parse_iso_date(fundamental_period_end)
    if market_date is None or fiscal_end is None:
        return None

    if market_cap is None or market_cap <= 0:
        return None

    lag_days = (market_date - fiscal_end).days
    if lag_days < 0:
        return None

    balance_sheet_period_end = resolve_balance_sheet_period_end(sec_financials)
    ev_aligned = ev_balance_sheet_aligned(sec_financials)

    limitations = (
        f"SEC yıllık finansal dönem {fundamental_period_end} ile "
        f"{market_data_as_of[:10]} piyasa değeri birleştirildi; "
        "TTM/çeyreklik değerleme değildir.",
    )

    if lag_days > MAX_FUNDAMENTAL_TO_MARKET_LAG_DAYS:
        return ValuationAlignmentAssessment(
            status=ALIGNMENT_STALE,
            fundamental_period_end=fundamental_period_end,
            market_data_as_of=market_data_as_of[:10],
            lag_days=lag_days,
            confidence="LOW",
            limitations=limitations + (f"Piyasa verisi finansal dönemden {lag_days} gün sonra.",),
            balance_sheet_period_end=balance_sheet_period_end,
            ev_components_period_aligned=ev_aligned,
        )

    confidence = "MEDIUM" if lag_days <= MEDIUM_CONFIDENCE_MAX_LAG_DAYS else "LOW"
    if lag_days > MEDIUM_CONFIDENCE_MAX_LAG_DAYS:
        limitations = limitations + (
            f"Finansal dönem ile piyasa verisi arasında {lag_days} gün fark var.",
        )

    status = ALIGNMENT_ACCEPTABLE_LAG
    if lag_days == 0:
        status = ALIGNMENT_ALIGNED

    return ValuationAlignmentAssessment(
        status=status,
        fundamental_period_end=fundamental_period_end,
        market_data_as_of=market_data_as_of[:10],
        lag_days=lag_days,
        confidence=confidence,
        limitations=limitations,
        balance_sheet_period_end=balance_sheet_period_end,
        ev_components_period_aligned=ev_aligned,
    )


def alignment_allows_hybrid_valuation(
    assessment: Optional[ValuationAlignmentAssessment],
) -> bool:
    if assessment is None:
        return False
    return assessment.status in {ALIGNMENT_ALIGNED, ALIGNMENT_ACCEPTABLE_LAG}


def safe_positive_ratio(
    numerator: Optional[float],
    denominator: Optional[float],
) -> Optional[float]:
    num = safe_float(numerator)
    den = safe_float(denominator)
    if num is None or den is None or den <= 0:
        return None
    return num / den
