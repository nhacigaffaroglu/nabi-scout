import streamlit as st

from services.candidate_pipeline_presentation import (
    SCORE_HIDDEN_COPY,
    display_nabi_score,
    pipeline_stage_label,
)
from services.research_workflow_service import build_research_workflow


def render_candidate_card(candidate: dict) -> str | None:
    with st.container(border=True):
        a, b, c, d = st.columns([2.5, 1, 1, 1.2])

        a.markdown(
            f"### {candidate['symbol']} — "
            f"{candidate.get('company_name') or candidate['symbol']}"
        )
        a.caption(
            f"{candidate.get('asset_type', '—')} · "
            f"{candidate.get('market', '—')} · "
            f"{candidate.get('sector_theme') or 'Tema yok'}"
        )
        a.write(candidate.get("investment_thesis") or candidate.get("main_reason") or "Yatırım tezi girilmedi.")

        score = display_nabi_score(candidate)
        b.metric(
            "NABI Score",
            f"{score:.1f}" if score is not None else "—",
        )
        if score is None:
            b.caption(SCORE_HIDDEN_COPY)

        c.metric(
            "İskonto",
            f"%{candidate['discount_to_fair_value']:.1f}"
            if candidate.get("discount_to_fair_value") is not None else "—",
        )

        d.markdown(f"**{candidate.get('decision') or 'VERİ EKSİK'}**")
        workflow = build_research_workflow(candidate)
        d.caption(pipeline_stage_label(candidate))
        d.caption(
            f"{candidate.get('participation_status') or 'Kontrol Et'} · "
            f"{workflow['research_status_label']}"
        )

        edit = d.button(
            "Düzenle",
            key=f"edit_{candidate['id']}",
            use_container_width=True,
        )
        delete = d.button(
            "Sil",
            key=f"delete_{candidate['id']}",
            use_container_width=True,
        )

        if candidate.get("critical_risk"):
            st.caption(f"⚠️ Kritik risk: {candidate['critical_risk']}")

    if edit:
        return "edit"

    if delete:
        return "delete"

    return None
