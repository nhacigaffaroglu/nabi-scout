import streamlit as st
from repositories.candidate_repository import CandidateRepository
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar, show_connection_status

configure_page("NABI Scout", "🔭")
render_sidebar()
st.title("🔭 NABI Scout")
st.caption("Nabi için doğru yatırım araçlarını araştıran bağımsız yatırım araştırma platformu.")
show_connection_status()

repo = CandidateRepository(get_supabase_client())
stats = repo.get_dashboard_stats()
cols = st.columns(4)
cols[0].metric("Toplam aday", stats["total"])
cols[1].metric("Güçlü aday", stats["strong"])
cols[2].metric("İzle", stats["watch"])
cols[3].metric("Araştırılıyor", stats["researching"])

st.subheader("En yüksek puanlı adaylar")
rows = repo.get_all(limit=5, order_by="nabi_score", descending=True)
if not rows:
    st.info("Henüz aday eklenmedi.")
else:
    for c in rows:
        with st.container(border=True):
            a, b, d = st.columns([2.4, 1, 1.2])
            a.markdown(f"### {c['symbol']} — {c.get('company_name') or c['symbol']}")
            a.caption(f"{c.get('asset_type','—')} · {c.get('market','—')} · {c.get('sector_theme') or 'Tema yok'}")
            b.metric("NABI Score", f"{c['nabi_score']:.1f}" if c.get("nabi_score") is not None else "—")
            d.markdown(f"**{c.get('decision') or 'VERİ EKSİK'}**")
            d.caption(c.get("participation_status") or "Kontrol Et")
