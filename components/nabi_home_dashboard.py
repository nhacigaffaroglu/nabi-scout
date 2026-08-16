from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from components.nabi_design_system import render_kpi_row, render_section_title
from services.auth_service import get_current_user_id
from services.candidate_price_service import CandidatePriceService
from services.daily_portfolio_brief_service import build_daily_portfolio_brief
from services.data_quality_center_service import build_data_quality_summary
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.system_health_service import SystemHealthService
from services.total_wealth_service import compute_total_wealth_metrics
from services.wealth_core_service import WealthCoreService


def render_nabi_home_executive(client) -> None:
    user_id = get_current_user_id(client)
    if not user_id:
        st.info("Portföy özeti için oturum açın.")
        return

    wealth = WealthCoreService(client, user_id)
    portfolio = wealth.ensure_default_portfolio()
    positions = wealth.list_positions()
    if not positions:
        st.info("**Portföyün boş** — ilk yatırım aracını Portföy Zekâsı'ndan ekleyebilirsin.")
        if st.button("Portföy Zekâsı'na git", key="home_go_portfolio"):
            st.switch_page("pages/11_Portfolio_Intelligence.py")
        return

    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(wealth, price_service, nabi_client=client)
    base_view = intelligence.build_view(portfolio, enrich_nabi=False)
    dashboard = build_portfolio_intelligence_dashboard(base_view, accounts_by_id={})
    monitor = MonitorIntelligenceService(client, user_id)
    brief = build_daily_portfolio_brief(portfolio=portfolio, dashboard=dashboard, monitor=monitor)
    metrics = compute_total_wealth_metrics(
        base_view,
        participation_covered_pct=dashboard.participation_eligible_weight_pct,
        research_covered_pct=dashboard.research_coverage_weight_pct,
    )
    quality = build_data_quality_summary(dashboard)

    render_section_title("PORTFÖYÜM")
    total_label = (
        f"{metrics.total_wealth:,.0f} {metrics.base_currency}"
        if metrics.total_wealth is not None
        else "Kısmi"
    )
    render_kpi_row(
        [
            ("Toplam Servet", total_label, metrics.limitation or None),
            ("Nakit", f"{metrics.cash:,.0f}", None),
            ("Katılım kapsamı", f"%{dashboard.participation_eligible_weight_pct:.0f}", None),
            ("Araştırma kapsamı", f"%{dashboard.research_coverage_weight_pct:.0f}", None),
        ]
    )
    if metrics.partial_total:
        st.caption(metrics.limitation)

    render_section_title("BUGÜN")
    st.caption(
        f"Monitör olayları: {brief.event_counts.get('total', 0)} · "
        f"Yüksek/Kritik: {brief.event_counts.get('high_critical', 0)} · "
        f"Wealth olayları: {brief.event_counts.get('wealth', 0)}"
    )
    if brief.unresolved_attention:
        for item in brief.unresolved_attention[:3]:
            st.markdown(f"- {item}")
    else:
        st.caption("Şu anda incelemen gereken yeni yüksek öncelikli olay yok.")

    if quality.issues:
        render_section_title("VERİ / SİSTEM")
        for issue in quality.issues[:4]:
            st.caption(f"{issue.label}: {issue.detail}")

    health = SystemHealthService(client)
    stale_jobs = [
        row.label
        for row in health.list_automation_health()
        if row.status not in {None, "COMPLETED"}
    ]
    if stale_jobs:
        st.caption(f"Otomasyon uyarısı: {', '.join(stale_jobs[:3])}")

    nav_cols = st.columns(3)
    with nav_cols[0]:
        if st.button("Portföy Zekâsı", key="home_nav_portfolio"):
            st.switch_page("pages/11_Portfolio_Intelligence.py")
    with nav_cols[1]:
        if st.button("Monitör", key="home_nav_monitor"):
            st.switch_page("pages/12_Monitor.py")
    with nav_cols[2]:
        if st.button("Araştırma Monitörü", key="home_nav_research_monitor"):
            st.switch_page("pages/3_Research_Monitor.py")
