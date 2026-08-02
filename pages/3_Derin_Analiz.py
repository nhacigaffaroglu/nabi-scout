import streamlit as st
import pandas as pd

from services.supabase_client import get_supabase_client
from services.ui import configure_page, sidebar_navigation

configure_page("Derin Analiz | NABI Scout", "🔬")
sidebar_navigation()

st.title("🔬 Derin Analiz")
supabase = get_supabase_client()

candidates = supabase.table("investment_candidates").select("id,symbol").order("symbol").execute().data or []

if not candidates:
    st.info("Önce Aday Havuzu'na yatırım aracı ekleyin.")
    st.stop()

candidate_map = {item["symbol"]: item["id"] for item in candidates}
symbol = st.selectbox("Yatırım aracı", list(candidate_map.keys()))

with st.form("deep_analysis_form"):
    revenue_growth = st.number_input("Gelir büyümesi (%)", value=0.0)
    eps_growth = st.number_input("EPS büyümesi (%)", value=0.0)
    operating_margin = st.number_input("Faaliyet marjı (%)", value=0.0)
    roic = st.number_input("ROIC (%)", value=0.0)
    net_debt_ebitda = st.number_input("Net borç / EBITDA", value=0.0)
    valuation_summary = st.text_area("Değerleme özeti")
    investment_plans = st.text_area("Şirketin yatırım planları")
    competitive_advantage = st.text_area("Rekabet avantajı")
    management_notes = st.text_area("Yönetim ve sermaye tahsisi")
    analyst_note = st.text_area("Scout analist notu")

    submitted = st.form_submit_button("Analizi kaydet", type="primary")

if submitted:
    supabase.table("deep_analyses").insert({
        "candidate_id": candidate_map[symbol],
        "revenue_growth": revenue_growth,
        "eps_growth": eps_growth,
        "operating_margin": operating_margin,
        "roic": roic,
        "net_debt_ebitda": net_debt_ebitda,
        "valuation_summary": valuation_summary,
        "investment_plans": investment_plans,
        "competitive_advantage": competitive_advantage,
        "management_notes": management_notes,
        "analyst_note": analyst_note,
    }).execute()
    st.success("Derin analiz kaydedildi.")

data = supabase.table("deep_analyses").select("*, investment_candidates(symbol)").order("created_at", desc=True).execute().data or []
st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
