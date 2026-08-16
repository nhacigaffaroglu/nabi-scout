from __future__ import annotations

from typing import Optional

import streamlit as st

from components.nabi_design_system import (
    render_data_quality_level,
    render_executive_hero,
    render_insight_list,
    render_secondary_kpi_row,
    render_status_badge,
)
from services.data_quality_center_service import build_data_quality_summary
from services.nabi_visual_insights import build_portfolio_insights
from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView
from services.portfolio_performance_intelligence_service import PortfolioIntelligenceV13View
from services.total_wealth_service import TotalWealthMetrics
from services.wave3_intelligence_service import Wave3IntelligenceView


def _money(value: Optional[float], currency: str, *, partial: bool = False) -> str:
    if value is None:
        return "—"
    suffix = "*" if partial else ""
    return f"{value:,.0f} {currency}{suffix}"


def _pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%" if abs(value) < 1000 else f"{value:,.2f}%"


def render_portfolio_executive_hero(
    *,
    dashboard: PortfolioIntelligenceDashboardView,
    v13: PortfolioIntelligenceV13View,
    wealth_metrics: TotalWealthMetrics,
    wave3: Optional[Wave3IntelligenceView] = None,
) -> None:
    base = dashboard.base
    perf = v13.performance
    currency = base.base_currency
    partial = base.unpriced_position_count > 0 or wealth_metrics.partial_total

    primary_value = (
        _money(wealth_metrics.total_wealth, currency, partial=partial)
        if wealth_metrics.total_wealth is not None
        else _money(base.priced_total_market_value, currency, partial=partial)
    )
    partial_note = None
    if partial:
        partial_note = (
            f"{base.unpriced_position_count} pozisyon güncel fiyat olmadığı için "
            f"toplam dışında bırakıldı. Değerleme kapsamı: "
            f"%{base.health.priced_position_coverage_pct:.0f}."
        )

    render_executive_hero(
        primary_label="Toplam Servet / Portföy Değeri",
        primary_value=primary_value.replace(f" {currency}", "").replace("*", ""),
        subtitle=f"Baz para: {currency} · Fiyat kaynağı: {base.price_provider or 'persisted'}",
        partial=partial,
        partial_note=partial_note,
    )

    coverage_pct = base.health.priced_position_coverage_pct
    render_secondary_kpi_row(
        [
            ("Yatırılan sermaye", _money(perf.invested_capital, currency), None),
            ("Yatırım getirisi", _money(perf.investment_gain, currency), None),
            ("Getiri", _pct(perf.return_pct), None),
            ("Nakit", _money(wealth_metrics.cash, currency), None),
            ("Değerleme kapsamı", f"%{coverage_pct:.0f}", None),
        ]
    )

    quality = build_data_quality_summary(dashboard)
    if quality.partial_valuation or quality.issues:
        level = "PARTIAL" if quality.partial_valuation else "COMPLETE"
        detail = quality.issues[0].detail if quality.issues else "Persisted veriler kullanılıyor."
        render_data_quality_level(level, detail)

    attention_count = len(dashboard.attention_items)
    if attention_count:
        st.markdown(
            render_status_badge(f"{attention_count} dikkat maddesi", "warning"),
            unsafe_allow_html=True,
        )

    insights = build_portfolio_insights(dashboard=dashboard, v13=v13, wave3=wave3)
    render_insight_list(insights)
