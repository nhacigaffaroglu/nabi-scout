from typing import Dict, Optional


WEIGHTS = {
    "Kalite": 0.18,
    "Büyüme": 0.16,
    "Değerleme": 0.14,
    "Haber & Katalizör": 0.10,
    "Portföy Uyumu": 0.16,
    "Finansal Sağlık": 0.10,
    "Likidite": 0.05,
    "Katılım Uygunluğu": 0.11,
}


def clamp(value: Optional[float], minimum: float = 0, maximum: float = 100) -> float:
    if value is None:
        return 0.0
    return max(minimum, min(maximum, float(value)))


def financial_health_score(
    *,
    roic: Optional[float],
    operating_margin: Optional[float],
    net_debt_ebitda: Optional[float],
    free_cash_flow_margin: Optional[float],
) -> float:
    score = 50.0

    if roic is not None:
        score += min(25, max(-20, roic * 1.2))

    if operating_margin is not None:
        score += min(15, max(-15, operating_margin * 0.5))

    if free_cash_flow_margin is not None:
        score += min(15, max(-15, free_cash_flow_margin * 0.6))

    if net_debt_ebitda is not None:
        if net_debt_ebitda <= 0:
            score += 15
        elif net_debt_ebitda <= 1:
            score += 10
        elif net_debt_ebitda <= 2:
            score += 4
        elif net_debt_ebitda <= 3:
            score -= 5
        else:
            score -= 18

    return round(clamp(score), 1)


def valuation_score_from_prices(
    *,
    current_price: Optional[float],
    fair_value: Optional[float],
    manual_valuation_score: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    if current_price and fair_value and current_price > 0:
        discount = ((fair_value - current_price) / current_price) * 100
        score = 50 + discount
        return {
            "valuation_score": round(clamp(score), 1),
            "discount_to_fair_value": round(discount, 1),
        }

    return {
        "valuation_score": round(clamp(manual_valuation_score), 1),
        "discount_to_fair_value": None,
    }


def calculate_nabi_score_v2(
    *,
    quality: float,
    growth: float,
    valuation: float,
    news_catalyst: float,
    portfolio_fit: float,
    financial_health: float,
    liquidity: float,
    participation_score: float,
    participation_status: str,
) -> Dict[str, object]:
    if participation_status == "Uygun Değil":
        return {"score": 0.0, "decision": "ELE"}

    score = (
        clamp(quality) * WEIGHTS["Kalite"]
        + clamp(growth) * WEIGHTS["Büyüme"]
        + clamp(valuation) * WEIGHTS["Değerleme"]
        + clamp(news_catalyst) * WEIGHTS["Haber & Katalizör"]
        + clamp(portfolio_fit) * WEIGHTS["Portföy Uyumu"]
        + clamp(financial_health) * WEIGHTS["Finansal Sağlık"]
        + clamp(liquidity) * WEIGHTS["Likidite"]
        + clamp(participation_score) * WEIGHTS["Katılım Uygunluğu"]
    )

    score = round(clamp(score), 1)

    if score >= 82:
        decision = "GÜÇLÜ ADAY"
    elif score >= 68:
        decision = "İZLE"
    else:
        decision = "UZAK DUR"

    return {"score": score, "decision": decision}
