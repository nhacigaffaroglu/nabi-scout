import streamlit as st

from services.scoring_engine import WEIGHTS
from services.ui import prepare_protected_page

prepare_protected_page("Ayarlar | NABI Scout", "⚙️")

st.title("⚙️ Ayarlar")
st.subheader("NABI Score v2 ağırlıkları")

for key, value in WEIGHTS.items():
    st.write(f"**{key}:** %{value * 100:.0f}")

st.info("Bu sürümde ağırlıklar salt okunurdur; aktif NABI Score v4 scanner yolunu etkilemez.")
