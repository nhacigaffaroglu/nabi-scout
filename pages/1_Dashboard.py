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
cols = st.columns(5)
cols[0].metric("Toplam aday", stats["total"])
cols[1].metric("Güçlü aday", stats["strong"])
cols[2].metric("İzle", stats["watch"])
cols[3].metric("Katılım uygun", stats["participation_ok"])
cols[4].metric("İnceleniyor", stats["researching"])

rows = repo.get_all(order_by="nabi_score", descending=True)
df = pd.DataFrame(rows)

if df.empty:
    st.info("Aday havuzu boş.")
else:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Karar dağılımı")
        st.bar_chart(
            df["decision"].fillna("VERİ EKSİK").value_counts()
        )

    with c2:
        st.subheader("Varlık türü dağılımı")
        st.bar_chart(
            df["asset_type"].fillna("Belirsiz").value_counts()
        )

    st.subheader("En yüksek NABI Score")
    visible = [
        "symbol",
        "company_name",
        "asset_type",
        "market",
        "current_price",
        "fair_value",
        "discount_to_fair_value",
        "nabi_score",
        "decision",
        "participation_status",
        "research_status",
    ]

    st.dataframe(
        df[[column for column in visible if column in df.columns]],
        use_container_width=True,
        hide_index=True,
    )
