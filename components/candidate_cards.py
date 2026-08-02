import streamlit as st

def render_candidate_card(candidate):
    with st.container(border=True):
        a, b, c = st.columns([2.5, 1, 1.2])
        a.markdown(f"### {candidate['symbol']} — {candidate.get('company_name') or candidate['symbol']}")
        a.caption(f"{candidate.get('asset_type','—')} · {candidate.get('market','—')} · {candidate.get('sector_theme') or 'Tema yok'}")
        a.write(candidate.get("main_reason") or "Henüz ana gerekçe girilmedi.")
        b.metric("NABI Score", f"{candidate['nabi_score']:.1f}" if candidate.get("nabi_score") is not None else "—")
        b.caption(f"{candidate.get('decision') or 'VERİ EKSİK'} · {candidate.get('participation_status') or 'Kontrol Et'}")
        edit = c.button("Düzenle", key=f"edit_{candidate['id']}", use_container_width=True)
        delete = c.button("Sil", key=f"delete_{candidate['id']}", use_container_width=True)
        if candidate.get("critical_risk"):
            st.caption(f"⚠️ Kritik risk: {candidate['critical_risk']}")
    return "edit" if edit else "delete" if delete else None
