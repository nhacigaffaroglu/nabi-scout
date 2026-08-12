import streamlit as st
from services.ui import prepare_protected_page

prepare_protected_page("Haberler | NABI Scout", "📰")

st.title("📰 Haber & Katalizör")
st.info("Otomatik haber toplama ve AI haber analizi v0.4 sprintinde eklenecek.")
