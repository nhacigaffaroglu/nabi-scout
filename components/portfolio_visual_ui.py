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
    build_pl_by_position_chart,
    build_position_allocation_chart,
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


def render_allocation_dashboard(
    dashboard: PortfolioIntelligenceDashboardView,
    *,
    compact: bool = False,
) -> None:
    rows = list(dashboard.enriched_positions)
    if not rows:
        st.info("Görselleştirme için pozisyon bulunmuyor.")
        return

    if compact:
        c1, c2 = st.columns(2)
        with c1:
            st.altair_chart(build_position_allocation_chart(rows), use_container_width=True)
        with c2:
            st.altair_chart(
                build_allocation_bar_chart(
                    dashboard.sector_allocation,
                    title="Sektör dağılımı",
                ),
                use_container_width=True,
            )
        return

    render_chart_container("Dağılım analizi", subtitle="Fiyatlı pozisyonlar üzerinden")
    r1a, r1b = st.columns(2)
    with r1a:
        st.altair_chart(build_position_allocation_chart(rows), use_container_width=True)
    with r1b:
        st.altair_chart(
            build_allocation_bar_chart(dashboard.account_allocation, title="Kurum dağılımı"),
            use_container_width=True,
        )

    with st.expander("Detaylı dağılım", expanded=False):
        r2a, r2b = st.columns(2)
        with r2a:
            st.altair_chart(
                build_allocation_bar_chart(dashboard.sector_allocation, title="Sektör"),
                use_container_width=True,
            )
            st.altair_chart(
                build_allocation_bar_chart(dashboard.currency_allocation, title="Para birimi"),
                use_container_width=True,
            )
        with r2b:
            st.altair_chart(
                build_allocation_bar_chart(
                    dashboard.participation_allocation,
                    title="Katılım uygunluğu",
                    color_field="participation",
                ),
                use_container_width=True,
            )
            st.altair_chart(
                build_allocation_bar_chart(
                    dashboard.research_coverage_allocation,
                    title="Araştırma kapsamı",
                ),
                use_container_width=True,
            )

    st.altair_chart(build_pl_by_position_chart(rows), use_container_width=True)
