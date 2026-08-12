from __future__ import annotations

import streamlit as st

from services.company_report_participation_service import CompanyReportParticipationView
from services.participation_intelligence_contract import (
    PARTICIPATION_DISCLAIMER_SHORT,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)


def _status_container(status: str):
    if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return st.error
    return st.warning


def render_company_report_participation_section(
    view: CompanyReportParticipationView,
) -> None:
    st.subheader("Katılım İncelemesi")
    st.caption(
        "Bağımsız katılım metodolojisi taraması. NABI Skoru, yatırım kararı, "
        "tez veya değerleme puanlamasından ayrı bir araştırma boyutudur."
    )

    if not view.available:
        st.info(
            view.error_message
            or "Katılım incelemesi şu anda gösterilemiyor."
        )
        return

    result = view.result
    if result is None:
        st.info("Katılım incelemesi sonucu üretilemedi.")
        return

    assessment = result.participation_assessment
    _status_container(assessment.status)(f"**Durum:** {assessment.status}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Kaynak:** {assessment.source}")
        st.markdown(f"**Güven:** {assessment.confidence}")
    with col2:
        if assessment.methodology_label:
            version = assessment.methodology_version or "—"
            st.markdown(
                f"**Metodoloji:** {assessment.methodology_label} ({version})"
            )
        elif result.methodology_id:
            st.markdown(f"**Metodoloji ID:** {result.methodology_id}")

    st.markdown("**Finansal oran taraması**")
    st.caption(view.financial_screen_summary)

    st.markdown("**Faaliyet alanı taraması**")
    st.caption(view.business_screen_summary)

    if view.missing_capabilities:
        st.markdown("**Eksik yetenekler / kanıt**")
        for item in view.missing_capabilities:
            st.caption(f"• {item}")

    combined_warnings = tuple(dict.fromkeys((*view.warnings, *assessment.warnings)))
    if combined_warnings:
        st.markdown("**Uyarılar**")
        for warning in combined_warnings[:8]:
            st.caption(warning)

    if result.errors:
        st.markdown("**Veri hataları**")
        for error in result.errors[:4]:
            st.caption(error)

    st.caption(PARTICIPATION_DISCLAIMER_SHORT)
