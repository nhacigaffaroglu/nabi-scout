from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional, Sequence

import streamlit as st

from components.nabi_design_system import (
    render_data_quality_banner,
    render_kpi_row,
    render_section_title,
    render_status_badge,
)
from services.ui_formatters import format_date_dmy
from services.wealth_contribution_intelligence import (
    CONTRIBUTION_HISTORY_PARTIAL_COPY,
    CONTRIBUTION_HISTORY_UNAVAILABLE_COPY,
    ContributionEvidenceQuality,
    PerformanceEvidenceQuality,
)
from services.wealth_external_cash_flow import ContributionReconciliation
from services.wealth_history_chart import build_wealth_history_curve
from services.wealth_history_service import (
    ATTRIBUTION_INCOMPLETE_COPY,
    HISTORY_STARTED_COPY,
    WAITING_SECOND_SNAPSHOT,
    WealthHistoryState,
    WealthHistoryView,
)
from services.wealth_performance_center_presentation import (
    BEST_LABEL,
    DETAILS_EXPANDER,
    INSUFFICIENT_COPY,
    PERIOD_OPTIONS,
    SECTION_TITLE,
    WEAKEST_LABEL,
    PerformanceCenterView,
    PerformancePeriod,
    build_performance_center,
)
from services.wealth_timeline_contract import PortfolioSnapshotView


def _money(value: Optional[Decimal | float], currency: str) -> str:
    if value is None:
        return "—"
    amount = float(value)
    if str(currency).upper() == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def _pct(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.2f}%"


def _price(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.4f}".rstrip("0").rstrip(".")


def _selected_period() -> PerformancePeriod:
    labels = [row.value for row in PERIOD_OPTIONS]
    chosen = st.radio(
        "Dönem",
        labels,
        index=labels.index(PerformancePeriod.ALL.value),
        horizontal=True,
        key="wealth_performance_center_period",
    )
    return PerformancePeriod(chosen)


def _render_portfolio_summary(center: PerformanceCenterView) -> None:
    history = center.history
    if history is None:
        st.info(center.insufficient_reason or INSUFFICIENT_COPY)
        return
    currency = history.currency
    if not center.sufficient:
        st.info(center.insufficient_reason or INSUFFICIENT_COPY)
        if history.limitations:
            st.caption(" · ".join(str(item) for item in history.limitations))
        return
    quality = history.evidence_quality
    st.markdown(
        render_status_badge(
            quality.value,
            "success" if quality == PerformanceEvidenceQuality.COMPLETE else "warning",
        ),
        unsafe_allow_html=True,
    )
    if center.start_snapshot_at and center.end_snapshot_at:
        st.caption(
            f"Dönem: {format_date_dmy(center.start_snapshot_at)} → "
            f"{format_date_dmy(center.end_snapshot_at)}"
        )
    net_label = "—"
    if history.contribution_evidence_quality == ContributionEvidenceQuality.COMPLETE:
        net_label = _money(history.net_external_contributions, currency)
    elif history.contribution_evidence_quality == ContributionEvidenceQuality.UNAVAILABLE:
        net_label = CONTRIBUTION_HISTORY_UNAVAILABLE_COPY
    else:
        net_label = CONTRIBUTION_HISTORY_PARTIAL_COPY
    render_kpi_row(
        [
            ("Başlangıç değeri", _money(history.start_value, currency), None),
            ("Bitiş değeri", _money(history.end_value, currency), None),
            ("Net dış nakit akışı", net_label, None),
            (
                "Yatırım kazancı",
                _money(history.investment_gain_loss, currency)
                if history.investment_gain_loss is not None
                else "—",
                None,
            ),
        ]
    )
    if history.return_pct is None:
        st.caption("Getiri % gösterilmiyor — kanıt yetersiz veya dönem karşılaştırılabilir değil.")
    else:
        st.caption(f"Modified Dietz %: {float(history.return_pct):.2f}%")


