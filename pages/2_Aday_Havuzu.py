import streamlit as st
import pandas as pd

from services.supabase_client import get_supabase_client
from services.scoring_engine import calculate_nabi_score
from services.ui import configure_page, sidebar_navigation

configure_page("Aday Havuzu | NABI Scout", "🧭")
sidebar_navigation()

st.title("🧭 Aday Havuzu")
supabase = get_supabase_client()

with st.form("candidate_form", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    symbol = c1.text_input("Sembol", placeholder="SPUS").strip().upper()
    asset_type = c2.selectbox("Varlık türü", ["Hisse", "ETF", "Fon", "Sukuk", "Altın", "Gümüş", "Diğer"])
    market = c3.selectbox("Piyasa", ["ABD", "BIST", "TEFAS", "Global", "Diğer"])

    c4, c5 = st.columns(2)
    participation_status = c4.selectbox("Katılım uygunluğu", ["Kontrol Et", "Uygun", "Uygun Değil"])
    sector_theme = c5.text_input("Sektör / Tema")

    st.markdown("#### Araştırma puanları")
    cols = st.columns(4)
    quality = cols[0].number_input("Kalite", 0, 100, 50)
    growth = cols[1].number_input("Büyüme", 0, 100, 50)
    valuation = cols[2].number_input("Değerleme", 0, 100, 50)
    news_catalyst = cols[3].number_input("Haber & katalizör", 0, 100, 50)

    cols2 = st.columns(4)
    portfolio_fit = cols2[0].number_input("Portföy uyumu", 0, 100, 50)
    risk = cols2[1].number_input("Risk (yüksek = kötü)", 0, 100, 50)
    liquidity = cols2[2].number_input("Likidite", 0, 100, 50)
    participation_score = cols2[3].number_input("Katılım skoru", 0, 100, 100)

    reason = st.text_area("Ana gerekçe")
    critical_risk = st.text_area("Kritik risk")

    submitted = st.form_submit_button("Adayı kaydet", type="primary")

if submitted:
    if not symbol:
        st.error("Sembol zorunludur.")
    else:
        score_result = calculate_nabi_score(
            quality=quality,
            growth=growth,
            valuation=valuation,
            news_catalyst=news_catalyst,
            portfolio_fit=portfolio_fit,
            risk=risk,
            liquidity=liquidity,
            participation_score=participation_score,
            participation_status=participation_status,
        )

        payload = {
            "symbol": symbol,
            "asset_type": asset_type,
            "market": market,
            "participation_status": participation_status,
            "sector_theme": sector_theme,
            "quality_score": quality,
            "growth_score": growth,
            "valuation_score": valuation,
            "news_catalyst_score": news_catalyst,
            "portfolio_fit_score": portfolio_fit,
            "risk_score": risk,
            "liquidity_score": liquidity,
            "participation_score": participation_score,
            "nabi_score": score_result["score"],
            "decision": score_result["decision"],
            "main_reason": reason,
            "critical_risk": critical_risk,
            "research_status": "Araştırılacak",
        }

        supabase.table("investment_candidates").insert(payload).execute()
        st.success(f"{symbol} kaydedildi. NABI Score: {score_result['score']} — {score_result['decision']}")

response = (
    supabase.table("investment_candidates")
    .select("*")
    .order("created_at", desc=True)
    .execute()
)
df = pd.DataFrame(response.data or [])

st.subheader("Kayıtlı adaylar")
if df.empty:
    st.info("Henüz aday bulunmuyor.")
else:
    visible = [
        "symbol", "asset_type", "market", "participation_status",
        "nabi_score", "decision", "research_status", "updated_at"
    ]
    st.dataframe(df[[c for c in visible if c in df.columns]], use_container_width=True, hide_index=True)
