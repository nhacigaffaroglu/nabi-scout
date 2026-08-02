from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def clamp(value: Optional[float], low: float = 0, high: float = 100) -> float:
    if value is None:
        return 50.0
    return max(low, min(high, float(value)))


def scale(value: Optional[float], bad: float, good: float) -> Optional[float]:
    if value is None:
        return None
    if good == bad:
        return 50.0
    return clamp((value - bad) / (good - bad) * 100)


def inverse(value: Optional[float], good: float, bad: float) -> Optional[float]:
    if value is None:
        return None
    if bad == good:
        return 50.0
    return clamp((bad - value) / (bad - good) * 100)


def weighted(items: List[tuple[Optional[float], float]]) -> float:
    available = [
        (float(value), weight)
        for value, weight in items
        if value is not None
    ]
    if not available:
        return 50.0

    weight_sum = sum(weight for _, weight in available)
    if weight_sum <= 0:
        return 50.0

    return sum(value * weight for value, weight in available) / weight_sum


@dataclass
class ScoreReason:
    label: str
    impact: str
    detail: str
    value: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "impact": self.impact,
            "detail": self.detail,
            "value": self.value,
        }


def _reason(
    reasons: List[ScoreReason],
    *,
    label: str,
    impact: str,
    detail: str,
    value: Optional[float],
) -> None:
    if value is not None:
        reasons.append(
            ScoreReason(
                label=label,
                impact=impact,
                detail=detail,
                value=round(float(value), 2),
            )
        )


