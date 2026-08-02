import streamlit as st
from services.ui import configure_page, render_sidebar
configure_page("Derin Analiz | NABI Scout","🔬")
render_sidebar()
st.title("🔬 Derin Analiz")
st.info("v0.2'de mevcut form korunur. Finansal veri otomasyonu v0.3'te eklenecek.")
