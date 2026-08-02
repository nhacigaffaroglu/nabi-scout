import streamlit as st
from services.scoring_engine import WEIGHTS
from services.ui import configure_page, render_sidebar
configure_page("Ayarlar | NABI Scout","⚙️")
render_sidebar()
st.title("⚙️ Ayarlar")
for k,v in WEIGHTS.items():
    st.write(f"**{k}:** %{v*100:.0f}")
