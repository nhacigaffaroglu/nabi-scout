from __future__ import annotations

from typing import Any, Dict, Optional


def number(value: Any) -> Optional[float]:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def clamp(value: Optional[float], low: float = 0, high: float = 100) -> float:
    if value is None:
        return 50.0
    return max(low, min(high, float(value)))


def scale(value: Optional[float], bad: float, good: float) -> float:
    if value is None:
        return 50.0
    if good == bad:
        return 50.0
    return clamp((value - bad) / (good - bad) * 100)


def inverse(value: Optional[float], good: float, bad: float) -> float:
    if value is None:
        return 50.0
    if bad == good:
        return 50.0
    return clamp((bad - value) / (bad - good) * 100)


def weighted_available(
    items: list[tuple[Optional[float], float]],
    default: float = 50.0,
) -> float:
    available = [
        (float(value), weight)
        for value, weight in items
        if value is not None
    ]
    if not available:
        return default

    total_weight = sum(weight for _, weight in available)
    if total_weight <= 0:
        return default

    return sum(
        value * weight
        for value, weight in available
    ) / total_weight


def data_completeness(fields: Dict[str, Any]) -> float:
    if not fields:
        return 0.0
    present = sum(value is not None for value in fields.values())
    return round(present / len(fields) * 100, 1)


def calculate_scores(
    *,
    revenue_growth_1y: Optional[float],
    revenue_cagr_3y: Optional[float],
    eps_growth_1y: Optional[float],
    eps_cagr_3y: Optional[float],
    gross_margin: Optional[float],
    operating_margin: Optional[float],
    net_margin: Optional[float],
    fcf_margin: Optional[float],
    roic: Optional[float],
    roe: Optional[float],
    roa: Optional[float],
    current_ratio: Optional[float],
    debt_to_equity: Optional[float],
    net_debt_to_fcf: Optional[float],
    interest_coverage: Optional[float],
    pe_ratio: Optional[float],
    price_to_sales: Optional[float],
    price_to_book: Optional[float],
    market_cap: Optional[float],
    average_volume: Optional[float],
    portfolio_fit: float,
    participation_score: float,
    participation_status: str,
    completeness: float,
) -> Dict[str, float | str]:
    quality = weighted_available([
        (scale(roic, 5, 30), 0.28),
        (scale(roe, 8, 30), 0.14),
        (scale(roa, 3, 15), 0.10),
        (scale(operating_margin, 5, 35), 0.18),
        (scale(net_margin, 2, 25), 0.10),
        (scale(fcf_margin, 2, 25), 0.14),
        (scale(gross_margin, 15, 70), 0.06),
    ])

    growth = weighted_available([
        (scale(revenue_growth_1y, -5, 25), 0.25),
        (scale(revenue_cagr_3y, 0, 20), 0.25),
        (scale(eps_growth_1y, -10, 30), 0.25),
        (scale(eps_cagr_3y, 0, 25), 0.25),
    ])

    valuation = weighted_available([
        (inverse(pe_ratio, 12, 45), 0.50),
        (inverse(price_to_sales, 1.5, 12), 0.25),
        (inverse(price_to_book, 1.5, 12), 0.25),
    ])

    financial_strength = weighted_available([
        (scale(current_ratio, 0.8, 2.5), 0.22),
        (inverse(debt_to_equity, 0.2, 2.5), 0.28),
        (inverse(net_debt_to_fcf, 0, 6), 0.28),
        (scale(interest_coverage, 2, 20), 0.22),
    ])

    risk = weighted_available([
        (inverse(debt_to_equity, 0.2, 3.0), 0.30),
        (inverse(net_debt_to_fcf, 0, 8), 0.30),
        (scale(current_ratio, 0.7, 2.2), 0.20),
        (scale(interest_coverage, 1.5, 15), 0.20),
    ])

    liquidity = weighted_available([
        (scale(market_cap, 500_000_000, 50_000_000_000), 0.55),
        (scale(average_volume, 100_000, 5_000_000), 0.45),
    ])

    raw_score = (
        quality * 0.23
        + growth * 0.18
        + valuation * 0.14
        + financial_strength * 0.15
        + risk * 0.08
        + clamp(portfolio_fit) * 0.12
        + liquidity * 0.04
        + clamp(participation_score) * 0.06
    )

    completeness_factor = (
        1.00 if completeness >= 85
        else 0.94 if completeness >= 75
        else 0.86 if completeness >= 65
        else 0.74 if completeness >= 50
        else 0.58
    )
    score = round(clamp(raw_score * completeness_factor), 1)

    if participation_status == "Uygun Değil":
        decision = "ELE"
        score = 0.0
    elif completeness < 50:
        decision = "VERİ EKSİK"
    elif score >= 82:
        decision = "GÜÇLÜ ADAY"
    elif score >= 68:
        decision = "İZLE"
    elif score >= 55:
        decision = "ARAŞTIR"
    else:
        decision = "UZAK DUR"

    return {
        "quality_score": round(quality, 1),
        "growth_score": round(growth, 1),
        "valuation_score": round(valuation, 1),
        "financial_health_score": round(financial_strength, 1),
        "risk_score": round(risk, 1),
        "liquidity_score": round(liquidity, 1),
        "nabi_score": score,
        "decision": decision,
    }
