from __future__ import annotations

import streamlit as st

from components.nabi_design_system import render_chart_container, render_section_title
from components.portfolio_intelligence_ui import render_attention_section
from services.portfolio_intelligence_charts import (
    build_allocation_bar_chart,
    build_coverage_status_chart,
    build_portfolio_value_history_chart,
    build_top_concentration_chart,
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
    """Dominant wealth curve, then structure vs attention split."""
    perf = v13.performance
    currency = dashboard.base.base_currency
    conc = wave3.construction.concentration

    render_section_title(
        "Portföy / servet eğrisi",
        description="Persisted snapshot geçmişi — sahte katkı zaman serisi yok.",
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
        if perf.net_contributions:
            st.caption(
                "Kesikli çizgi: ömür boyu net katkı (skaler referans — geçmiş serisi değil)."
            )
    else:
        st.info("Yeterli tarihsel snapshot bulunmuyor. Performans sekmesinden görüntü kaydedin.")

    left, right = st.columns([3, 2])
    with left:
        render_chart_container(
            "Portföy yapısı",
            subtitle="Varlık sınıfı dağılımı — kısmi değerleme kapsamı korunur",
        )
        allocation = dashboard.base.asset_class_allocation
        if allocation:
            st.altair_chart(
                build_allocation_bar_chart(allocation, title="Varlık sınıfı"),
                use_container_width=True,
            )
            coverage = dashboard.base.health.priced_position_coverage_pct
            if coverage < 99.9:
                st.caption(f"Değerleme kapsamı: %{coverage:.0f} — grafik fiyatlı pozisyonları yansıtır.")
        else:
            st.info("Dağılım için yeterli fiyatlı pozisyon yok.")

        st.altair_chart(
            build_top_concentration_chart(
                top1_pct=conc.top1_weight_pct,
                top3_pct=conc.top3_weight_pct,
                top5_pct=conc.top5_weight_pct,
                top1_limit=12.0,
                top3_limit=40.0,
            ),
            use_container_width=True,
        )

    with right:
        render_chart_container(
            "Dikkat / ne değişti",
            subtitle="Yoğunlaşma, fiyat boşlukları ve izleme sinyalleri",
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
        render_attention_section(dashboard)
