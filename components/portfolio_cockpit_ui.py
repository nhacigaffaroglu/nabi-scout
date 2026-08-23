"""Portfolio Cockpit UI. Visual composition only; no writes or providers."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import pandas as pd
import streamlit as st

from components.nabi_design_system import (
    render_executive_hero,
    render_kpi_row,
    render_section_title,
)
from services.fx_rate_service import FxRateService
from services.portfolio_cockpit_presentation import (
    BENCHMARK_UNAVAILABLE_COPY,
    COCKPIT_TITLE,
    COST_MISSING_COPY,
    LAYER_UNAVAILABLE_COPY,
    NO_HISTORY_COPY,
    PortfolioCockpitView,
    build_portfolio_cockpit,
)
from services.portfolio_intelligence_charts import (
    HoldingsChartRow,
    build_allocation_donut,
    build_holdings_weight_chart,
    build_portfolio_value_history_chart,
    build_target_vs_actual_chart,
)
from services.portfolio_intelligence_contract import AllocationSlice, PortfolioIntelligenceView
from services.wealth_comparison_chart import (
    build_benchmark_comparison_altair_chart,
    build_benchmark_comparison_chart_frame,
)
from services.wealth_history_service import WealthHistoryState
from services.wealth_performance_center_presentation import (
    INSUFFICIENT_COPY,
    PERIOD_OPTIONS,
    PerformanceCenterView,
    PerformancePeriod,
    build_performance_center,
)
from services.wealth_timeline_contract import BenchmarkComparisonView


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


def _render_fx_details(view: PortfolioCockpitView) -> None:
    evidence = view.fx_evidence
    with st.expander("Kur kanıtı", expanded=False):
        st.caption(f"{evidence.pair}")
        st.caption(f"Kur: {evidence.rate if evidence.rate is not None else '—'}")
        st.caption(f"Kaynak: {evidence.source or '—'}")
        st.caption(f"Tarih: {evidence.as_of or '—'}")
        st.caption(f"Tazelik: {evidence.freshness}")


def _performance_kwargs(
    snapshots: Sequence[Any],
    *,
    transactions: Sequence[Any] = (),
    account_ids: Sequence[str] = (),
    portfolio_id: str = "",
) -> dict:
    return {
        "transactions": transactions,
        "account_ids": account_ids,
        "portfolio_id": portfolio_id or None,
    }


def render_portfolio_cockpit(
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
    performance: Optional[PerformanceCenterView] = None,
    benchmark: Optional[BenchmarkComparisonView] = None,
    cockpit: Optional[PortfolioCockpitView] = None,
) -> PortfolioCockpitView:
    fx = FxRateService(getattr(wealth, "client", None)) if wealth is not None else None
    perf_kwargs = _performance_kwargs(
        snapshots,
        transactions=transactions,
        account_ids=account_ids,
        portfolio_id=portfolio_id,
    )
    center = performance
    if center is None and snapshots:
        center = build_performance_center(
            snapshots,
            period=PerformancePeriod.MONTHLY,
            **perf_kwargs,
        )
        if not center.sufficient:
            center = build_performance_center(
                snapshots,
                period=PerformancePeriod.ALL,
                **perf_kwargs,
            )
    view = cockpit or build_portfolio_cockpit(
        portfolio_view,
        fx_service=fx,
        accounts=accounts,
        assets=assets,
        positions=positions,
        candidates=candidates,
        performance=center,
        benchmark_available=bool(benchmark and benchmark.performance_comparable),
    )
    hero = view.hero
    render_section_title(COCKPIT_TITLE)
    render_executive_hero(
        primary_label="TOPLAM SERVET",
        primary_value=hero.usd_label,
        subtitle=hero.valuation_label,
        partial=not hero.valuation_complete,
        delta_lines=(
            [(hero.try_label, "info")] if hero.try_label else []
        ),
        partial_note=hero.try_limitation if not hero.try_label else None,
    )
    if hero.try_limitation and hero.try_label is None:
        st.caption(hero.try_limitation)
    render_kpi_row(
        [
            ("K/Z", hero.gain_usd_label or COST_MISSING_COPY, hero.gain_pct_label),
            ("Dönem", hero.period_label or NO_HISTORY_COPY, None),
            ("Pozisyon", str(hero.holdings_count), None),
            (
                "En büyük",
                f"{hero.largest_symbol or '—'} {hero.largest_weight_label or ''}".strip(),
                None,
            ),
        ]
    )
    _render_fx_details(view)

    render_section_title("Portföy değeri")
    history = center.history if center is not None else None
    if history is not None and history.curve_points:
        net = (
            float(history.net_external_contributions)
            if history.net_external_contributions is not None
            else None
        )
        st.altair_chart(
            build_portfolio_value_history_chart(
                history.curve_points,
                net_contributions=net,
                currency=portfolio_view.base_currency,
            ),
            use_container_width=True,
        )
        if history.history_state != WealthHistoryState.COMPARABLE:
            st.caption(" · ".join(history.limitations) or NO_HISTORY_COPY)
        st.caption("Katkılar getiri değildir; Modified Dietz dış nakit akışını ayırır.")
    else:
        st.info(NO_HISTORY_COPY)

    render_section_title("Karşılaştırma")
    if view.benchmark_available and benchmark is not None and benchmark.portfolio_normalized:
        frame = build_benchmark_comparison_chart_frame(benchmark.portfolio_normalized)
        st.altair_chart(build_benchmark_comparison_altair_chart(frame), use_container_width=True)
    else:
        st.caption(view.benchmark_limitation or BENCHMARK_UNAVAILABLE_COPY)

    left, right = st.columns(2)
    with left:
        render_section_title("Varlık dağılımı")
        if view.asset_allocation:
            st.altair_chart(
                build_allocation_donut(_slices(view.asset_allocation), title="Varlık sınıfı"),
                use_container_width=True,
            )
            for row in view.asset_allocation:
                st.caption(f"{row.label}: ${row.market_value:,.0f} · %{row.weight_pct:.1f}")
        else:
            st.caption("Dağılım için fiyatlı pozisyon yok.")
    with right:
        render_section_title("Piyasa / coğrafya")
        if view.market_allocation:
            st.altair_chart(
                build_allocation_donut(_slices(view.market_allocation), title="Piyasa"),
                use_container_width=True,
            )
        else:
            st.caption("Piyasa meta verisi yok; ticker'dan ülke türetilmedi.")

    render_section_title("Katman / hedef")
    if view.layer_available and view.layer_rows:
        st.altair_chart(
            build_target_vs_actual_chart(
                [
                    {
                        "label": row.label,
                        "actual_pct": row.actual_pct,
                        "target_pct": row.target_pct or 0.0,
                    }
                    for row in view.layer_rows
                ],
                title="Fiili vs hedef",
            ),
            use_container_width=True,
        )
        for row in view.layer_rows:
            st.caption(
                f"{row.label}: fiili %{row.actual_pct:.1f} · hedef "
                f"{'%' + format(row.target_pct, '.1f') if row.target_pct is not None else '—'} · {row.status}"
            )
    else:
        st.caption(view.layer_limitation or LAYER_UNAVAILABLE_COPY)

    render_section_title("Ağırlıklar")
    if view.holding_weights:
        st.altair_chart(
            build_holdings_weight_chart(
                [
                    HoldingsChartRow(
                        symbol=row.symbol,
                        weight_pct=row.weight_pct,
                        market_value=row.market_value,
                        unrealized_pl=None,
                        pl_pct=None,
                        price_available=True,
                    )
                    for row in view.holding_weights
                ]
            ),
            use_container_width=True,
        )
        with st.expander("Tümünü göster", expanded=False):
            for row in view.holding_weights:
                extra = f" · {row.gain_label}" if row.gain_label else ""
                st.caption(f"{row.symbol}: ${row.market_value:,.0f} · %{row.weight_pct:.1f}{extra}")

    render_section_title("Kazananlar / Kaybedenler")
    if view.gain_available:
        wcol, lcol = st.columns(2)
        with wcol:
            st.markdown("**Kazananlar**")
            for row in view.winners:
                st.caption(
                    f"{row.symbol}: {row.gain_usd:+,.0f} USD"
                    f"{f' ({row.gain_pct:+.1f}%)' if row.gain_pct is not None else ''}"
                )
        with lcol:
            st.markdown("**Kaybedenler**")
            for row in view.losers:
                st.caption(
                    f"{row.symbol}: {row.gain_usd:+,.0f} USD"
                    f"{f' ({row.gain_pct:+.1f}%)' if row.gain_pct is not None else ''}"
                )
    else:
        st.caption(COST_MISSING_COPY)

    render_section_title("Dönem performansı")
    supported = []
    if snapshots:
        for option in PERIOD_OPTIONS:
            probe = build_performance_center(snapshots, period=option, **perf_kwargs)
            if probe.sufficient:
                supported.append(option)
    labels = [row.value for row in (supported or PERIOD_OPTIONS)]
    chosen = st.radio("Dönem", labels, horizontal=True, key="cockpit_period")
    period = PerformancePeriod(chosen)
    period_view = (
        build_performance_center(snapshots, period=period, **perf_kwargs)
        if snapshots
        else center
    )
    if period_view is None or not period_view.sufficient:
        st.info((period_view.insufficient_reason if period_view else None) or INSUFFICIENT_COPY)
    else:
        hist = period_view.history
        if hist is not None and hist.return_pct is not None:
            st.metric("Portföy getirisi (Modified Dietz)", f"{float(hist.return_pct):.2f}%")
        if hist is not None and hist.investment_gain_loss is not None:
            st.caption(f"Yatırım K/Z: ${float(hist.investment_gain_loss):,.0f}")
        if hist is not None and hist.net_external_contributions is not None:
            st.caption(f"Dış nakit akışı: ${float(hist.net_external_contributions):,.0f}")
        if period_view.best:
            best = period_view.best[0]
            st.caption(
                f"En iyi: {best.symbol}"
                + (
                    f" {float(best.period_return) * 100:.1f}%"
                    if best.period_return is not None
                    else ""
                )
            )
        if period_view.weakest:
            weak = period_view.weakest[0]
            st.caption(
                f"En zayıf: {weak.symbol}"
                + (
                    f" {float(weak.period_return) * 100:.1f}%"
                    if weak.period_return is not None
                    else ""
                )
            )
        st.caption("Dış katkılar getiriye karıştırılmaz.")

    render_section_title("Kurumlar")
    inst = view.institutions
    if inst.institutions:
        for row in inst.institutions:
            st.caption(
                f"{row.name}: ${row.total_value:,.0f} · %{row.portfolio_share_pct:.1f}"
            )
    else:
        st.caption("Kurum dağılımı yok.")

    render_section_title("Pozisyonlar")
    if view.holdings_table:
        frame = pd.DataFrame(
            [
                {
                    "Sembol": row.symbol,
                    "Varlık": row.asset_type,
                    "Kurum": row.institution,
                    "Adet": row.quantity,
                    "Güncel Fiyat": row.current_price,
                    "Para Birimi": row.currency,
                    "Piyasa Değeri": row.market_value,
                    "Portföy Payı": row.weight_pct,
                    "Maliyet": COST_MISSING_COPY if row.cost_missing else row.cost_basis,
                    "K/Z": "—" if row.cost_missing else row.unrealized_pl,
                    "K/Z %": "—" if row.cost_missing else row.pl_pct,
                    "NABI Score": "—" if row.nabi_score is None else row.nabi_score,
                    "Karar": row.decision,
                }
                for row in view.holdings_table
            ]
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)
    return view
