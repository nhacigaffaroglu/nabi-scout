from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import streamlit as st

from services.company_report_participation_service import CompanyReportParticipationView
from services.participation_assessment_change_service import annotate_history_with_changes
from services.participation_financial_diagnostics import serialize_financial_diagnostics
from services.participation_completeness import translate_missing_capability
from services.participation_intelligence_contract import (
    PARTICIPATION_DISCLAIMER_SHORT,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.participation_message_normalization import merge_warning_messages
from services.participation_revenue_granularity import (
    attribution_quality_label_tr,
    granularity_label_tr,
)
from services.participation_screening_context import screening_context_label_tr
from services.ui_formatters import format_datetime_tr


def _status_container(status: str):
    if status == PARTICIPATION_STATUS_UYGUN:
        return st.success
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
        st.markdown("**Eksik kanıt alanları**")
        for item in view.missing_capabilities:
            st.caption(f"• {translate_missing_capability(item)}")

    result = view.result
    if result is not None and result.assessment_completeness is not None:
        completeness = result.assessment_completeness
        st.caption(
            "Değerlendirme kapsamı: "
            f"finansal {completeness.financial_rules_evaluated}/"
            f"{completeness.financial_rules_total} · "
            f"faaliyet {completeness.business_rules_evaluated}/"
            f"{completeness.business_rules_total}"
        )
        diagnostics = serialize_financial_diagnostics(
            result.financial_screen_result,
            as_of_date=assessment.as_of_date,
        )
        if diagnostics or result.participation_provider_calls or view.missing_capabilities:
            with st.expander("Teknik katılım kanıt ayrıntıları"):
                if result.screening_context:
                    st.caption(
                        "Tarama bağlamı: "
                        + screening_context_label_tr(result.screening_context)
                    )
                methodology = result.participation_assessment
                if methodology.methodology_version:
                    st.caption(
                        f"Metodoloji sürümü: {methodology.methodology_version}"
                    )
                if result.participation_provider_calls:
                    st.caption(
                        "Sağlayıcı çağrıları (katılım): "
                        + ", ".join(
                            f"{key}={value}"
                            for key, value in sorted(result.participation_provider_calls.items())
                        )
                    )
                if diagnostics:
                    st.markdown("**Finansal kural kanıtları**")
                    for row in diagnostics:
                        st.markdown(f"**{row['rule_name']}** · {row['status']}")
                        if row["status"] == "Değerlendirilemedi":
                            st.caption(row["limitations"] or "Yeterli kanıt yok.")
                        else:
                            st.caption(f"Pay ({row['numerator_name']}): {row['numerator_value']}")
                            st.caption(
                                f"Payda ({row['denominator_name']}): {row['denominator_value']}"
                            )
                            st.caption(f"Hesaplanan oran: {row['calculated_ratio']}")
                            st.caption(f"Eşik: {row['threshold']}")
                        st.caption(f"Dönem: {row['fiscal_period']}")
                        st.caption(f"Kaynak: {row['source']}")
                        if row.get("source_fields"):
                            st.caption(f"Kaynak alanları: {row['source_fields']}")
                attribution = getattr(result, "revenue_attribution", None)
                if attribution is not None and getattr(attribution, "items", None):
                    st.markdown("**Yasaklı faaliyet gelir oranı — SEC 10-K Inline XBRL**")
                    st.caption(f"Durum: {getattr(attribution, 'status', '—')}")
                    if getattr(attribution, "partition_status", None):
                        st.caption(f"Bölümleme durumu: {attribution.partition_status}")
                    if getattr(attribution, "partition_granularity", None):
                        st.caption(
                            "Gelir ayrımı düzeyi: "
                            + granularity_label_tr(attribution.partition_granularity)
                        )
                    if getattr(attribution, "attribution_quality", None):
                        st.caption(
                            "Kanıt kalitesi: "
                            + attribution_quality_label_tr(attribution.attribution_quality)
                        )
                    if attribution.prohibited_ratio is not None:
                        st.caption(f"Oran: {attribution.prohibited_ratio * 100:.2f}%")
                    st.caption("Eşik: <5%")
                    st.caption(f"Dönem: FY {attribution.screening_period or '—'}")
                    st.caption(f"Kaynak: SEC 10-K Inline XBRL ({attribution.filing_accession})")
                    st.caption(f"Seçilen eksen: {attribution.selected_axis or '—'}")
                    if attribution.partition_coverage is not None:
                        st.caption(f"Kapsam: {attribution.partition_coverage * 100:.1f}%")
                    for limitation in attribution.limitations[:3]:
                        st.caption(limitation)
                    with st.expander("Gelir bölümleme kanıtı"):
                        for item in attribution.items:
                            st.caption(
                                f"- {item.reported_label} — ${item.amount:,.0f} → "
                                f"{item.mapping_status}"
                                + (f" ({item.msci_category})" if item.msci_category else "")
                            )
                for item in view.missing_capabilities:
                    st.caption(f"{item}: {translate_missing_capability(item)}")

    combined_warnings = merge_warning_messages(view.warnings, assessment.warnings)
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
