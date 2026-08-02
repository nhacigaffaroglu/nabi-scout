import streamlit as st
from services.ui import configure_page, render_sidebar

configure_page("Haberler | NABI Scout", "📰")
render_sidebar()

st.title("📰 Haber & Katalizör")
st.info("Otomatik haber toplama ve AI haber analizi v0.4 sprintinde eklenecek.")
