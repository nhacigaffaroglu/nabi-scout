import streamlit as st

from components.nabi_design_system import render_section_title
from services.scoring_engine import WEIGHTS
from services.system_health_service import SystemHealthService
from services.ui import prepare_protected_page, show_connection_status

client = prepare_protected_page("Ayarlar | NABI Scout", "⚙️")

st.title("⚙️ Ayarlar")

render_section_title("Bağlantı")
show_connection_status()

render_section_title("Otomasyon Durumu")
health = SystemHealthService(client)
for row in health.list_automation_health():
    status = row.status or "—"
    detail = f"{row.run_date or '—'} · güncellenen: {row.records_updated or 0}"
    if row.status and row.status != "COMPLETED":
        st.warning(f"**{row.label}** — {status} ({detail})")
    else:
        st.caption(f"**{row.label}** — {status} ({detail})")

st.divider()
render_section_title("NABI Score v2 ağırlıkları")
for key, value in WEIGHTS.items():
    st.write(f"**{key}:** %{value * 100:.0f}")

st.info("Bu sürümde ağırlıklar salt okunurdur; aktif NABI Score v4 scanner yolunu etkilemez.")
