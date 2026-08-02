import streamlit as st
import pandas as pd

from services.supabase_client import get_supabase_client
from services.ui import configure_page, sidebar_navigation

configure_page("İzleme Listesi | NABI Scout", "👁️")
sidebar_navigation()

st.title("👁️ İzleme Listesi")
supabase = get_supabase_client()

candidates = supabase.table("investment_candidates").select("id,symbol,nabi_score").order("symbol").execute().data or []
candidate_map = {item["symbol"]: item for item in candidates}

if not candidate_map:
    st.info("Önce Aday Havuzu'na yatırım aracı ekleyin.")
    st.stop()

with st.form("watchlist_form", clear_on_submit=True):
    symbol = st.selectbox("Sembol", list(candidate_map.keys()))
    target_role = st.text_input("Portföyde hedeflenen rol")
    buy_threshold = st.number_input("Alım eşiği", min_value=0.0)
    target_price = st.number_input("Hedef fiyat", min_value=0.0)
    risk_threshold = st.number_input("Risk / stop eşiği", min_value=0.0)
    catalyst = st.text_area("Beklenen katalizör")
    status = st.selectbox("Durum", ["İzle", "Alıma Yakın", "Al", "Bekle", "Çıkar"])
    notes = st.text_area("Not")
    submitted = st.form_submit_button("İzleme listesine ekle", type="primary")

if submitted:
    supabase.table("watchlist").insert({
        "candidate_id": candidate_map[symbol]["id"],
        "target_role": target_role,
        "buy_threshold": buy_threshold,
        "target_price": target_price,
        "risk_threshold": risk_threshold,
        "catalyst": catalyst,
        "status": status,
        "notes": notes,
    }).execute()
    st.success("İzleme listesine eklendi.")

data = supabase.table("watchlist").select("*, investment_candidates(symbol,nabi_score)").order("created_at", desc=True).execute().data or []
st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
