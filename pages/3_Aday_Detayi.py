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
labels = {f"{c['symbol']} — {c.get('company_name') or c['symbol']}": c["id"] for c in rows}
selected = st.selectbox("Aday seç", list(labels))
c = repo.get_by_id(labels[selected])
a,b,d = st.columns([2,1,1])
a.markdown(f"## {c['symbol']}")
a.write(c.get("company_name") or "İsim yok")
b.metric("NABI Score", f"{c['nabi_score']:.1f}" if c.get("nabi_score") is not None else "—")
d.metric("Karar", c.get("decision") or "VERİ EKSİK")
scores = pd.DataFrame({
    "Puan":[c.get("quality_score") or 0,c.get("growth_score") or 0,c.get("valuation_score") or 0,c.get("news_catalyst_score") or 0,c.get("portfolio_fit_score") or 0,c.get("liquidity_score") or 0,c.get("participation_score") or 0]
}, index=["Kalite","Büyüme","Değerleme","Haber","Portföy Uyumu","Likidite","Katılım"])
st.bar_chart(scores)
st.write("**Ana gerekçe:**", c.get("main_reason") or "—")
st.write("**Kritik risk:**", c.get("critical_risk") or "—")
st.write("**Not:**", c.get("notes") or "—")
