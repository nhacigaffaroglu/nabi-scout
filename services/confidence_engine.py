from __future__ import annotations

from typing import Any, Dict, List, Optional


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def calculate_confidence(
    *,
    data_completeness: Optional[float],
    annual_periods_found: Optional[int],
    endpoint_errors: List[str] | None,
    score_penalty: Optional[float],
    financial_period_end: Optional[str],
) -> Dict[str, Any]:
    completeness = float(data_completeness or 0)
    periods = int(annual_periods_found or 0)
    errors = endpoint_errors or []
    penalty = float(score_penalty or 0)

    score = completeness * 0.72
    score += min(periods, 5) / 5 * 18
    score += 10 if not errors else max(0, 10 - len(errors) * 3)
    score -= min(penalty, 20) * 0.25

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

    return {
        "research_confidence": confidence,
        "research_confidence_level": level,
        "research_confidence_explanation": explanation,
        "research_confidence_reasons": reasons,
    }