def calculate_nabi_score_v4(
    *,
    revenue_growth_1y: Optional[float],
    revenue_cagr_3y: Optional[float],
    eps_growth_1y: Optional[float],
    eps_cagr_3y: Optional[float],
    fcf_cagr_3y: Optional[float],
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
    share_change_3y: Optional[float],
    payout_ratio: Optional[float],
    market_cap: Optional[float],
    average_volume: Optional[float],
    portfolio_fit: float,
    participation_score: float,
    participation_status: str,
    completeness: float,
) -> Dict[str, Any]:
    reasons: List[ScoreReason] = []

    profitability = weighted([
        (scale(roic, 5, 25), 0.35),
        (scale(operating_margin, 5, 30), 0.25),
        (scale(fcf_margin, 2, 22), 0.20),
        (scale(net_margin, 2, 20), 0.10),
        (scale(gross_margin, 15, 65), 0.10),
    ])

    capital_efficiency = weighted([
        (scale(roic, 5, 25), 0.50),
        (scale(roe, 8, 28), 0.30),
        (scale(roa, 3, 14), 0.20),
    ])

    growth_quality = weighted([
        (scale(revenue_cagr_3y, 0, 18), 0.28),
        (scale(eps_cagr_3y, 0, 22), 0.28),
        (scale(fcf_cagr_3y, 0, 22), 0.24),
        (scale(revenue_growth_1y, -5, 22), 0.10),
        (scale(eps_growth_1y, -10, 28), 0.10),
    ])

    balance_sheet = weighted([
        (scale(current_ratio, 0.8, 2.2), 0.20),
        (inverse(debt_to_equity, 0.2, 2.2), 0.30),
        (inverse(net_debt_to_fcf, 0, 5), 0.30),
        (scale(interest_coverage, 2, 18), 0.20),
    ])

    valuation = weighted([
        (inverse(pe_ratio, 12, 40), 0.50),
        (inverse(price_to_sales, 1.5, 10), 0.25),
        (inverse(price_to_book, 1.5, 10), 0.25),
    ])

    shareholder_friendly = weighted([
        (inverse(share_change_3y, -5, 18), 0.65),
        (inverse(payout_ratio, 20, 100), 0.35),
    ])

    liquidity = weighted([
        (scale(market_cap, 500_000_000, 40_000_000_000), 0.60),
        (scale(average_volume, 100_000, 4_000_000), 0.40),
    ])

    # Temel kalite skoru
    quality_score = (
        profitability * 0.45
        + capital_efficiency * 0.30
        + shareholder_friendly * 0.10
        + balance_sheet * 0.15
    )

    growth_score = growth_quality

    financial_strength_score = balance_sheet

    risk_score = weighted([
        (inverse(debt_to_equity, 0.2, 2.8), 0.30),
        (inverse(net_debt_to_fcf, 0, 7), 0.30),
        (scale(current_ratio, 0.7, 2.0), 0.20),
        (scale(interest_coverage, 1.5, 15), 0.20),
    ])

    # Veri azsa nötr 50 değerlerinin puanı yapay biçimde yükseltmesini engeller.
    confidence_factor = (
        1.00 if completeness >= 90
        else 0.97 if completeness >= 80
        else 0.92 if completeness >= 70
        else 0.84 if completeness >= 60
        else 0.72 if completeness >= 50
        else 0.50
    )

    raw_score = (
        quality_score * 0.27
        + growth_score * 0.20
        + valuation * 0.15
        + financial_strength_score * 0.14
        + risk_score * 0.08
        + clamp(portfolio_fit) * 0.10
        + liquidity * 0.03
        + clamp(participation_score) * 0.03
    )

    # Sert finansal risk cezaları
    penalty = 0.0
    hard_flags: List[str] = []

    if debt_to_equity is not None and debt_to_equity > 3:
        penalty += 7
        hard_flags.append("Yüksek borç/özsermaye")

    if interest_coverage is not None and interest_coverage < 1.5:
        penalty += 8
        hard_flags.append("Zayıf faiz karşılama")

    if fcf_margin is not None and fcf_margin < 0:
        penalty += 6
        hard_flags.append("Negatif serbest nakit akışı marjı")

    if revenue_cagr_3y is not None and revenue_cagr_3y < -5:
        penalty += 4
        hard_flags.append("Gelirlerde yapısal küçülme")

    if share_change_3y is not None and share_change_3y > 20:
        penalty += 5
        hard_flags.append("Yüksek hisse sulandırması")

    nabi_score = round(
        clamp(raw_score * confidence_factor - penalty),
        1,
    )

    if participation_status == "Uygun Değil":
        nabi_score = 0.0
        decision = "ELE"
    elif completeness < 50:
        decision = "VERİ EKSİK"
    elif nabi_score >= 84:
        decision = "GÜÇLÜ ADAY"
    elif nabi_score >= 72:
        decision = "ADAY"
    elif nabi_score >= 60:
        decision = "İZLE"
    elif nabi_score >= 48:
        decision = "ARAŞTIR"
    else:
        decision = "UZAK DUR"

    # Profil sınıflandırması
    if quality_score >= 75 and growth_score >= 70:
        profile = "KALİTELİ BÜYÜME"
    elif valuation >= 75 and quality_score >= 60:
        profile = "DEĞER FIRSATI"
    elif financial_strength_score >= 75 and quality_score >= 65:
        profile = "FİNANSAL GÜÇLÜ"
    elif growth_score >= 75 and risk_score < 55:
        profile = "RİSKLİ BÜYÜME"
    elif quality_score >= 70 and growth_score < 55:
        profile = "OLGUN KALİTE"
    elif nabi_score < 48:
        profile = "ZAYIF / RİSKLİ"
    else:
        profile = "DENGELİ / İZLE"

    # Açıklanabilir puan nedenleri
    if roic is not None:
        _reason(
            reasons,
            label="ROIC",
            impact="positive" if roic >= 15 else "negative" if roic < 7 else "neutral",
            detail=(
                "Sermaye verimliliği güçlü."
                if roic >= 15
                else "Sermaye verimliliği zayıf."
                if roic < 7
                else "Sermaye verimliliği orta seviyede."
            ),
            value=roic,
        )

    if revenue_cagr_3y is not None:
        _reason(
            reasons,
            label="3Y Revenue CAGR",
            impact="positive" if revenue_cagr_3y >= 10 else "negative" if revenue_cagr_3y < 0 else "neutral",
            detail=(
                "Gelir büyümesi güçlü ve süreklilik gösteriyor."
                if revenue_cagr_3y >= 10
                else "Gelirler küçülüyor."
                if revenue_cagr_3y < 0
                else "Gelir büyümesi sınırlı."
            ),
            value=revenue_cagr_3y,
        )

    if fcf_margin is not None:
        _reason(
            reasons,
            label="FCF Margin",
            impact="positive" if fcf_margin >= 12 else "negative" if fcf_margin < 0 else "neutral",
            detail=(
                "Nakit üretim kalitesi güçlü."
                if fcf_margin >= 12
                else "Serbest nakit akışı negatif."
                if fcf_margin < 0
                else "Nakit üretimi sınırlı."
            ),
            value=fcf_margin,
        )

    if debt_to_equity is not None:
        _reason(
            reasons,
            label="Debt/Equity",
            impact="positive" if debt_to_equity <= 0.8 else "negative" if debt_to_equity > 2 else "neutral",
            detail=(
                "Borçluluk kontrollü."
                if debt_to_equity <= 0.8
                else "Borçluluk yüksek."
                if debt_to_equity > 2
                else "Borçluluk orta seviyede."
            ),
            value=debt_to_equity,
        )

    if pe_ratio is not None:
        _reason(
            reasons,
            label="P/E",
            impact="positive" if 0 < pe_ratio <= 18 else "negative" if pe_ratio > 40 or pe_ratio <= 0 else "neutral",
            detail=(
                "Değerleme makul görünüyor."
                if 0 < pe_ratio <= 18
                else "Değerleme pahalı veya kâr negatif."
                if pe_ratio > 40 or pe_ratio <= 0
                else "Değerleme orta seviyede."
            ),
            value=pe_ratio,
        )

    positive_reasons = [
        reason.to_dict()
        for reason in reasons
        if reason.impact == "positive"
    ][:3]
    negative_reasons = [
        reason.to_dict()
        for reason in reasons
        if reason.impact == "negative"
    ][:3]

    confidence_level = (
        "YÜKSEK"
        if completeness >= 85
        else "ORTA"
        if completeness >= 65
        else "DÜŞÜK"
    )

    return {
        "profitability_score": round(profitability, 1),
        "capital_efficiency_score": round(capital_efficiency, 1),
        "quality_score": round(quality_score, 1),
        "growth_score": round(growth_score, 1),
        "valuation_score": round(valuation, 1),
        "financial_health_score": round(financial_strength_score, 1),
        "shareholder_score": round(shareholder_friendly, 1),
        "risk_score": round(risk_score, 1),
        "liquidity_score": round(liquidity, 1),
        "nabi_score": nabi_score,
        "decision": decision,
        "investment_profile": profile,
        "score_confidence": confidence_level,
        "score_penalty": round(penalty, 1),
        "hard_flags": hard_flags,
        "positive_reasons": positive_reasons,
        "negative_reasons": negative_reasons,
        "all_reasons": [reason.to_dict() for reason in reasons],
    }