def _render_best_worst(center: PerformanceCenterView) -> None:
    if not center.pair_comparable:
        return
    left, right = st.columns(2)
    with left:
        st.markdown(f"**{BEST_LABEL}**")
        if not center.best:
            st.caption("Karşılaştırılabilir ürün yok.")
        for row in center.best:
            st.write(f"{row.symbol} · {_pct(row.period_return)}")
    with right:
        st.markdown(f"**{WEAKEST_LABEL}**")
        if not center.weakest:
            st.caption("Karşılaştırılabilir ürün yok.")
        for row in center.weakest:
            st.write(f"{row.symbol} · {_pct(row.period_return)}")


def _render_product_table(center: PerformanceCenterView) -> None:
    st.markdown("**Ürün dönemi**")
    if not center.products:
        st.caption("Bu dönem için ürün fiyat kanıtı yok.")
        return
    comparable = [row for row in center.products if row.comparable]
    comparable.sort(key=lambda row: row.period_return or Decimal("-1"), reverse=True)
    incomplete = [row for row in center.products if not row.comparable]
    ordered = comparable + incomplete
    table = [
        {
            "Ürün": row.symbol,
            "Varlık sınıfı": row.asset_class,
            "Başlangıç fiyatı": _price(row.start_price),
            "Bitiş fiyatı": _price(row.end_price),
            "Dönem %": _pct(row.period_return) if row.comparable else "—",
            "Veri durumu": row.status,
        }
        for row in ordered
    ]
    st.dataframe(table, hide_index=True, use_container_width=True)


def _render_asset_classes(center: PerformanceCenterView) -> None:
    if not center.asset_classes:
        return
    st.markdown("**Varlık sınıfı**")
    for row in center.asset_classes:
        st.write(
            f"{row.asset_class} · {row.comparable_count} ürün · "
            f"ortalama fiyat getirisi {_pct(row.average_price_return)}"
        )


def _render_history_details(view: WealthHistoryView) -> None:
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
            else (
                CONTRIBUTION_HISTORY_UNAVAILABLE_COPY
                if view.contribution_evidence_quality == ContributionEvidenceQuality.UNAVAILABLE
                else CONTRIBUTION_HISTORY_PARTIAL_COPY
            ),
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


def render_wealth_history(
    view: WealthHistoryView,
    *,
    snapshots: Sequence[PortfolioSnapshotView] = (),
    transactions: Iterable[dict] = (),
    account_ids: Sequence[str] = (),
    contribution_reconciliations: Sequence[ContributionReconciliation] | None = None,
    portfolio_id: Optional[str] = None,
) -> Optional[PerformanceCenterView]:
    render_section_title(SECTION_TITLE)
    period = _selected_period()
    center = None
    if snapshots:
        center = build_performance_center(
            snapshots,
            period=period,
            transactions=transactions,
            account_ids=account_ids,
            contribution_reconciliations=contribution_reconciliations,
            portfolio_id=portfolio_id,
        )
        _render_portfolio_summary(center)
        _render_best_worst(center)
        _render_product_table(center)
        _render_asset_classes(center)
    else:
        if view.history_state == WealthHistoryState.ZERO:
            st.info(INSUFFICIENT_COPY)
        elif view.snapshot_count < 2:
            st.info(INSUFFICIENT_COPY)
        else:
            fallback = PerformanceCenterView(
                period=period,
                sufficient=view.history_state == WealthHistoryState.COMPARABLE,
                insufficient_reason=""
                if view.history_state == WealthHistoryState.COMPARABLE
                else INSUFFICIENT_COPY,
                history=view,
                start_snapshot_at=view.period_start,
                end_snapshot_at=view.period_end,
                products=(),
                best=(),
                weakest=(),
                asset_classes=(),
                pair_comparable=view.history_state == WealthHistoryState.COMPARABLE,
            )
            center = fallback
            _render_portfolio_summary(fallback)

    with st.expander(DETAILS_EXPANDER, expanded=False):
        _render_history_details(view)
    return center
