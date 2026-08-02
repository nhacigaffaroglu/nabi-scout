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

labels = {f"{r['symbol']} — {r.get('company_name') or r['symbol']}": r["id"] for r in rows}
selected = st.selectbox("Aday seç", list(labels))
candidate = repo.get_by_id(labels[selected])

a, b, c, d = st.columns([2.4, 1, 1, 1])
a.markdown(f"## {candidate['symbol']}")
a.write(candidate.get("company_name") or "Şirket adı yok")
a.caption(f"{candidate.get('investment_profile') or 'Profil yok'} · {candidate.get('score_confidence') or 'Güven yok'}")
b.metric("NABI Score", candidate.get("nabi_score") or 0)
c.metric("Veri Tamlığı", f"%{candidate.get('data_completeness') or 0}")
d.metric("Karar", candidate.get("decision") or "—")

st.subheader("NABI Investment Memo")
st.write(candidate.get("memo_summary") or "Bu kayıt için memo henüz üretilmedi.")

left, right = st.columns(2)
with left:
    st.markdown("#### Güçlü Taraflar")
    for item in candidate.get("memo_strengths") or []:
        st.success(item)
with right:
    st.markdown("#### Riskler")
    for item in candidate.get("memo_risks") or []:
        st.error(item)

for item in candidate.get("memo_watch_items") or []:
    st.warning(item)
st.info(candidate.get("memo_conclusion") or "Ek doğrulama gerekli.")

st.subheader("Gelişmiş Metrikler")
metrics = [
    ("ROIC", candidate.get("roic")),
    ("Gelir CAGR 3Y", candidate.get("revenue_cagr_3y")),
    ("EPS CAGR 3Y", candidate.get("eps_cagr_3y")),
    ("FCF CAGR 3Y", candidate.get("fcf_cagr_3y")),
    ("EV/EBIT", candidate.get("ev_to_ebit")),
    ("PEG", candidate.get("peg_ratio_calculated")),
    ("Fiyat/FCF", candidate.get("price_to_fcf")),
    ("Faiz Karşılama", candidate.get("interest_coverage")),
]
cols = st.columns(4)
for i, (label, value) in enumerate(metrics):
    cols[i % 4].metric(label, "—" if value is None else f"{value:.2f}")

st.subheader("Skor Haritası")
score_data = {
    "Kalite": candidate.get("quality_score") or 0,
    "Büyüme": candidate.get("growth_score") or 0,
    "Değerleme": candidate.get("valuation_score") or 0,
    "Finansal Güç": candidate.get("financial_health_score") or 0,
    "Risk": candidate.get("risk_score") or 0,
}
st.bar_chart(pd.DataFrame({"Puan": score_data}))
