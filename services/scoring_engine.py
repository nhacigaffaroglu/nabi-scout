WEIGHTS = {
    "Kalite": 0.18, "Büyüme": 0.16, "Değerleme": 0.14,
    "Haber & Katalizör": 0.12, "Portföy Uyumu": 0.16,
    "Risk": 0.10, "Likidite": 0.05, "Katılım Uygunluğu": 0.09,
}

def calculate_nabi_score(*, quality, growth, valuation, news_catalyst,
                         portfolio_fit, risk, liquidity,
                         participation_score, participation_status):
    if participation_status == "Uygun Değil":
        return {"score": 0.0, "decision": "ELE"}
    score = (
        quality * WEIGHTS["Kalite"] +
        growth * WEIGHTS["Büyüme"] +
        valuation * WEIGHTS["Değerleme"] +
        news_catalyst * WEIGHTS["Haber & Katalizör"] +
        portfolio_fit * WEIGHTS["Portföy Uyumu"] +
        (100-risk) * WEIGHTS["Risk"] +
        liquidity * WEIGHTS["Likidite"] +
        participation_score * WEIGHTS["Katılım Uygunluğu"]
    )
    score = round(max(0, min(100, score)), 1)
    decision = "GÜÇLÜ ADAY" if score >= 80 else "İZLE" if score >= 65 else "UZAK DUR"
    return {"score": score, "decision": decision}
