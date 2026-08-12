from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import streamlit as st

from services.company_report_participation_service import CompanyReportParticipationView
from services.participation_assessment_change_service import annotate_history_with_changes
from services.participation_intelligence_contract import (
    PARTICIPATION_DISCLAIMER_SHORT,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.ui_formatters import format_datetime_tr


def _status_container(status: str):
    if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return st.error
    return st.warning


def _format_outcome(value: Optional[str]) -> str:
    if not value:
        return "—"
    return str(value)


def render_company_report_participation_section(
    view: CompanyReportParticipationView,
    *,
    history: Optional[Sequence[Mapping[str, Any]]] = None,
    history_unavailable_message: Optional[str] = None,
    save_message: Optional[str] = None,
    save_skipped_duplicate: bool = False,
    save_failed: bool = False,
) -> bool:
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
        _render_participation_history(history, history_unavailable_message)
        return False

    result = view.result
    if result is None:
        st.info("Katılım incelemesi sonucu üretilemedi.")
        _render_participation_history(history, history_unavailable_message)
        return False

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

    save_clicked = st.button(
        "Katılım incelemesini kaydet",
        key=f"save_participation_assessment_{view.symbol}",
    )
    if save_message:
        if save_failed:
            st.warning(save_message)
        elif save_skipped_duplicate:
            st.info(save_message)
        else:
            st.success(save_message)

    st.caption(PARTICIPATION_DISCLAIMER_SHORT)
    _render_participation_history(history, history_unavailable_message)
    return save_clicked


def _render_participation_history(
    history: Optional[Sequence[Mapping[str, Any]]],
    unavailable_message: Optional[str] = None,
) -> None:
    st.markdown("**Katılım geçmişi**")
    if unavailable_message:
        st.info(unavailable_message)
        return
    rows = list(history or [])
    if not rows:
        st.caption("Henüz kaydedilmiş katılım incelemesi yok.")
        return

    annotated = annotate_history_with_changes(rows)
    for row in annotated[:5]:
        assessed_at = format_datetime_tr(row.get("assessed_at"))
        methodology = row.get("methodology_id") or "—"
        version = row.get("methodology_version") or "—"
        change = row.get("change_from_previous") or {}
        change_summary = change.get("summary") or "—"
        st.caption(
            f"{assessed_at} · {row.get('status')} · {methodology} ({version}) · "
            f"Güven: {row.get('confidence') or '—'} · "
            f"Finansal: {_format_outcome(row.get('financial_overall_outcome'))} · "
            f"Faaliyet: {_format_outcome(row.get('business_overall_outcome'))} · "
            f"Değişim: {change_summary}"
        )
