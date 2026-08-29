from __future__ import annotations

import streamlit as st

from services.security_intelligence_contract import SecurityFacts, SecurityIntelligenceView


_DIM_LABELS = {
    "QUALITY": "Kalite",
    "GROWTH": "Büyüme",
    "PROFITABILITY": "Kârlılık",
    "BALANCE_SHEET": "Bilanço",
    "VALUATION": "Değerleme",
    "MOMENTUM": "Momentum",
    "RISK": "Risk",
    "DATA_QUALITY": "Veri kalitesi",
}


def _score(value) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}"


def render_security_intelligence_section(
    view: SecurityIntelligenceView,
    facts: SecurityFacts,
    *,
    nabi_score=None,
    persisted_row=None,
) -> None:
    st.subheader("Security Intelligence")
    st.caption(
        "Menkul kıymetin kendi temel değerlendirmesi. NABI Skoru v4 Scanner/aday skorudur "
        "ve burada değiştirilmez. Portföy uyumu bu skora dahil değildir."
    )
    cols = st.columns(5)
    cols[0].metric("SI skoru", _score(view.overall_score))
    cols[1].metric("SI durum", view.overall_status or "—")
    cols[2].metric("Yatırım durumu", view.investment_state or "—")
    cols[3].metric("Güven", _score(view.overall_confidence))
    cols[4].metric("NABI Skoru v4", _score(nabi_score) if nabi_score not in (None, "") else "—")
    st.caption(
        f"Katılım: {view.participation_status or '—'} · "
        f"research_allowed: {view.research_allowed} · "
        f"facts {view.facts_version} · engine {view.engine_version}"
    )
    st.caption(
        "Canlı evaluate() kaynak gerçektir. Kayıtlı snapshot geçmiş ve değişim içindir."
    )
    if persisted_row:
        st.caption(
            "Kayıtlı snapshot: "
            f"{persisted_row.get('id') or '—'} · as_of {persisted_row.get('as_of') or '—'}"
        )
    if nabi_score not in (None, "") and view.overall_score is not None:
        st.caption(
            "SI overall ≠ NABI Skoru v4: SI portföy uyumu ve likiditeyi içermez; "
            "eksik veri 50’ye çekilmez."
        )

    rows = []
    for name, label in _DIM_LABELS.items():
        dim = view.dimension(name)
        rows.append(
            {
                "Boyut": label,
                "Skor": _score(dim.score),
                "Durum": dim.status,
                "Güven": _score(dim.confidence),
                "Eksik": ", ".join(dim.missing_facts[:4]) or "—",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    dq = facts
    st.caption(
        f"Tamamlanma: {_score(dq.completeness_pct)}% · "
        f"Tazelik: {dq.freshness_status or '—'} · "
        f"Otorite: {dq.authority_status or '—'} · "
        f"Dönem: {dq.period_compatibility or '—'}"
    )
    if view.strengths:
        st.markdown("**Güçlü yönler:** " + ", ".join(view.strengths))
    if view.weaknesses:
        st.markdown("**Zayıf yönler:** " + ", ".join(view.weaknesses))
    if view.risk_flags:
        st.markdown("**Risk bayrakları:** " + ", ".join(view.risk_flags))
    if facts.missing_critical_fields:
        st.caption("Kritik eksikler: " + ", ".join(facts.missing_critical_fields))
    if view.change_flags:
        st.caption("Değişim: " + ", ".join(view.change_flags))
