from __future__ import annotations

import streamlit as st

from components.nabi_design_system import render_chart_container
from components.portfolio_management_ui import (
    render_account_management_panel,
    render_add_holding_form,
    render_create_account_form,
)
from components.portfolio_advanced_ui import render_cash_event_form
from services.portfolio_intelligence_charts import (
    build_allocation_bar_chart,
    build_coverage_status_chart,
    build_pl_by_position_chart,
)
from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView


def render_portfolio_management_expander(
    wealth,
    portfolio,
    accounts,
) -> None:
    with st.expander("⚙️ Portföyü Yönet", expanded=False):
        st.caption("Hesap, pozisyon ve nakit işlemleri — analitik katmandan ayrıdır.")
        render_create_account_form(wealth, str(portfolio["id"]))
        render_add_holding_form(wealth, portfolio, accounts)
        render_cash_event_form(wealth, portfolio, accounts)
        render_account_management_panel(wealth, portfolio, accounts)


_SECONDARY_ALLOCATION_OPTIONS = {
    "Kurum": "account_allocation",
    "Sektör": "sector_allocation",
    "Ülke": "country_allocation",
    "Para birimi": "currency_allocation",
}


def render_allocation_dashboard(
    dashboard: PortfolioIntelligenceDashboardView,
    *,
    compact: bool = False,
) -> None:
    rows = list(dashboard.enriched_positions)
    if not rows and not dashboard.base.asset_class_allocation:
        st.info("Görselleştirme için pozisyon bulunmuyor.")
        return

    render_chart_container(
        "Dağılım hiyerarşisi",
        subtitle="Birincil: varlık sınıfı · İkincil: seçilebilir boyutlar",
    )

    primary = dashboard.base.asset_class_allocation
    if primary:
        st.altair_chart(
            build_allocation_bar_chart(primary, title="Varlık sınıfı (birincil)"),
            use_container_width=True,
        )
        coverage = dashboard.base.health.priced_position_coverage_pct
        if coverage < 99.9:
            st.caption(
                f"Kısmi değerleme: %{coverage:.0f} fiyatlı — grafik tam portföyü temsil etmez."
            )
    else:
        st.info("Varlık sınıfı dağılımı için fiyatlı pozisyon gerekli.")

    if compact:
        return

    choice = st.radio(
        "İkincil dağılım",
        list(_SECONDARY_ALLOCATION_OPTIONS.keys()),
        horizontal=True,
        key="pi_secondary_allocation",
    )
    field = _SECONDARY_ALLOCATION_OPTIONS[choice]
    secondary = getattr(dashboard, field, ())
    st.altair_chart(
        build_allocation_bar_chart(secondary, title=choice),
        use_container_width=True,
    )

    st.altair_chart(
        build_coverage_status_chart(
            participation_pct=dashboard.participation_eligible_weight_pct,
            research_pct=dashboard.research_coverage_weight_pct,
            unknown_participation_pct=dashboard.participation_unknown_weight_pct,
            unresearched_pct=dashboard.unresearched_weight_pct,
        ),
        use_container_width=True,
    )

    if rows:
        st.altair_chart(build_pl_by_position_chart(rows), use_container_width=True)
