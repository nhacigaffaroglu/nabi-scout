from __future__ import annotations
from typing import Any, Dict, List, Optional

def pct(value: Optional[float]) -> str:
    return "veri yok" if value is None else f"%{value:.1f}"

def ratio(value: Optional[float]) -> str:
    return "veri yok" if value is None else f"{value:.2f}"

def build(candidate: Dict[str, Any]) -> Dict[str, Any]:
    strengths: List[str] = []
    risks: List[str] = []
    watch: List[str] = []

    roic = candidate.get("roic")
    revenue_cagr = candidate.get("revenue_cagr_3y")
    eps_cagr = candidate.get("eps_cagr_3y")
    fcf_cagr = candidate.get("fcf_cagr_3y")
    fcf_margin = candidate.get("free_cash_flow_margin")
    debt_equity = candidate.get("debt_to_equity")
    interest = candidate.get("interest_coverage")
    share_change = candidate.get("share_change_3y")
    ev_ebit = candidate.get("ev_to_ebit")
    peg = candidate.get("peg_ratio_calculated")
    pe = candidate.get("pe_ratio")

    if roic is not None:
        if roic >= 15:
            strengths.append(f"ROIC {pct(roic)}; sermaye verimliliği güçlü.")
        elif roic < 7:
            risks.append(f"ROIC {pct(roic)}; sermaye verimliliği zayıf.")
        else:
            watch.append(f"ROIC {pct(roic)}; orta seviyede.")

    if revenue_cagr is not None:
        if revenue_cagr >= 10:
            strengths.append(f"Üç yıllık gelir CAGR {pct(revenue_cagr)}.")
        elif revenue_cagr < 0:
            risks.append(f"Üç yıllık gelir trendi negatif: {pct(revenue_cagr)}.")
        else:
            watch.append(f"Gelir büyümesi sınırlı: {pct(revenue_cagr)}.")

    if eps_cagr is not None:
        if eps_cagr >= 12:
            strengths.append(f"Üç yıllık EPS CAGR {pct(eps_cagr)}.")
        elif eps_cagr < 0:
            risks.append(f"EPS trendi negatif: {pct(eps_cagr)}.")

    if fcf_cagr is not None and fcf_cagr >= 10:
        strengths.append(f"Üç yıllık FCF CAGR {pct(fcf_cagr)}.")

    if fcf_margin is not None:
        if fcf_margin >= 10:
            strengths.append(f"FCF marjı {pct(fcf_margin)}; nakit üretimi güçlü.")
        elif fcf_margin < 0:
            risks.append(f"FCF marjı negatif: {pct(fcf_margin)}.")

    if debt_equity is not None:
        if debt_equity <= 0.8:
            strengths.append(f"Borç/özsermaye {ratio(debt_equity)}; kontrollü.")
        elif debt_equity > 2:
            risks.append(f"Borç/özsermaye {ratio(debt_equity)}; yüksek.")

    if interest is not None:
        if interest >= 8:
            strengths.append(f"Faiz karşılama {ratio(interest)}x; güçlü.")
        elif interest < 2:
            risks.append(f"Faiz karşılama {ratio(interest)}x; zayıf.")

    if share_change is not None and share_change > 10:
        risks.append(f"Üç yılda hisse adedi {pct(share_change)} arttı.")

    valuation = []
    if pe is not None:
        valuation.append(f"F/K {pe:.1f}")
    if ev_ebit is not None:
        valuation.append(f"EV/EBIT {ev_ebit:.1f}")
    if peg is not None:
        valuation.append(f"PEG {peg:.2f}")

    company = candidate.get("company_name") or candidate.get("symbol")
    score = candidate.get("nabi_score")
    score_text = "veri yok" if score is None else f"{score:.1f}/100"
    profile = candidate.get("investment_profile") or "Belirsiz"
    decision = candidate.get("decision") or "Belirsiz"

    summary = (
        f"{company}, NABI Score {score_text} ile “{profile}” profilindedir. "
        f"Karar: {decision}. "
        f"Değerleme: {', '.join(valuation) if valuation else 'veri sınırlı'}."
    )
    if strengths:
        summary += " Güçlü yönler: " + " ".join(strengths[:2])
    if risks:
        summary += " Başlıca riskler: " + " ".join(risks[:2])

    conclusion = (
        "Araştırma önceliği yüksek."
        if decision in {"GÜÇLÜ ADAY", "ADAY"}
        else "İzleme ve ek doğrulama gerekli."
        if decision in {"İZLE", "ARAŞTIR"}
        else "Mevcut verilerle aday havuzuna uygun görünmüyor."
    )

    return {
        "memo_summary": summary,
        "memo_strengths": strengths,
        "memo_risks": risks,
        "memo_watch_items": watch,
        "memo_conclusion": conclusion,
        "memo_version": "Deterministic Memo v1",
    }
