import streamlit as st
import pandas as pd

from services.supabase_client import get_supabase_client
from services.ui import configure_page, sidebar_navigation

configure_page("Dashboard | NABI Scout", "📊")
sidebar_navigation()

st.title("📊 Scout Dashboard")

supabase = get_supabase_client()
response = (
    supabase.table("investment_candidates")
    .select("symbol,asset_type,market,nabi_score,decision,research_status")
    .order("nabi_score", desc=True)
    .execute()
)
rows = response.data or []
df = pd.DataFrame(rows)

if df.empty:
    st.info("Henüz aday eklenmedi. Aday Havuzu sayfasından ilk yatırım aracını ekleyin.")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam aday", len(df))
    c2.metric("Güçlü aday", int((df["decision"] == "GÜÇLÜ ADAY").sum()))
    c3.metric("İzle", int((df["decision"] == "İZLE").sum()))
    c4.metric("Veri eksik", int((df["decision"] == "VERİ EKSİK").sum()))

    st.subheader("En yüksek puanlı adaylar")
    st.dataframe(df.head(10), use_container_width=True, hide_index=True)
