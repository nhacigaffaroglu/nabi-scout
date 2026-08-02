import streamlit as st
from services.ui import configure_page, render_sidebar

configure_page("İzleme Listesi | NABI Scout", "👁️")
render_sidebar()

st.title("👁️ İzleme Listesi")
st.info("İzleme listesi Candidate Intelligence sonrasında geliştirilecek.")
