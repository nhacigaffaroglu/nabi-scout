from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.freshness_engine import evaluate_freshness, period_age_days


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def calculate_confidence(
    *,
    data_completeness: Optional[float],
    annual_periods_found: Optional[int],
    endpoint_errors: List[str] | None,
    score_penalty: Optional[float],
    financial_period_end: Optional[str],
    period_age_days_value: Optional[int] = None,
) -> Dict[str, Any]:
    completeness = float(data_completeness or 0)
    periods = int(annual_periods_found or 0)
    errors = endpoint_errors or []
    penalty = float(score_penalty or 0)
    age_days = (
        period_age_days_value
        if period_age_days_value is not None
        else period_age_days(financial_period_end)
    )
    freshness = evaluate_freshness(age_days)

    score = completeness * 0.72
    score += min(periods, 5) / 5 * 18
    score += 10 if not errors else max(0, 10 - len(errors) * 3)
    score -= min(penalty, 20) * 0.25
    score += freshness["confidence_adjustment"]

    confidence = round(clamp(score), 1)

    if confidence >= 85:
        level = "YÜKSEK"
        explanation = (
            "Finansal veri kapsamı ve dönem geçmişi güçlü; sonuca güven yüksek."
        )
    elif confidence >= 65:
        level = "ORTA"
        explanation = (
            "Analiz kullanılabilir seviyede ancak bazı metrikler veya dönemler eksik."
        )
    else:
        level = "DÜŞÜK"
        explanation = (
            "Eksik veri nedeniyle sonuç yalnızca ön eleme amacıyla kullanılmalı."
        )

    reasons = []
    if completeness < 65:
        reasons.append("Veri tamlığı düşük.")
    if periods < 3:
        reasons.append("Uzun dönem geçmişi sınırlı.")
    if errors:
        reasons.append(f"{len(errors)} veri kaynağı/alan sorunu var.")
    if not financial_period_end:
        reasons.append("Finansal dönem tarihi doğrulanamadı.")
    if freshness["freshness_status"] == "AGING":
        reasons.append(f"Finansal dönem {age_days} gün önce kapandı.")
    elif freshness["freshness_status"] == "STALE":
        reasons.append(
            f"Finansal dönem çok eski ({age_days} gün); güncel karar için yetersiz."
        )
    elif freshness["freshness_status"] == "UNKNOWN":
        reasons.append("Finansal dönem yaşı doğrulanamadı.")

    if freshness["freshness_status"] in {"AGING", "STALE", "UNKNOWN"}:
        explanation = (
            f"{explanation} {freshness['freshness_label']}."
        )

    return {
        "research_confidence": confidence,
        "research_confidence_level": level,
        "research_confidence_explanation": explanation,
        "research_confidence_reasons": reasons,
        "period_age_days": age_days,
        "freshness_status": freshness["freshness_status"],
        "freshness_score": freshness["freshness_score"],
        "freshness_label": freshness["freshness_label"],
    }
