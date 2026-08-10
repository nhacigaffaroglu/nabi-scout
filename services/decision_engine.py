from __future__ import annotations

from typing import Any, Dict, List, Optional


def _component_score(value: Optional[float], default: float = 50.0) -> float:
    if value is None:
        return default
    return float(value)


def _grade(
    *,
    nabi_score: float,
    confidence: float,
    risk_score: float,
) -> str:
    combined = (
        nabi_score * 0.55
        + confidence * 0.25
        + risk_score * 0.20
    )

    if combined >= 88:
        return "AAA"
    if combined >= 82:
        return "AA"
    if combined >= 75:
        return "A"
    if combined >= 67:
        return "BBB"
    if combined >= 58:
        return "BB"
    if combined >= 48:
        return "B"
    return "C"


def build_decision(
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    score = float(candidate.get("nabi_score") or 0)
    confidence = float(candidate.get("research_confidence") or 0)
    risk = _component_score(candidate.get("risk_score"))
    valuation = _component_score(candidate.get("valuation_score"))
    quality = _component_score(candidate.get("quality_score"))
    growth = _component_score(candidate.get("growth_score"))
    completeness = float(candidate.get("data_completeness") or 0)

    positive = candidate.get("score_positive_factors") or []
    negative = candidate.get("score_negative_factors") or []
    flags = candidate.get("hard_flags") or []

    grade = _grade(
        nabi_score=score,
        confidence=confidence,
        risk_score=risk,
    )

    conviction = round(
        max(
            0,
            min(
                100,
                score * 0.50
                + confidence * 0.25
                + quality * 0.15
                + risk * 0.10,
            ),
        ),
        1,
    )

    opportunity = round(
        max(
            0,
            min(
                100,
                valuation * 0.45
                + growth * 0.25
                + quality * 0.20
                + confidence * 0.10,
            ),
        ),
        1,
    )

    if completeness < 50:
        decision = "VERİ EKSİK — ÖN ELEME"
        action = "Ek veri olmadan karar verme."
    elif score >= 84 and confidence >= 75:
        decision = "YÜKSEK ÖNCELİKLİ ARAŞTIRMA ADAYI"
        action = "Derin analiz ve değerleme doğrulamasına geçir."
    elif score >= 72:
        decision = "ARAŞTIRMA ADAYI"
        action = "İzleme listesine al ve eksik riskleri doğrula."
    elif score >= 60:
        decision = "İZLE"
        action = "Finansal iyileşme veya değerleme fırsatı bekle."
    elif score >= 48:
        decision = "İKİNCİL İNCELEME"
        action = "Yalnızca özel bir yatırım tezi varsa incele."
    else:
        decision = "ŞİMDİLİK UZAK DUR"
        action = "Kalite, risk veya büyüme düzelmeden öncelik verme."

    suitable_for: List[str] = []
    not_suitable_for: List[str] = []

    if quality >= 70 and confidence >= 70:
        suitable_for.append("Uzun vadeli kalite odaklı yatırımcı")
    if growth >= 72:
        suitable_for.append("Büyüme odaklı yatırımcı")
    if valuation >= 72:
        suitable_for.append("Değer fırsatı arayan yatırımcı")
    if risk >= 75:
        suitable_for.append("Daha defansif yatırımcı")
    if candidate.get("payout_ratio") is not None:
        suitable_for.append("Temettü kalitesini ayrıca inceleyen yatırımcı")

    if risk < 50:
        not_suitable_for.append("Düşük risk arayan yatırımcı")
    if valuation < 45:
        not_suitable_for.append("Ucuz değerleme arayan yatırımcı")
    if growth < 45:
        not_suitable_for.append("Yüksek büyüme arayan yatırımcı")
    if confidence < 65:
        not_suitable_for.append("Yalnızca yüksek veri güveniyle hareket eden yatırımcı")

    why_now: List[str] = []
    if valuation >= 70:
        why_now.append("Değerleme puanı araştırma için cazip seviyede.")
    if growth >= 75:
        why_now.append("Büyüme göstergeleri güçlü.")
    if quality >= 75:
        why_now.append("İş kalitesi ve sermaye verimliliği güçlü.")
    if candidate.get("fcf_cagr_3y") is not None and candidate["fcf_cagr_3y"] >= 12:
        why_now.append("Serbest nakit akışı hızlı büyüyor.")
    if not why_now:
        why_now.append(
            "Belirgin bir 'neden şimdi' katalizörü finansal veriden doğrulanamadı."
        )

    top_reasons = [
        item.get("summary")
        for item in positive[:3]
        if item.get("summary")
    ]
    top_risks = [
        item.get("summary")
        for item in negative[:3]
        if item.get("summary")
    ]
    top_risks.extend([str(flag) for flag in flags[:2]])

    verdict = (
        f"{candidate.get('company_name') or candidate.get('symbol')} için "
        f"NABI Score {score:.1f}, araştırma güveni %{confidence:.1f} ve "
        f"yatırım notu {grade}. Sonuç: {decision}."
    )

    return {
        "decision_label": decision,
        "decision_action": action,
        "investment_grade": grade,
        "conviction_score": conviction,
        "opportunity_score": opportunity,
        "decision_verdict": verdict,
        "decision_top_reasons": top_reasons,
        "decision_top_risks": top_risks,
        "decision_suitable_for": suitable_for,
        "decision_not_suitable_for": not_suitable_for,
        "decision_why_now": why_now,
        "decision_version": "Decision Engine v1",
    }
