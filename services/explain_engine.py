from __future__ import annotations

from typing import Any, Dict, List, Optional


def _impact(
    value: Optional[float],
    *,
    strong: float,
    weak: float,
    higher_is_better: bool = True,
) -> str:
    if value is None:
        return "unknown"

    if higher_is_better:
        if value >= strong:
            return "positive"
        if value <= weak:
            return "negative"
    else:
        if value <= strong:
            return "positive"
        if value >= weak:
            return "negative"

    return "neutral"


def build_score_explanation(candidate: Dict[str, Any]) -> Dict[str, Any]:
    factors: List[Dict[str, Any]] = []

    definitions = [
        (
            "ROIC",
            candidate.get("roic"),
            _impact(candidate.get("roic"), strong=15, weak=5),
            "Sermaye verimliliği",
            "roic",
        ),
        (
            "Gelir CAGR 3Y",
            candidate.get("revenue_cagr_3y"),
            _impact(candidate.get("revenue_cagr_3y"), strong=10, weak=0),
            "Gelir büyümesinin sürekliliği",
            "revenue_cagr_3y",
        ),
        (
            "EPS CAGR 3Y",
            candidate.get("eps_cagr_3y"),
            _impact(candidate.get("eps_cagr_3y"), strong=12, weak=0),
            "Hisse başına kâr büyümesi",
            "eps_cagr_3y",
        ),
        (
            "FCF Marjı",
            candidate.get("free_cash_flow_margin"),
            _impact(candidate.get("free_cash_flow_margin"), strong=10, weak=0),
            "Satışların nakde dönüşme kalitesi",
            "free_cash_flow_margin",
        ),
        (
            "Borç/Özsermaye",
            candidate.get("debt_to_equity"),
            _impact(
                candidate.get("debt_to_equity"),
                strong=0.8,
                weak=2.0,
                higher_is_better=False,
            ),
            "Finansal kaldıraç",
            "debt_to_equity",
        ),
        (
            "Faiz Karşılama",
            candidate.get("interest_coverage"),
            _impact(candidate.get("interest_coverage"), strong=8, weak=2),
            "Faiz yükünü ödeme kapasitesi",
            "interest_coverage",
        ),
        (
            "EV/EBIT",
            candidate.get("ev_to_ebit"),
            _impact(
                candidate.get("ev_to_ebit"),
                strong=10,
                weak=20,
                higher_is_better=False,
            ),
            "Faaliyet kârına göre değerleme",
            "ev_to_ebit",
        ),
        (
            "Hisse Adedi Değişimi 3Y",
            candidate.get("share_change_3y"),
            _impact(
                candidate.get("share_change_3y"),
                strong=0,
                weak=15,
                higher_is_better=False,
            ),
            "Hisse sulandırması veya geri alım etkisi",
            "share_change_3y",
        ),
    ]

    for label, value, impact, meaning, academy_key in definitions:
        if value is None:
            continue

        direction = {
            "positive": "Puanı destekliyor",
            "negative": "Puanı aşağı çekiyor",
            "neutral": "Nötr etki",
        }[impact]

        factors.append({
            "label": label,
            "value": round(float(value), 2),
            "impact": impact,
            "meaning": meaning,
            "summary": f"{direction}: {meaning}.",
            "academy_key": academy_key,
        })

    positives = [
        item for item in factors
        if item["impact"] == "positive"
    ][:4]
    negatives = [
        item for item in factors
        if item["impact"] == "negative"
    ][:4]
    neutrals = [
        item for item in factors
        if item["impact"] == "neutral"
    ][:3]

    quality_reasons = [
        item for item in factors
        if item["academy_key"] in {
            "roic", "free_cash_flow_margin", "debt_to_equity",
            "interest_coverage", "share_change_3y",
        }
    ]
    growth_reasons = [
        item for item in factors
        if item["academy_key"] in {
            "revenue_cagr_3y", "eps_cagr_3y",
        }
    ]
    valuation_reasons = [
        item for item in factors
        if item["academy_key"] in {"ev_to_ebit"}
    ]

    return {
        "score_factors": factors,
        "score_positive_factors": positives,
        "score_negative_factors": negatives,
        "score_neutral_factors": neutrals,
        "quality_explanation": quality_reasons,
        "growth_explanation": growth_reasons,
        "valuation_explanation": valuation_reasons,
    }
