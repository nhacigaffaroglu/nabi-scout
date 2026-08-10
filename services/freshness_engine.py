from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

# Benchmark-backed bands:
# - US names (AAPL ~317d, NVDA ~197d, ASML ~222d) stay fresh
# - 20-F laggers like TSM (~587d) enter aging without being treated as stale
# - SONY/TM (>1900d) are clearly stale
FRESH_MAX_DAYS = 450
AGING_MAX_DAYS = 900


def period_age_days(
    financial_period_end: Optional[str],
    *,
    as_of: Optional[date] = None,
) -> Optional[int]:
    if not financial_period_end:
        return None

    try:
        period_end = date.fromisoformat(financial_period_end)
    except ValueError:
        return None

    reference = as_of or date.today()
    return (reference - period_end).days


def evaluate_freshness(
    period_age: Optional[int],
) -> Dict[str, Any]:
    if period_age is None:
        return {
            "freshness_status": "UNKNOWN",
            "freshness_score": 0.0,
            "freshness_label": "Finansal dönem doğrulanamadı",
            "confidence_adjustment": -12.0,
        }

    if period_age <= FRESH_MAX_DAYS:
        return {
            "freshness_status": "FRESH",
            "freshness_score": 100.0,
            "freshness_label": "Güncel finansal dönem",
            "confidence_adjustment": 0.0,
        }

    if period_age <= AGING_MAX_DAYS:
        slide = (period_age - FRESH_MAX_DAYS) / (
            AGING_MAX_DAYS - FRESH_MAX_DAYS
        )
        adjustment = -(8 + slide * 12)
        return {
            "freshness_status": "AGING",
            "freshness_score": round(75 - slide * 25, 1),
            "freshness_label": (
                f"Finansal dönem {period_age} gün önce kapandı"
            ),
            "confidence_adjustment": round(adjustment, 1),
        }

    years_beyond = (period_age - AGING_MAX_DAYS) / 365
    adjustment = -(22 + min(28, years_beyond * 12))
    return {
        "freshness_status": "STALE",
        "freshness_score": round(max(5, 35 - min(30, years_beyond * 8)), 1),
        "freshness_label": (
            f"Eski finansal dönem ({period_age} gün)"
        ),
        "confidence_adjustment": round(adjustment, 1),
    }


def derive_score_confidence(
    *,
    data_completeness: Optional[float],
    freshness_status: str,
) -> str:
    completeness = float(data_completeness or 0)

    if freshness_status in {"STALE", "UNKNOWN"}:
        return "DÜŞÜK"
    if freshness_status == "AGING":
        if completeness >= 85:
            return "ORTA"
        if completeness >= 65:
            return "ORTA"
        return "DÜŞÜK"

    if completeness >= 85:
        return "YÜKSEK"
    if completeness >= 65:
        return "ORTA"
    return "DÜŞÜK"
