"""Wealth Command Center UI. Visual composition only; no writes or providers."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import pandas as pd
import streamlit as st

from components.nabi_design_system import (
    inject_nabi_theme,
    render_command_viewport,
    render_compact_priority_card,
    render_journey_milestones,
    render_section_title,
    render_valuation_chip,
)
from services.fx_rate_service import FxRateService
from services.portfolio_cockpit_presentation import COST_MISSING_COPY
from services.portfolio_intelligence_charts import (
    build_compact_allocation_chart,
    build_gain_rank_chart,
    build_holdings_treemap,
    build_institution_bar_chart,
    build_labeled_holdings_chart,
    build_portfolio_value_history_chart,
)
from services.portfolio_intelligence_contract import AllocationSlice, PortfolioIntelligenceView
from services.nabi_dashboard_presentation import format_usd_display
from services.wealth_command_center_presentation import (
    ALLOCATION_TITLE,
    COMMENTARY_TITLE,
    CONTRIBUTION_NOT_RETURN,
    COST_EXCLUDED_COPY,
    DETAILS_TITLE,
    FULL_HOLDINGS_LABEL,
    GAIN_KPI_CAPTION,
    GAIN_KPI_LABEL,
    HERO_LABEL,
    CURRENT_MONTHLY_CAPTION,
    HISTORY_TITLE,
    INCOMPARABLE_HISTORY,
    INCOMPARABLE_SCOPE,
    JOURNEY_TITLE,
    LOSERS_TITLE,
    OTHER_HOLDINGS_TEMPLATE,
    PERIOD_CHIP_LABELS,
    PRIORITY_OVERFLOW_TEMPLATE,
    PRIORITY_TITLE,
    REACH_YEAR_CAPTION,
    REQUIRED_MONTHLY_CAPTION,
    SYNTHESIS_PREFIX,
    TECHNICAL_HISTORY_TITLE,
    TOP_HOLDINGS_TITLE,
    TREEMAP_COLOR_LEGEND,
    TREEMAP_COLOR_LIMIT,
    TREEMAP_SIZE_LEGEND,
    TREEMAP_TITLE,
    UNREALIZED_NOTE,
    WINNERS_TITLE,
    WealthCommandCenterView,
    build_performance_strip,
    build_wealth_command_center,
    format_history_point_date,
    format_holdings_table_rows,
    list_comparable_periods,
    present_wealth_curve,
)
from services.wealth_history_service import WealthHistoryState
from services.wealth_performance_center_presentation import (
    PerformanceCenterView,
    PerformancePeriod,
    build_performance_center,
)


def _slices(rows) -> list[AllocationSlice]:
    return [
        AllocationSlice(
            key=row.key,
            label=row.label,
            market_value=row.market_value,
            weight_pct=row.weight_pct,
        )
        for row in rows
    ]


def _quiet(message: str) -> None:
    st.caption(message)


def _render_priority(view: WealthCommandCenterView) -> None:
    render_section_title(PRIORITY_TITLE)
    focus = view.priority_focus
    if focus.primary is None:
        _quiet(view.priority.empty_copy)
        return
    item = focus.primary
    render_compact_priority_card(
        severity=item.severity,
        title=item.title,
        current_metric=focus.current_metric,
        required_metric=focus.required_metric,
        actions=list(focus.action_labels),
    )
    if focus.overflow_count:
        with st.expander(
            PRIORITY_OVERFLOW_TEMPLATE.format(count=focus.overflow_count),
            expanded=False,
        ):
            for extra in focus.overflow_items:
                st.markdown(f"**{extra.title}**")
                st.caption(extra.explanation)


def _render_commentary(view: WealthCommandCenterView) -> None:
    commentary = view.commentary
    if not commentary.insights and not commentary.synthesis:
        return
    render_section_title(COMMENTARY_TITLE)
    bullets = "".join(f"<li>{line}</li>" for line in commentary.insights)
    chips = "".join(f'<span class="nabi-chip">{chip}</span>' for chip in commentary.chips)
    synthesis = ""
    if commentary.synthesis:
        synthesis = (
            f'<p class="nabi-commentary-synthesis">{SYNTHESIS_PREFIX} {commentary.synthesis}</p>'
        )
    chip_html = f'<div class="nabi-commentary-chips">{chips}</div>' if chips else ""
    st.markdown(
        f'<div class="nabi-commentary"><ul>{bullets}</ul>{synthesis}{chip_html}</div>',
        unsafe_allow_html=True,
    )


def _selected_performance(
    view: WealthCommandCenterView,
    *,
    snapshots: Sequence[Any],
    transactions: Sequence[Any],
    account_ids: Sequence[str],
    portfolio_id: str,
) -> PerformanceCenterView | None:
    periods = view.supported_periods or list_comparable_periods(snapshots)
    center = view.performance
    if not periods:
        return center
    labels = [PERIOD_CHIP_LABELS[period] for period in periods]
    preferred = PerformancePeriod.MONTHLY if PerformancePeriod.MONTHLY in periods else periods[0]
    default = (
        PERIOD_CHIP_LABELS[center.period]
        if center is not None and center.period in periods
        else PERIOD_CHIP_LABELS[preferred]
    )
    picked = st.pills("Dönem", labels, default=default, key="wealth_cc_period")
    period = next((item for item in periods if PERIOD_CHIP_LABELS[item] == picked), periods[0])
    if center is not None and center.period == period:
        return center
    return build_performance_center(
        snapshots,
        period=period,
        transactions=transactions,
        account_ids=account_ids,
        portfolio_id=portfolio_id or None,
    )


def render_wealth_command_center(
    *,
    portfolio_view: PortfolioIntelligenceView,
    wealth=None,
    accounts: Sequence[Mapping[str, Any]] = (),
    assets: Sequence[Mapping[str, Any]] = (),
    positions: Sequence[Mapping[str, Any]] = (),
    candidates: Sequence[Mapping[str, Any]] = (),
    snapshots: Sequence[Any] = (),
    transactions: Sequence[Any] = (),
    account_ids: Sequence[str] = (),
    portfolio_id: str = "",
    summary=None,
    liabilities: Sequence[Mapping[str, Any]] = (),
    command: Optional[WealthCommandCenterView] = None,
    performance: Optional[PerformanceCenterView] = None,
) -> WealthCommandCenterView:
    inject_nabi_theme()
    fx = FxRateService(getattr(wealth, "client", None)) if wealth is not None else None
    view = command or build_wealth_command_center(
        portfolio_view,
        wealth=wealth,
        accounts=accounts,
        assets=assets,
        positions=positions,
        candidates=candidates,
        snapshots=snapshots,
        transactions=transactions,
        account_ids=account_ids,
        portfolio_id=portfolio_id,
        fx_service=fx,
        performance=performance,
    )
    cockpit = view.cockpit
    hero = cockpit.hero
    viewport = view.viewport

    render_valuation_chip(viewport.valuation_chip)
    render_command_viewport(
        [
            (HERO_LABEL, viewport.wealth_usd, viewport.wealth_try),
            (
                GAIN_KPI_LABEL,
                viewport.gain_usd or "—",
                viewport.gain_pct if viewport.gain_usd else None,
            ),
            ("2031 İLERLEME", viewport.progress_compact, None),
            (
                "EN BÜYÜK POZİSYON",
                viewport.largest_symbol or "—",
                viewport.largest_weight,
            ),
        ]
    )
    if hero.try_limitation and viewport.wealth_try is None:
        _quiet(hero.try_limitation)
    if viewport.gain_usd is None:
        _quiet(COST_MISSING_COPY)
    else:
        _quiet(GAIN_KPI_CAPTION)

    _render_priority(view)
    _render_commentary(view)

    render_section_title(HISTORY_TITLE)
    curve = view.history_curve
    selected = None
    if view.show_period_controls:
        selected = _selected_performance(
            view,
            snapshots=snapshots,
            transactions=transactions,
            account_ids=account_ids,
            portfolio_id=portfolio_id,
        )
    strip = build_performance_strip(selected) if selected is not None and selected is not view.performance else view.performance_strip
    hist = selected.history if selected is not None else None
    if selected is not None and hist is not None:
        selected_curve = present_wealth_curve(hist.curve_points)
        if selected_curve.show_chart:
            curve = selected_curve
    if curve.show_chart and view.show_period_controls:
        net = (
            float(hist.net_external_contributions)
            if hist is not None and hist.net_external_contributions is not None
            else None
        )
        gain = (
            float(hist.investment_gain_loss)
            if hist is not None and hist.investment_gain_loss is not None
            else None
        )
        st.altair_chart(
            build_portfolio_value_history_chart(
                curve.comparable_points,
                net_contributions=net,
                investment_gain=gain if hist is not None and hist.history_state == WealthHistoryState.COMPARABLE else None,
                currency=portfolio_view.base_currency,
                height=360,
                title="",
            ),
            use_container_width=True,
        )
        _quiet(CONTRIBUTION_NOT_RETURN)
        if strip.comparable:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.caption("Dönem getirisi")
            c1.markdown(f"**{strip.period_return or '—'}**")
            c2.caption("Yatırım kazancı")
            c2.markdown(f"**{strip.investment_gain or '—'}**")
            c3.caption("Net katkı")
            c3.markdown(f"**{strip.net_contribution or '—'}**")
            c4.caption("En iyi ürün")
            c4.markdown(f"**{strip.best_product or '—'}**")
            c5.caption("En zayıf ürün")
            c5.markdown(f"**{strip.weakest_product or '—'}**")
        else:
            _quiet(strip.limitation or INCOMPARABLE_HISTORY)
    elif curve.mode == "one_point" and curve.latest_complete is not None:
        point = curve.latest_complete
        st.markdown(
            f'<div class="nabi-history-compact"><p>{curve.compact_copy}</p>'
            f"<p><strong>{format_usd_display(point.priced_market_value)}</strong></p>"
            f"<p>{format_history_point_date(point.captured_at)}</p></div>",
            unsafe_allow_html=True,
        )
    else:
        _quiet(curve.compact_copy or INCOMPARABLE_HISTORY)

    render_section_title(ALLOCATION_TITLE)
    a_col, i_col, m_col = st.columns(3)
    with a_col:
        st.caption("Varlık")
        if cockpit.asset_allocation:
            st.altair_chart(
                build_compact_allocation_chart(_slices(cockpit.asset_allocation)),
                use_container_width=True,
            )
        else:
            _quiet("Dağılım yok.")
    with i_col:
        st.caption("Kurum")
        inst = cockpit.institutions
        if inst.institutions:
            st.altair_chart(
                build_institution_bar_chart(
                    [
                        {
                            "label": row.name,
                            "market_value": row.total_value,
                            "weight_pct": row.portfolio_share_pct,
                        }
                        for row in inst.institutions
                    ],
                    title="",
                ),
                use_container_width=True,
            )
        else:
            _quiet("Kurum dağılımı yok.")
    with m_col:
        st.caption("Piyasa")
        if cockpit.market_allocation:
            st.altair_chart(
                build_compact_allocation_chart(_slices(cockpit.market_allocation)),
                use_container_width=True,
            )
        else:
            _quiet("Piyasa meta verisi yok.")

    render_section_title(TREEMAP_TITLE)
    if view.treemap:
        st.altair_chart(build_holdings_treemap(view.treemap, title=""), use_container_width=True)
        legend = f"{TREEMAP_SIZE_LEGEND} · {TREEMAP_COLOR_LEGEND}"
        if view.excluded_cost_count:
            legend = f"{legend} · {TREEMAP_COLOR_LIMIT}"
        _quiet(legend)
    else:
        _quiet("Harita için fiyatlı pozisyon yok.")

    render_section_title("KAZANANLAR / KAYBEDENLER", description=UNREALIZED_NOTE)
    if view.gain_available:
        wcol, lcol = st.columns(2)
        with wcol:
            st.markdown(f"**{WINNERS_TITLE}**")
            st.altair_chart(build_gain_rank_chart(view.winners), use_container_width=True)
        with lcol:
            st.markdown(f"**{LOSERS_TITLE}**")
            st.altair_chart(build_gain_rank_chart(view.losers), use_container_width=True)
        if view.excluded_cost_count:
            _quiet(COST_EXCLUDED_COPY)
    else:
        _quiet(view.gain_limitation or COST_MISSING_COPY)

    render_section_title(JOURNEY_TITLE)
    journey = view.journey
    render_journey_milestones(
        current_label="Bugün",
        current_value=journey.current_label,
        projected_label="2031 tahmini",
        projected_value=journey.projected_label,
        target_label="Hedef",
        target_value=journey.target_label,
        progress_pct=journey.progress_pct,
        attainment_pct=journey.attainment_pct,
    )
    j1, j2, j3 = st.columns(3)
    j1.caption(CURRENT_MONTHLY_CAPTION)
    j1.markdown(f"**{journey.configured_monthly_label}**")
    j2.caption(REQUIRED_MONTHLY_CAPTION)
    j2.markdown(f"**{journey.required_monthly_label}**")
    j3.caption(REACH_YEAR_CAPTION)
    j3.markdown(f"**{journey.earliest_label or '—'}**")
    if journey.summary_line:
        _quiet(journey.summary_line)

    render_section_title(TOP_HOLDINGS_TITLE)
    if view.top_holdings:
        st.altair_chart(build_labeled_holdings_chart(view.top_holdings), use_container_width=True)
        if view.other_holdings_count:
            _quiet(
                OTHER_HOLDINGS_TEMPLATE.format(
                    count=view.other_holdings_count,
                    weight=view.other_holdings_weight,
                )
            )
        with st.expander(FULL_HOLDINGS_LABEL, expanded=False):
            rows = format_holdings_table_rows(cockpit.holdings_table)
            if rows:
                st.dataframe(pd.DataFrame(list(rows)), use_container_width=True, hide_index=True)

    if cockpit.layer_available and cockpit.layer_rows:
        with st.expander("Hedef dağılım", expanded=False):
            for row in cockpit.layer_rows:
                target = f"%{row.target_pct:.1f}" if row.target_pct is not None else "—"
                st.caption(f"{row.label} · Fiili %{row.actual_pct:.1f} · Hedef {target} · {row.status}")

    with st.expander(DETAILS_TITLE, expanded=False):
        if summary is not None:
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Portföy", summary.portfolio_count)
            c2.metric("Hesap", summary.account_count)
            c3.metric("Varlık", summary.asset_count)
            c4.metric("Pozisyon", summary.position_count)
            c5.metric("Borç", summary.liability_count)
            c6.metric("İşlem", summary.transaction_count)
        evidence = cockpit.fx_evidence
        st.caption(
            f"USD/TRY {evidence.rate if evidence.rate is not None else '—'} · "
            f"{evidence.source or '—'} · {evidence.as_of or '—'} · {evidence.freshness}"
        )
        st.caption(
            "Pozisyonlar işlem defterinden türetilir. "
            "Alış/satış tek taraflıdır; nakit bakiyesi otomatik güncellenmez."
        )
        focus = view.priority_focus
        if focus.primary is not None:
            st.caption(focus.primary.explanation)
            for line in focus.primary.evidence:
                st.caption(line)
        hist_state = None
        if view.performance is not None and view.performance.history is not None:
            hist_state = view.performance.history
        if hist_state is not None:
            st.caption(
                f"Snapshot geçmişi: {hist_state.snapshot_count} nokta · "
                f"{hist_state.history_state.value} · "
                f"{'kısmi uç' if hist_state.latest_is_partial else 'tam uç'}"
            )
        if view.history_curve.technical_points:
            with st.expander(TECHNICAL_HISTORY_TITLE, expanded=False):
                _quiet(INCOMPARABLE_SCOPE)
                for point in view.history_curve.all_points:
                    scope = INCOMPARABLE_SCOPE if point.is_partial else "Tam kapsam"
                    st.caption(
                        f"{format_history_point_date(point.captured_at)} · "
                        f"{format_usd_display(point.priced_market_value)} · {scope}"
                    )
        if liabilities:
            for row in liabilities:
                st.caption(
                    f"{row.get('name')} · {row.get('liability_type')} · "
                    f"{row.get('principal')} {row.get('currency')}"
                )
    return view
