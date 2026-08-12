import streamlit as st
from services.ui import prepare_protected_page

prepare_protected_page("Derin Analiz | NABI Scout", "🔬")

st.title("🔬 Derin Analiz")
st.info(
    "Candidate Intelligence v0.3 finansal alanları Aday Havuzu ve "
    "Aday Detayı ekranlarına taşıdı. Otomatik finansal veri v0.4'te eklenecek."
)
