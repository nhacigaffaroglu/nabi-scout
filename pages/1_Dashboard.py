import pandas as pd
import streamlit as st
from repositories.candidate_repository import CandidateRepository
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Dashboard | NABI Scout", "📊")
render_sidebar()
st.title("📊 Scout Dashboard")
repo = CandidateRepository(get_supabase_client())
stats = repo.get_dashboard_stats()
cols = st.columns(4)
cols[0].metric("Toplam aday", stats["total"])
cols[1].metric("Güçlü aday", stats["strong"])
cols[2].metric("İzle", stats["watch"])
cols[3].metric("Veri eksik", stats["missing"])
df = pd.DataFrame(repo.get_all(order_by="nabi_score", descending=True))
if df.empty:
    st.info("Aday havuzu boş.")
else:
    st.subheader("Karar dağılımı")
    st.bar_chart(df["decision"].fillna("VERİ EKSİK").value_counts())
    st.dataframe(df[[c for c in ["symbol","company_name","asset_type","market","participation_status","nabi_score","decision","research_status"] if c in df.columns]], use_container_width=True, hide_index=True)
