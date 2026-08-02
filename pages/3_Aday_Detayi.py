import pandas as pd
import streamlit as st

from repositories.candidate_repository import CandidateRepository
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Aday Detayı | NABI Scout", "🔎")
render_sidebar()

st.title("🔎 Aday Detayı")
repo = CandidateRepository(get_supabase_client())
rows = repo.get_all(order_by="symbol", descending=False)

if not rows:
    st.info("Henüz aday bulunmuyor.")
    st.stop()

labels = {
    f"{candidate['symbol']} — "
    f"{candidate.get('company_name') or candidate['symbol']}":
    candidate["id"]
    for candidate in rows
}

selected = st.selectbox("Aday seç", list(labels.keys()))
candidate = repo.get_by_id(labels[selected])

title, score, valuation, decision = st.columns([2.4, 1, 1, 1.2])

title.markdown(f"## {candidate['symbol']}")
title.write(candidate.get("company_name") or "İsim belirtilmedi")
title.caption(
    f"{candidate.get('asset_type', '—')} · "
    f"{candidate.get('market', '—')} · "
    f"{candidate.get('country') or 'Ülke yok'}"
)

score.metric(
    "NABI Score",
    f"{candidate['nabi_score']:.1f}"
    if candidate.get("nabi_score") is not None else "—",
)

valuation.metric(
    "İskonto",
    f"%{candidate['discount_to_fair_value']:.1f}"
    if candidate.get("discount_to_fair_value") is not None else "—",
)

decision.metric(
    "Karar",
    candidate.get("decision") or "VERİ EKSİK",
)

st.subheader("Finansal profil")
metrics = st.columns(6)

metrics[0].metric(
    "Güncel fiyat",
    candidate.get("current_price") or "—",
)
metrics[1].metric(
    "Adil değer",
    candidate.get("fair_value") or "—",
)
metrics[2].metric(
    "F/K",
    candidate.get("pe_ratio") or "—",
)
metrics[3].metric(
    "PEG",
    candidate.get("peg_ratio") or "—",
)
metrics[4].metric(
    "ROIC",
    f"%{candidate.get('roic')}"
    if candidate.get("roic") is not None else "—",
)
metrics[5].metric(
    "Net borç / EBITDA",
    candidate.get("net_debt_ebitda") or "—",
)

st.subheader("Puan profili")
score_data = pd.DataFrame(
    {
        "Puan": [
            candidate.get("quality_score") or 0,
            candidate.get("growth_score") or 0,
            candidate.get("valuation_score") or 0,
            candidate.get("news_catalyst_score") or 0,
            candidate.get("portfolio_fit_score") or 0,
            candidate.get("financial_health_score") or 0,
            candidate.get("liquidity_score") or 0,
            candidate.get("participation_score") or 0,
        ]
    },
    index=[
        "Kalite",
        "Büyüme",
        "Değerleme",
        "Haber",
        "Portföy Uyumu",
        "Finansal Sağlık",
        "Likidite",
        "Katılım",
    ],
)
st.bar_chart(score_data)

c1, c2 = st.columns(2)

with c1:
    st.subheader("Yatırım tezi")
    st.write(candidate.get("investment_thesis") or "Henüz girilmedi.")

    st.subheader("Büyüme katalizörleri")
    st.write(candidate.get("growth_catalysts") or "Henüz girilmedi.")

with c2:
    st.subheader("Kritik risk")
    st.write(candidate.get("critical_risk") or "Henüz girilmedi.")

    st.subheader("Araştırma durumu")
    st.write(candidate.get("research_status") or "Araştırılacak")

st.subheader("Not")
st.write(candidate.get("notes") or "—")
