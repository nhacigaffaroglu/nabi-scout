from __future__ import annotations

import streamlit as st

from components.nabi_design_system import render_chart_container, render_section_title
from components.portfolio_intelligence_ui import render_attention_section
from services.portfolio_intelligence_charts import (
    build_allocation_bar_chart,
    build_pl_by_position_chart,
    build_portfolio_value_history_chart,
    build_position_allocation_chart,
    build_position_weight_chart,
)
from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView
from services.portfolio_performance_intelligence_service import PortfolioIntelligenceV13View
from services.total_wealth_service import TotalWealthMetrics
from services.wave3_intelligence_service import Wave3IntelligenceView


def render_portfolio_overview_tab(
    *,
    dashboard: PortfolioIntelligenceDashboardView,
    v13: PortfolioIntelligenceV13View,
    wealth_metrics: TotalWealthMetrics,
    wave3: Wave3IntelligenceView,
) -> None:
    rows = list(dashboard.enriched_positions)
    perf = v13.performance
    currency = dashboard.base.base_currency

    render_section_title(
        "Portföy Nabzı",
        description="Dağılım, yoğunlaşma ve güncel performans özeti.",
    )

    history = v13.performance_history.history_points
    if history:
        st.altair_chart(
            build_portfolio_value_history_chart(
                history,
                net_contributions=perf.net_contributions if perf.net_contributions else None,
                currency=currency,
            ),
            use_container_width=True,
        )
    else:
        st.info("Yeterli tarihsel snapshot bulunmuyor. Performans sekmesinden görüntü kaydedin.")

    c1, c2 = st.columns(2)
    with c1:
        if rows:
            st.altair_chart(build_position_allocation_chart(rows), use_container_width=True)
    with c2:
        st.altair_chart(
            build_allocation_bar_chart(
                dashboard.base.asset_class_allocation,
                title="Varlık sınıfı",
            ),
            use_container_width=True,
        )

    conc = wave3.construction.concentration
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Top-1", f"{conc.top1_weight_pct:.1f}%" if conc.top1_weight_pct else "—")
    m2.metric("Top-3", f"{conc.top3_weight_pct:.1f}%" if conc.top3_weight_pct else "—")
    m3.metric(
        "Katılım kapsamı",
        f"%{dashboard.participation_eligible_weight_pct:.0f}",
    )
    m4.metric(
        "Araştırma kapsamı",
        f"%{dashboard.research_coverage_weight_pct:.0f}",
    )

    render_chart_container("Pozisyon görünümü", subtitle="En büyük pozisyonlar ve K/Z katkısı")
    p1, p2 = st.columns(2)
    with p1:
        st.altair_chart(build_position_weight_chart(rows), use_container_width=True)
    with p2:
        st.altair_chart(build_pl_by_position_chart(rows), use_container_width=True)

    render_attention_section(dashboard)
