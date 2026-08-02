from typing import Dict


WEIGHTS = {
    "Kalite": 0.18,
    "Büyüme": 0.16,
    "Değerleme": 0.14,
    "Haber & Katalizör": 0.12,
    "Portföy Uyumu": 0.16,
    "Risk": 0.10,
    "Likidite": 0.05,
    "Katılım Uygunluğu": 0.09,
}


def calculate_nabi_score(
    *,
    quality: float,
    growth: float,
    valuation: float,
    news_catalyst: float,
    portfolio_fit: float,
    risk: float,
    liquidity: float,
    participation_score: float,
    participation_status: str,
) -> Dict[str, object]:
    if participation_status == "Uygun Değil":
        return {"score": 0.0, "decision": "ELE"}

    score = (
        quality * WEIGHTS["Kalite"]
        + growth * WEIGHTS["Büyüme"]
        + valuation * WEIGHTS["Değerleme"]
        + news_catalyst * WEIGHTS["Haber & Katalizör"]
        + portfolio_fit * WEIGHTS["Portföy Uyumu"]
        + (100 - risk) * WEIGHTS["Risk"]
        + liquidity * WEIGHTS["Likidite"]
        + participation_score * WEIGHTS["Katılım Uygunluğu"]
    )

    score = round(max(0.0, min(100.0, score)), 1)

    if score >= 80:
        decision = "GÜÇLÜ ADAY"
    elif score >= 65:
        decision = "İZLE"
    else:
        decision = "UZAK DUR"

    return {"score": score, "decision": decision}
