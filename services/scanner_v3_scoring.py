from __future__ import annotations

from typing import Optional


def clamp(value: Optional[float], low=0, high=100) -> float:
    if value is None:
        return 50.0
    return max(low, min(high, float(value)))


def scale(value: Optional[float], bad: float, good: float) -> float:
    if value is None:
        return 50.0
    return clamp((value - bad) / (good - bad) * 100)


def inverse(value: Optional[float], good: float, bad: float) -> float:
    if value is None:
        return 50.0
    return clamp((bad - value) / (bad - good) * 100)


def weighted(items, default=50.0) -> float:
    available = [
        (value, weight)
        for value, weight in items
        if value is not None
    ]
    if not available:
        return default

    total = sum(weight for _, weight in available)
    return sum(
        value * weight
        for value, weight in available
    ) / total


def score_v3(
    *,
    revenue_growth_1y,
    revenue_cagr_3y,
    eps_growth_1y,
    eps_cagr_3y,
    fcf_cagr_3y,
    gross_margin,
    operating_margin,
    net_margin,
    fcf_margin,
    roic,
    roe,
    roa,
    current_ratio,
    debt_to_equity,
    net_debt_to_fcf,
    interest_coverage,
    pe_ratio,
    price_to_sales,
    price_to_book,
    share_change_3y,
    payout_ratio,
    market_cap,
    average_volume,
    portfolio_fit,
    participation_score,
    participation_status,
    completeness,
):
    quality = weighted([
        (scale(roic, 5, 30), 0.25),
        (scale(roe, 8, 30), 0.12),
        (scale(roa, 3, 15), 0.08),
        (scale(operating_margin, 5, 35), 0.16),
        (scale(net_margin, 2, 25), 0.10),
        (scale(fcf_margin, 2, 25), 0.14),
        (scale(gross_margin, 15, 70), 0.05),
        (inverse(share_change_3y, -5, 20), 0.10),
    ])

    growth = weighted([
        (scale(revenue_growth_1y, -5, 25), 0.20),
        (scale(revenue_cagr_3y, 0, 20), 0.25),
        (scale(eps_growth_1y, -10, 30), 0.20),
        (scale(eps_cagr_3y, 0, 25), 0.20),
        (scale(fcf_cagr_3y, 0, 25), 0.15),
    ])

    valuation = weighted([
        (inverse(pe_ratio, 12, 45), 0.50),
        (inverse(price_to_sales, 1.5, 12), 0.25),
        (inverse(price_to_book, 1.5, 12), 0.25),
    ])

    financial_strength = weighted([
        (scale(current_ratio, 0.8, 2.5), 0.20),
        (inverse(debt_to_equity, 0.2, 2.5), 0.25),
        (inverse(net_debt_to_fcf, 0, 6), 0.30),
        (scale(interest_coverage, 2, 20), 0.25),
    ])

    capital_allocation = weighted([
        (inverse(share_change_3y, -5, 20), 0.60),
        (inverse(payout_ratio, 20, 100), 0.40),
    ])

    risk = weighted([
        (inverse(debt_to_equity, 0.2, 3.0), 0.28),
        (inverse(net_debt_to_fcf, 0, 8), 0.28),
        (scale(current_ratio, 0.7, 2.2), 0.18),
        (scale(interest_coverage, 1.5, 15), 0.18),
        (inverse(share_change_3y, -5, 25), 0.08),
    ])

    liquidity = weighted([
        (scale(market_cap, 500_000_000, 50_000_000_000), 0.55),
        (scale(average_volume, 100_000, 5_000_000), 0.45),
    ])

    raw = (
        quality * 0.22
        + growth * 0.18
        + valuation * 0.14
        + financial_strength * 0.14
        + capital_allocation * 0.08
        + risk * 0.08
        + clamp(portfolio_fit) * 0.10
        + liquidity * 0.03
        + clamp(participation_score) * 0.03
    )

    factor = (
        1.00 if completeness >= 90
        else 0.96 if completeness >= 80
        else 0.90 if completeness >= 70
        else 0.82 if completeness >= 60
        else 0.70 if completeness >= 50
        else 0.55
    )

    nabi_score = round(clamp(raw * factor), 1)

    if participation_status == "Uygun Değil":
        nabi_score = 0.0
        decision = "ELE"
    elif completeness < 50:
        decision = "VERİ EKSİK"
    elif nabi_score >= 82:
        decision = "GÜÇLÜ ADAY"
    elif nabi_score >= 70:
        decision = "ADAY"
    elif nabi_score >= 58:
        decision = "İZLE"
    elif nabi_score >= 48:
        decision = "ARAŞTIR"
    else:
        decision = "UZAK DUR"

    return {
        "quality_score": round(quality, 1),
        "growth_score": round(growth, 1),
        "valuation_score": round(valuation, 1),
        "financial_health_score": round(financial_strength, 1),
        "capital_allocation_score": round(capital_allocation, 1),
        "risk_score": round(risk, 1),
        "liquidity_score": round(liquidity, 1),
        "nabi_score": nabi_score,
        "decision": decision,
    }
