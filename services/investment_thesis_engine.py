from __future__ import annotations
from typing import Any, Dict, List, Optional

def _fmt_pct(value: Optional[float]) -> str:
    return "veri yok" if value is None else f"%{value:.1f}"

def _fmt_num(value: Optional[float]) -> str:
    return "veri yok" if value is None else f"{value:.2f}"

def _append_unique(items: List[str], value: str) -> None:
    if value and value not in items:
        items.append(value)

def build_investment_thesis(candidate: Dict[str, Any]) -> Dict[str, Any]:
    strengths, concerns, conditions, evidence = [], [], [], []

    roic = candidate.get("roic")
    revenue_cagr = candidate.get("revenue_cagr_3y")
    eps_cagr = candidate.get("eps_cagr_3y")
    fcf_cagr = candidate.get("fcf_cagr_3y")
    fcf_margin = candidate.get("free_cash_flow_margin")
    debt_equity = candidate.get("debt_to_equity")
    interest_coverage = candidate.get("interest_coverage")
    share_change = candidate.get("share_change_3y")
    pe = candidate.get("pe_ratio")
    ev_ebit = candidate.get("ev_to_ebit")
    price_fcf = candidate.get("price_to_fcf")
    quality = float(candidate.get("quality_score") or 0)
    growth = float(candidate.get("growth_score") or 0)
    valuation = float(candidate.get("valuation_score") or 0)
    financial_strength = float(candidate.get("financial_health_score") or 0)
    confidence = float(candidate.get("research_confidence") or 0)
    score = float(candidate.get("nabi_score") or 0)

    if roic is not None:
        if roic >= 15:
            _append_unique(strengths, f"ROIC {_fmt_pct(roic)} ile sermaye verimliliği güçlü.")
            evidence.append({"metric": "ROIC", "value": roic, "interpretation": "positive"})
        elif roic < 7:
            _append_unique(concerns, f"ROIC {_fmt_pct(roic)} ile sermaye verimliliği zayıf.")
            _append_unique(conditions, "ROIC'in sürdürülebilir biçimde yükselmesi.")
            evidence.append({"metric": "ROIC", "value": roic, "interpretation": "negative"})

    if revenue_cagr is not None:
        if revenue_cagr >= 10:
            _append_unique(strengths, f"Üç yıllık gelir büyümesi {_fmt_pct(revenue_cagr)}.")
        elif revenue_cagr < 0:
            _append_unique(concerns, f"Gelirler üç yıllık dönemde {_fmt_pct(revenue_cagr)} küçüldü.")
            _append_unique(conditions, "Gelir trendinin yeniden pozitife dönmesi.")

    if eps_cagr is not None:
        if eps_cagr >= 12:
            _append_unique(strengths, f"Hisse başına kâr büyümesi güçlü: {_fmt_pct(eps_cagr)}.")
        elif eps_cagr < 0:
            _append_unique(concerns, f"Hisse başına kâr trendi negatif: {_fmt_pct(eps_cagr)}.")
            _append_unique(conditions, "EPS büyümesinin yeniden pozitif ve sürdürülebilir olması.")

    if fcf_cagr is not None:
        if fcf_cagr >= 10:
            _append_unique(strengths, f"Serbest nakit akışı üç yılda güçlü büyüdü: {_fmt_pct(fcf_cagr)}.")
        elif fcf_cagr < 0:
            _append_unique(concerns, f"Serbest nakit akışı büyümesi negatif: {_fmt_pct(fcf_cagr)}.")

    if fcf_margin is not None:
        if fcf_margin >= 10:
            _append_unique(strengths, f"FCF marjı {_fmt_pct(fcf_margin)} ile nakit üretimi güçlü.")
        elif fcf_margin < 0:
            _append_unique(concerns, f"FCF marjı negatif: {_fmt_pct(fcf_margin)}.")
            _append_unique(conditions, "Serbest nakit akışının yeniden pozitife dönmesi.")

    if debt_equity is not None:
        if debt_equity <= 0.8:
            _append_unique(strengths, f"Borç/özsermaye {_fmt_num(debt_equity)} ile kontrollü.")
        elif debt_equity > 2:
            _append_unique(concerns, f"Borç/özsermaye {_fmt_num(debt_equity)} ile yüksek.")
            _append_unique(conditions, "Borçluluğun ve finansman giderlerinin azalması.")

    if interest_coverage is not None:
        if interest_coverage >= 8:
            _append_unique(strengths, f"Faiz karşılama {_fmt_num(interest_coverage)}x ile güçlü.")
        elif interest_coverage < 2:
            _append_unique(concerns, f"Faiz karşılama {_fmt_num(interest_coverage)}x ile zayıf.")
            _append_unique(conditions, "Faiz karşılama oranının en az 3–5x seviyesine çıkması.")

    if share_change is not None and share_change > 10:
        _append_unique(concerns, f"Üç yılda hisse adedi {_fmt_pct(share_change)} arttı.")
        _append_unique(conditions, "Hisse sulandırmasının durması veya geri alım başlaması.")

    valuation_parts = []
    if pe is not None and pe > 0:
        valuation_parts.append(f"F/K {pe:.1f}")
    if ev_ebit is not None and ev_ebit > 0:
        valuation_parts.append(f"EV/EBIT {ev_ebit:.1f}")
    if price_fcf is not None and price_fcf > 0:
        valuation_parts.append(f"Fiyat/FCF {price_fcf:.1f}")

    if valuation >= 70:
        valuation_view = "Mevcut değerleme araştırma açısından görece cazip."
    elif valuation >= 50:
        valuation_view = "Değerleme ne belirgin ucuz ne de aşırı pahalı görünüyor."
    else:
        valuation_view = "Değerleme pahalı veya finansal oranlar anlamlı değil."

    if valuation_parts:
        valuation_view += " Ölçülebilen oranlar: " + ", ".join(valuation_parts) + "."

    if quality >= 75 and growth >= 70:
        thesis_type = "KALİTELİ BÜYÜME"
    elif quality >= 70 and valuation >= 70:
        thesis_type = "KALİTE + DEĞER"
    elif growth >= 75 and quality < 60:
        thesis_type = "YÜKSEK BÜYÜME / YÜKSEK BELİRSİZLİK"
    elif financial_strength >= 75 and growth < 55:
        thesis_type = "FİNANSAL OLARAK GÜÇLÜ / SINIRLI BÜYÜME"
    elif score < 48:
        thesis_type = "ZAYIF YATIRIM TEZİ"
    else:
        thesis_type = "DENGELİ / EK ARAŞTIRMA GEREKTİRİR"

    company = candidate.get("company_name") or candidate.get("symbol") or "Şirket"
    core_case = " ".join(strengths[:3]) if strengths else (
        "Mevcut finansal veriler belirgin bir güçlü yatırım tezi oluşturmuyor."
    )
    risk_case = " ".join(concerns[:3]) if concerns else (
        "Mevcut finansal verilerde belirgin bir sert risk bayrağı tespit edilmedi."
    )
    confidence_text = "yüksek" if confidence >= 85 else "orta" if confidence >= 65 else "düşük"

    thesis_summary = (
        f"{company}, “{thesis_type}” profilinde değerlendiriliyor. "
        f"{core_case} {valuation_view} Analizin veri güveni {confidence_text} seviyede."
    )

    return {
        "thesis_type": thesis_type,
        "thesis_summary": thesis_summary,
        "thesis_strengths": strengths,
        "thesis_concerns": concerns,
        "thesis_bull_case": (
            "Olumlu senaryoda şirket; kârlılık, nakit üretimi ve büyüme "
            "göstergelerini birlikte iyileştirirse araştırma önceliği artabilir."
        ),
        "thesis_bear_case": f"Olumsuz senaryoda: {risk_case}",
        "thesis_revisit_conditions": conditions,
        "thesis_revisit_trigger": (
            " ".join(conditions[:4]) if conditions else
            "Bir sonraki finansal raporda büyüme, nakit üretimi ve değerleme yeniden kontrol edilmeli."
        ),
        "thesis_valuation_view": valuation_view,
        "thesis_evidence": evidence,
        "thesis_version": "Investment Thesis Engine v1",
    }
