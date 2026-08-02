import streamlit as st

from services.scoring_engine import WEIGHTS
from services.ui import configure_page, sidebar_navigation

configure_page("Ayarlar | NABI Scout", "⚙️")
sidebar_navigation()

st.title("⚙️ Ayarlar")
st.subheader("NABI Score ağırlıkları")

for key, value in WEIGHTS.items():
    st.write(f"**{key}:** %{value * 100:.0f}")

st.warning(
    "Bu başlangıç sürümünde ağırlıklar kod içinde sabittir. "
    "Sonraki sürümde Supabase üzerinden değiştirilebilir hale getirilecektir."
)

st.subheader("Kullanıcı profili")
st.write("- Ana hedef: 2031'de 500.000 USD")
st.write("- Risk: Orta / yüksek")
st.write("- Katılım uygunluğu: Zorunlu")
st.write("- İşlem tercihi: Tam adet ve verimli işlem eşiği")
