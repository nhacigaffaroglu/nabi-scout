import pandas as pd
import streamlit as st

from repositories.candidate_repository import CandidateRepository
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Aday Detayı | NABI Scout", "🔎")
render_sidebar()

st.title("🔎 Aday Detayı")
repo = CandidateRepository(get_supabase_client())
rows = repo.get_all(order_by="nabi_score", descending=True)

if not rows:
    st.info("Henüz aday bulunmuyor.")
    st.stop()

labels = {
    f"{row['symbol']} — {row.get('company_name') or row['symbol']}": row["id"]
    for row in rows
}
selected = st.selectbox("Aday seç", list(labels.keys()))
candidate = repo.get_by_id(labels[selected])

a, b, c, d = st.columns([2.4, 1, 1, 1])
a.markdown(f"## {candidate['symbol']}")
a.write(candidate.get("company_name") or "Şirket adı yok")
a.caption(
    f"{candidate.get('investment_profile') or 'Profil yok'} · "
    f"{candidate.get('score_confidence') or 'Güven yok'}"
)
b.metric("NABI Score", candidate.get("nabi_score") or 0)
c.metric("Veri Tamlığı", f"%{candidate.get('data_completeness') or 0}")
d.metric("Karar", candidate.get("decision") or "—")

st.subheader("Skor Haritası")
score_data = {
    "Kalite": candidate.get("quality_score"),
    "Büyüme": candidate.get("growth_score"),
    "Değerleme": candidate.get("valuation_score"),
    "Finansal Güç": candidate.get("financial_health_score"),
    "Risk": candidate.get("risk_score"),
    "Likidite": candidate.get("liquidity_score"),
}
score_df = pd.DataFrame(
    {"Puan": [value or 0 for value in score_data.values()]},
    index=list(score_data.keys()),
)
st.bar_chart(score_df)

left, right = st.columns(2)

with left:
    st.subheader("Güçlü Taraflar")
    positives = candidate.get("positive_reasons") or []
    if positives:
        for item in positives:
            st.success(
                f"**{item.get('label')}** — "
                f"{item.get('detail')} "
                f"({item.get('value')})"
            )
    else:
        st.info("Belirgin güçlü neden bulunamadı.")

with right:
    st.subheader("Riskler")
    negatives = candidate.get("negative_reasons") or []
    if negatives:
        for item in negatives:
            st.error(
                f"**{item.get('label')}** — "
                f"{item.get('detail')} "
                f"({item.get('value')})"
            )
    else:
        st.info("Belirgin negatif neden bulunamadı.")

flags = candidate.get("hard_flags") or []
if flags:
    st.warning("Sert risk bayrakları: " + ", ".join(flags))

st.subheader("Temel Finansallar")
metrics = [
    ("ROIC", candidate.get("roic")),
    ("ROE", candidate.get("roe")),
    ("Gelir CAGR 3Y", candidate.get("revenue_cagr_3y")),
    ("EPS CAGR 3Y", candidate.get("eps_cagr_3y")),
    ("FCF CAGR 3Y", candidate.get("fcf_cagr_3y")),
    ("FCF Marjı", candidate.get("free_cash_flow_margin")),
    ("Borç/Özsermaye", candidate.get("debt_to_equity")),
    ("Faiz Karşılama", candidate.get("interest_coverage")),
    ("F/K", candidate.get("pe_ratio")),
    ("Fiyat/Satış", candidate.get("price_to_sales")),
]
columns = st.columns(5)
for index, (label, value) in enumerate(metrics):
    columns[index % 5].metric(
        label,
        "—" if value is None else f"{value:.2f}",
    )
