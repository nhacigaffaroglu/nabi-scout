from __future__ import annotations

from components.nabi_design_system import (
    render_empty_state,
    render_executive_hero,
    render_insight_list,
    render_section_title,
    render_secondary_kpi_row,
    render_status_badge,
)
from services.auth_service import get_current_user_id
from services.candidate_price_service import CandidatePriceService
from services.daily_portfolio_brief_service import build_daily_portfolio_brief
from services.data_quality_center_service import build_data_quality_summary
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.nabi_visual_insights import build_portfolio_insights
from services.portfolio_intelligence_charts import build_portfolio_value_history_chart
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.system_health_service import SystemHealthService
from services.total_wealth_service import compute_total_wealth_metrics
from services.wealth_core_service import WealthCoreService
from services.wealth_timeline_service import WealthTimelineService


def _streamlit_runtime_active() -> bool:
    try:
        from streamlit.runtime.scriptrunner_utils import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def render_nabi_home_executive(client) -> None:
    import streamlit as st

    user_id = get_current_user_id(client)
    if not user_id:
        st.info("Portföy özeti için oturum açın.")
        return

    wealth = WealthCoreService(client, user_id)
    portfolio = wealth.ensure_default_portfolio()
    positions = wealth.list_positions()
    if not positions:
        render_empty_state(
            "Portföyün boş",
            "İlk yatırım aracını Portföy Zekâsı'ndan ekleyebilirsin.",
            action_label="Portföy Zekâsı → Portföyü Yönet",
        )
        if st.button("Portföy Zekâsı'na git", key="home_go_portfolio", type="primary"):
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
    timeline = WealthTimelineService(wealth)
    perf_history = timeline.build_performance_view(portfolio).history_points

    partial = metrics.partial_total or base_view.unpriced_position_count > 0
    currency = metrics.base_currency
    total_display = (
        f"{metrics.total_wealth:,.0f}"
        if metrics.total_wealth is not None
        else f"{base_view.priced_total_market_value:,.0f}"
    )

    render_executive_hero(
        primary_label="NABI — Toplam Servet",
        primary_value=total_display,
        subtitle=f"{currency} · Değerleme kapsamı %{base_view.health.priced_position_coverage_pct:.0f}",
        partial=partial,
        partial_note=metrics.limitation if partial else None,
    )

    render_secondary_kpi_row(
        [
            ("Nakit", f"{metrics.cash:,.0f} {currency}", None),
            ("Katılım kapsamı", f"%{dashboard.participation_eligible_weight_pct:.0f}", None),
            ("Araştırma kapsamı", f"%{dashboard.research_coverage_weight_pct:.0f}", None),
            (
                "Monitör",
                f"{brief.event_counts.get('high_critical', 0)} yüksek/kritik",
                None,
            ),
        ]
    )

    if perf_history and _streamlit_runtime_active():
        st.altair_chart(
            build_portfolio_value_history_chart(perf_history, currency=currency),
            use_container_width=True,
        )

    insights = build_portfolio_insights(dashboard=dashboard)
    render_insight_list(insights)

    render_section_title("BUGÜN", description="Günlük özet — persisted monitör olayları")
    if brief.unresolved_attention:
        for item in brief.unresolved_attention[:4]:
            st.markdown(f"- {item}")
    else:
        st.caption("Şu anda incelemen gereken yeni yüksek öncelikli olay yok.")

    if quality.issues:
        render_section_title("VERİ KALİTESİ")
        for issue in quality.issues[:3]:
            st.markdown(
                render_status_badge(issue.label, "warning" if issue.severity == "watch" else "info"),
                unsafe_allow_html=True,
            )
            st.caption(issue.detail)

    health = SystemHealthService(client)
    stale_jobs = [
        row.label
        for row in health.list_automation_health()
        if row.status not in {None, "COMPLETED"}
    ]
    if stale_jobs:
        st.caption(f"Otomasyon: {', '.join(stale_jobs[:3])}")

    nav_cols = st.columns(3)
    with nav_cols[0]:
        if st.button("Portföy Zekâsı", key="home_nav_portfolio", type="primary"):
            st.switch_page("pages/11_Portfolio_Intelligence.py")
    with nav_cols[1]:
        if st.button("Monitör", key="home_nav_monitor"):
            st.switch_page("pages/12_Monitor.py")
    with nav_cols[2]:
        if st.button("Araştırma Monitörü", key="home_nav_research_monitor"):
            st.switch_page("pages/3_Research_Monitor.py")
