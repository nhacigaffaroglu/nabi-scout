import streamlit as st

from repositories.candidate_repository import CandidateRepository
from services.ui import prepare_protected_page, show_connection_status

client = prepare_protected_page("NABI Scout", "🔭")

st.title("🔭 NABI Scout")
st.caption("Nabi için doğru yatırım araçlarını araştıran bağımsız yatırım araştırma platformu.")
show_connection_status()

repo = CandidateRepository(client)
stats = repo.get_dashboard_stats()

cols = st.columns(5)
cols[0].metric("Toplam aday", stats["total"])
cols[1].metric("Güçlü aday", stats["strong"])
cols[2].metric("İzle", stats["watch"])
cols[3].metric("Katılım uygun", stats["participation_ok"])
cols[4].metric("Açık Araştırma", stats["open_research"])

st.subheader("En yüksek puanlı adaylar")
rows = repo.get_all(limit=6, order_by="nabi_score", descending=True)

if not rows:
    st.info("Henüz aday eklenmedi.")
else:
    for candidate in rows:
        with st.container(border=True):
            a, b, c, d = st.columns([2.4, 1, 1, 1.2])
            a.markdown(
                f"### {candidate['symbol']} — "
                f"{candidate.get('company_name') or candidate['symbol']}"
            )
            a.caption(
                f"{candidate.get('asset_type', '—')} · "
                f"{candidate.get('market', '—')} · "
                f"{candidate.get('sector_theme') or 'Tema yok'}"
            )
            b.metric(
                "NABI Score",
                f"{candidate['nabi_score']:.1f}"
                if candidate.get("nabi_score") is not None else "—",
            )
            c.metric(
                "İskonto",
                f"%{candidate['discount_to_fair_value']:.1f}"
                if candidate.get("discount_to_fair_value") is not None else "—",
            )
            d.markdown(f"**{candidate.get('decision') or 'VERİ EKSİK'}**")
            d.caption(candidate.get("participation_status") or "Kontrol Et")

st.divider()
st.info(
    "v0.3 Candidate Intelligence aktif. "
    "Canlı veri bağlantıları bir sonraki sprintte eklenecek."
)
