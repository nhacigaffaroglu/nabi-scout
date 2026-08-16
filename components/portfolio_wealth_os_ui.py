from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from services.asset_capability_contract import route_report_page
from services.fund_lookthrough_engine import PortfolioLookThroughView
from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView
from services.total_wealth_service import TotalWealthMetrics


def render_total_wealth_overview(
    metrics: TotalWealthMetrics,
    *,
    fx_supported: bool,
) -> None:
    st.markdown("### WEALTH OVERVIEW")
    cols = st.columns(4)
    total_label = f"{metrics.total_wealth:,.2f} {metrics.base_currency}" if metrics.total_wealth is not None else "Kısmi"
    cols[0].metric("Toplam Servet", total_label)
    cols[1].metric("Yatırım", f"{metrics.invested_assets:,.2f}")
    cols[2].metric("Nakit", f"{metrics.cash:,.2f}")
    cols[3].metric("Dönüştürülemeyen", f"{metrics.unconverted_value:,.2f}")
    if metrics.partial_total:
        st.warning(metrics.limitation or "Toplam servet kısmi — fiyat veya FX eksik.")
    if fx_supported:
        st.caption("FX: persist edilmiş kurlar kullanıldı (sayfa render = 0 uzak FX çağrısı).")
    else:
        st.caption("FX: dönüşüm kapsamı sınırlı veya kur yok.")


def render_asset_class_section(dashboard: PortfolioIntelligenceDashboardView) -> None:
    st.markdown("### ASSET CLASS")
    for row in dashboard.base.asset_class_allocation[:8]:
        st.progress(min(row.weight_pct / 100.0, 1.0), text=f"{row.label}: %{row.weight_pct:.1f}")


def render_currency_section(dashboard: PortfolioIntelligenceDashboardView) -> None:
    st.markdown("### CURRENCY")
    for row in dashboard.currency_allocation[:8]:
        st.caption(f"{row.label}: %{row.weight_pct:.1f} ({row.market_value:,.2f})")


def render_participation_section(dashboard: PortfolioIntelligenceDashboardView) -> None:
    st.markdown("### PARTICIPATION")
    cols = st.columns(4)
    cols[0].metric("Uygun", f"%{dashboard.participation_eligible_weight_pct:.1f}")
    cols[1].metric("Kontrol Et", f"%{dashboard.participation_review_weight_pct:.1f}")
    cols[2].metric("Uygun Değil", f"%{dashboard.participation_non_eligible_weight_pct:.1f}")
    cols[3].metric("Bilinmiyor", f"%{dashboard.participation_unknown_weight_pct:.1f}")


def render_research_coverage_section(dashboard: PortfolioIntelligenceDashboardView) -> None:
    st.markdown("### RESEARCH COVERAGE")
    st.metric("Araştırma kapsamı", f"%{dashboard.research_coverage_weight_pct:.1f}")
    st.caption(f"Değerlendirilmemiş ağırlık: %{dashboard.unresearched_weight_pct:.1f}")


def render_lookthrough_section(lookthrough: Optional[PortfolioLookThroughView]) -> None:
    st.markdown("### LOOK-THROUGH")
    if lookthrough is None:
        st.info("Look-through verisi yok.")
        return
    st.caption(lookthrough.limitation or "Ekonomik look-through (fon alt holding kanıtına dayalı).")
    tab_direct, tab_economic = st.tabs(["Varlık dağılımı", "Ekonomik look-through"])
    with tab_direct:
        for row in lookthrough.direct_allocation[:10]:
            st.caption(f"{row.label}: %{row.weight_pct:.1f}")
    with tab_economic:
        for row in lookthrough.economic_allocation[:10]:
            st.caption(f"{row.label}: %{row.weight_pct:.1f}")


def render_wealth_os_tabs(
    *,
    dashboard: PortfolioIntelligenceDashboardView,
    metrics: TotalWealthMetrics,
    lookthrough: Optional[PortfolioLookThroughView],
) -> None:
    tab_overview, tab_class, tab_inst, tab_fx, tab_part, tab_research, tab_lt = st.tabs(
        [
            "Overview",
            "Asset Class",
            "Institution",
            "Currency",
            "Participation",
            "Research",
            "Look-through",
        ]
    )
    with tab_overview:
        render_total_wealth_overview(metrics, fx_supported=dashboard.base.fx_supported)
    with tab_class:
        render_asset_class_section(dashboard)
    with tab_inst:
        st.markdown("### INSTITUTION")
        for row in dashboard.account_allocation[:10]:
            st.caption(f"{row.label}: %{row.weight_pct:.1f}")
    with tab_fx:
        render_currency_section(dashboard)
    with tab_part:
        render_participation_section(dashboard)
    with tab_research:
        render_research_coverage_section(dashboard)
    with tab_lt:
        render_lookthrough_section(lookthrough)


def render_asset_navigation_hint(symbol: str, asset_class: str) -> str:
    page = route_report_page(asset_class)
    if page == "company_report":
        return "Company Report"
    if page == "fund_report":
        return "Fund Intelligence"
    return "Asset Detail"
