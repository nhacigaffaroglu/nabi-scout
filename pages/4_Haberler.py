import streamlit as st
import pandas as pd

from services.supabase_client import get_supabase_client
from services.ui import configure_page, sidebar_navigation

configure_page("Haber & Katalizör | NABI Scout", "📰")
sidebar_navigation()

st.title("📰 Haber & Katalizör")
supabase = get_supabase_client()

candidates = supabase.table("investment_candidates").select("id,symbol").order("symbol").execute().data or []
candidate_map = {item["symbol"]: item["id"] for item in candidates}

if not candidate_map:
    st.info("Önce Aday Havuzu'na yatırım aracı ekleyin.")
    st.stop()

with st.form("news_form", clear_on_submit=True):
    symbol = st.selectbox("Sembol", list(candidate_map.keys()))
    title = st.text_input("Başlık")
    news_type = st.selectbox("Tür", ["Bilanço", "Yatırım", "Ürün", "Regülasyon", "Yönetim", "Dava", "Makro", "Diğer"])
    impact = st.selectbox("Etki", ["Pozitif", "Nötr", "Negatif"])
    importance = st.selectbox("Önem", ["Yüksek", "Orta", "Düşük"])
    summary = st.text_area("Özet")
    catalyst_risk = st.text_area("Katalizör / Risk")
    source_url = st.text_input("Kaynak URL")
    verified = st.checkbox("Kaynak doğrulandı")
    submitted = st.form_submit_button("Haberi kaydet", type="primary")

if submitted:
    supabase.table("news_items").insert({
        "candidate_id": candidate_map[symbol],
        "title": title,
        "news_type": news_type,
        "impact": impact,
        "importance": importance,
        "summary": summary,
        "catalyst_risk": catalyst_risk,
        "source_url": source_url,
        "verified": verified,
    }).execute()
    st.success("Haber kaydedildi.")

data = supabase.table("news_items").select("*, investment_candidates(symbol)").order("published_at", desc=True).execute().data or []
st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
