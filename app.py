import streamlit as st

from services.ui import prepare_protected_page

prepare_protected_page("NABI Scout", "🔭")
st.switch_page("pages/1_Dashboard.py")
