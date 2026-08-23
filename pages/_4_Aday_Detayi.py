import streamlit as st

from services.ui import prepare_protected_page

prepare_protected_page("Yönlendirme | NABI Scout", "↪")

st.info("Bu sayfa güncellendi. Şirket araştırması için Company Report kullanılır.")
if st.button("Company Report'a git", type="primary"):
    st.query_params["symbol"] = st.query_params.get("symbol") or ""
    st.switch_page("pages/4_Company_Report.py")
