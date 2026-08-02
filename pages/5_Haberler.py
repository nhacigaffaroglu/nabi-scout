import streamlit as st
from services.ui import configure_page, render_sidebar
configure_page("Haberler | NABI Scout","📰")
render_sidebar()
st.title("📰 Haber & Katalizör")
st.info("Haber motoru v0.3 sprintinde otomatik hale getirilecek.")
