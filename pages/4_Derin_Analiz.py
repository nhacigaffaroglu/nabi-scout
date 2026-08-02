import streamlit as st
from services.ui import configure_page, render_sidebar

configure_page("Derin Analiz | NABI Scout", "🔬")
render_sidebar()

st.title("🔬 Derin Analiz")
st.info(
    "Candidate Intelligence v0.3 finansal alanları Aday Havuzu ve "
    "Aday Detayı ekranlarına taşıdı. Otomatik finansal veri v0.4'te eklenecek."
)
