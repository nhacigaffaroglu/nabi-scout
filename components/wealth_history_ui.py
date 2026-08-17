from __future__ import annotations

from decimal import Decimal
from typing import Optional

import streamlit as st

from components.nabi_design_system import (
    render_data_quality_banner,
    render_kpi_row,
    render_section_title,
    render_status_badge,
)
from services.ui_formatters import format_date_dmy
from services.wealth_contribution_intelligence import (
    ContributionEvidenceQuality,
    PerformanceEvidenceQuality,
)
from services.wealth_history_chart import build_wealth_history_curve
from services.wealth_history_service import (
    ATTRIBUTION_INCOMPLETE_COPY,
    HISTORY_STARTED_COPY,
    WAITING_SECOND_SNAPSHOT,
    WealthHistoryState,
    WealthHistoryView,
)


def _money(value: Optional[Decimal | float], currency: str) -> str:
    if value is None:
        return "—"
    amount = float(value)
    if str(currency).upper() == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def render_wealth_history(view: WealthHistoryView) -> None:
    render_section_title("Servet Geçmişi")
    if view.history_state == WealthHistoryState.ZERO:
        st.info("Henüz snapshot yok. Günlük kayıt başladıktan sonra geçmiş oluşacak.")
        return

    issues = []
    if view.latest_is_partial:
        issues.append("Kısmi değerleme: BIST piyasa değeri yok")
    if view.evidence_quality != PerformanceEvidenceQuality.COMPLETE:
        issues.append("Dönemsel getiri henüz yok")
    render_data_quality_banner(issues=issues, partial=view.latest_is_partial)

    if view.history_state == WealthHistoryState.STARTED and view.snapshot_count == 1:
        st.markdown(
            render_status_badge("Geçmiş başladı", "info"),
            unsafe_allow_html=True,
        )
        render_kpi_row(
            [
                ("Snapshot tarihi", format_date_dmy(view.latest_snapshot_at), None),
                (
                    "Ölçülebilen servet",
                    _money(view.latest_value, view.currency),
                    "Alt sınır" if view.latest_is_partial else None,
                ),
                ("Durum", WAITING_SECOND_SNAPSHOT, None),
            ]
        )
        if view.latest_is_partial:
            st.caption("Kısmi değerleme — eksik fiyatlar 0 sayılmaz.")
        st.info(HISTORY_STARTED_COPY)
        return

    evidence_label = view.evidence_quality.value
    st.markdown(
        render_status_badge(evidence_label, "warning" if view.evidence_quality != PerformanceEvidenceQuality.COMPLETE else "success"),
        unsafe_allow_html=True,
    )
    if view.period_start and view.period_end:
        st.caption(
            f"Dönem: {format_date_dmy(view.period_start)} → {format_date_dmy(view.period_end)}"
        )
    metrics = [
        ("Başlangıç", _money(view.start_value, view.currency), None),
        ("Bitiş", _money(view.end_value, view.currency), None),
        (
            "Net katkı",
            _money(view.net_external_contributions, view.currency)
            if view.contribution_evidence_quality == ContributionEvidenceQuality.COMPLETE
            else "Kanıt eksik",
            None,
        ),
        (
            "Yatırım K/Z",
            _money(view.investment_gain_loss, view.currency)
            if view.investment_gain_loss is not None
            else "—",
            None,
        ),
    ]
    render_kpi_row(metrics)
    if view.return_pct is None:
        st.caption("Getiri % gösterilmiyor — kanıt yetersiz veya dönem karşılaştırılabilir değil.")
    else:
        st.caption(f"Modified Dietz getiri: {float(view.return_pct):.2f}%")

    chart = build_wealth_history_curve(view.curve_points)
    if chart is not None:
        st.altair_chart(chart, use_container_width=True)
        if any(point.is_partial for point in view.curve_points):
            st.caption("Kısmi snapshot noktaları turuncu işaretlenir; ara günler uydurulmaz.")

    if view.bridge_available:
        st.markdown("**Katkı / performans köprüsü**")
        st.caption(
            f"{_money(view.start_value, view.currency)} "
            f"+ {_money(view.net_external_contributions, view.currency)} "
            f"+ {_money(view.investment_gain_loss, view.currency)} "
            f"= {_money(view.end_value, view.currency)}"
        )
        st.info(view.attribution_summary)
    else:
        st.caption(ATTRIBUTION_INCOMPLETE_COPY)
    if view.snapshot_count == 1:
        st.info(HISTORY_STARTED_COPY)
