from __future__ import annotations

from components.nabi_design_system import (
    render_empty_state,
    render_executive_hero,
    render_section_title,
    render_status_badge,
)
from components.portfolio_decision_center_ui import present_action_center
from components.wealth_brief_ui import compose_wealth_operating_views
from repositories.candidate_repository import CandidateRepository
from services.auth_service import get_current_user_id
from services.canonical_current_valuation import (
    build_canonical_current_view,
    canonical_wealth_metrics,
)
from services.fx_rate_service import FxRateService
from services.nabi_dashboard_presentation import (
    SECTION_GOAL,
    SECTION_NEW_MONEY,
    SECTION_OPPORTUNITIES,
    SECTION_PERFORMANCE,
    SECTION_PORTFOLIO,
    SECTION_PRIORITY,
    NabiTodayDashboard,
    build_nabi_today_dashboard,
)
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.wealth_core_service import WealthCoreService


def _load_candidates(client) -> list:
    try:
        return list(CandidateRepository(client).get_all(limit=500) or [])
    except Exception:
        return []


def render_nabi_today(today: NabiTodayDashboard) -> None:
    import streamlit as st

    wealth = today.wealth
    try_line = (
        f"≈ {wealth.try_equivalent.label}"
        if wealth.try_equivalent.available and wealth.try_equivalent.label
        else None
    )
    subtitle_parts = [wealth.valuation_label]
    if wealth.coverage_pct is not None:
        subtitle_parts.append(f"Kapsam %{wealth.coverage_pct:.0f}")
    render_executive_hero(
        primary_label=f"{today.title} · TOPLAM SERVET",
        primary_value=wealth.usd_label,
        subtitle=" · ".join(subtitle_parts),
        partial=not wealth.valuation_complete,
        delta_lines=[(try_line, "info")] if try_line else [],
        partial_note=wealth.limitation if not wealth.valuation_complete else None,
    )
    if try_line is None and wealth.try_equivalent.limitation:
        st.caption(wealth.try_equivalent.limitation)
    with st.expander("Kur kanıtı", expanded=False):
        st.caption(f"USD/TRY · {wealth.try_equivalent.rate or '—'}")
        st.caption(f"Tarih: {wealth.try_equivalent.rate_date or '—'}")
    if wealth.change_label:
        st.caption(wealth.change_label)

    render_section_title(SECTION_GOAL, description="Hedef Merkezi özeti")
    goal = today.goal
    cols = st.columns(3)
    cols[0].metric("Hedef", goal.target_label)
    cols[1].metric("İlerleme", goal.current_progress)
    cols[2].metric("2031 projeksiyon", goal.projected_wealth_label)
    st.caption(f"Ulaşma: {goal.attainment_label}")
    st.caption(
        f"Kayıtlı katkı: {goal.configured_monthly_label} · "
        f"Gereken: {goal.required_monthly_label}"
    )
    if goal.target_date_alternative:
        st.caption(f"Alternatif ulaşım: {goal.target_date_alternative}")
    st.caption(goal.status_copy)
    if st.button("2031 Hedef Merkezi", key="today_go_goal"):
        st.switch_page("pages/10_Wealth.py")

    render_section_title(SECTION_PRIORITY)
    if today.priority.healthy or not today.priority.items:
        st.info(today.priority.empty_copy)
    else:
        for item in today.priority.items:
            with st.container(border=True):
                st.markdown(
                    render_status_badge(item.severity, "warning"),
                    unsafe_allow_html=True,
                )
                st.markdown(f"**{item.title}**")
                st.caption(item.explanation)
                if item.options:
                    st.caption("Seçenekler: " + " · ".join(item.options[:3]))
    if st.button("Karar Merkezi", key="today_go_decision"):
        st.switch_page("pages/11_Portfolio_Intelligence.py")

    render_section_title(SECTION_PORTFOLIO)
    port = today.portfolio
    if port.holdings:
        for row in port.holdings:
            st.markdown(f"**{row.symbol}** · {row.weight_label} · {row.value_label}")
    if port.allocation_lines:
        st.caption(" · ".join(port.allocation_lines))
    if port.concentration_label:
        st.caption(port.concentration_label)
    for warning in port.imbalance_warnings:
        st.warning(warning)
    if not port.holdings and not port.allocation_lines:
        st.caption("Portföy özeti için fiyatlı pozisyon yok.")

    render_section_title(SECTION_OPPORTUNITIES)
    if not today.opportunities.rows:
        st.info(today.opportunities.empty_copy)
    else:
        for index, row in enumerate(today.opportunities.rows):
            score = f"{row.nabi_score:.1f}" if row.nabi_score is not None else "—"
            st.markdown(f"**{row.symbol}** · {score} · {row.decision}")
            if row.reason:
                st.caption(row.reason)
            if st.button("Company Report", key=f"today_opp_{row.symbol}_{index}"):
                st.session_state["company_report_candidate"] = {"symbol": row.symbol}
                st.query_params["symbol"] = row.symbol
                st.switch_page("pages/4_Company_Report.py")

    render_section_title(SECTION_NEW_MONEY)
    st.caption(today.new_money_lead)
    money = today.new_money
    if money.unavailable_reason and not money.recommendations:
        st.caption(money.unavailable_reason)
    else:
        for row in money.recommendations:
            st.markdown(f"**{row.symbol}** · {row.amount_label} · {row.kind_label}")
            st.caption(row.reason)
        st.caption(f"Dağıtılan: {money.allocated_label} · Nakit kalan: {money.residual_label}")
    st.caption("Danışmanlık özetidir; işlem uygulanmaz.")

    render_section_title(SECTION_PERFORMANCE)
    perf = today.performance
    if perf.limitation and not perf.return_label:
        st.info(perf.limitation)
    else:
        st.metric(perf.period_label, perf.return_label or "—")
        if perf.best_label:
            st.caption(f"En iyi: {perf.best_label}")
        if perf.weakest_label:
            st.caption(f"En zayıf: {perf.weakest_label}")
        if perf.limitation:
            st.caption(perf.limitation)
    if st.button("Performans Merkezi", key="today_go_performance"):
        st.switch_page("pages/10_Wealth.py")


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

    base_view = build_canonical_current_view(
        wealth,
        enrich_nabi=False,
        portfolio=portfolio,
    )
    dashboard = build_portfolio_intelligence_dashboard(base_view, accounts_by_id={})
    metrics = canonical_wealth_metrics(
        base_view,
        participation_covered_pct=dashboard.participation_eligible_weight_pct,
        research_covered_pct=dashboard.research_coverage_weight_pct,
    )
    accounts = wealth.list_accounts()
    candidates = _load_candidates(client)
    operating = compose_wealth_operating_views(
        portfolio_view=base_view,
        wealth=wealth,
        accounts=accounts,
        candidates=candidates,
    )
    presented = present_action_center(operating.decision)
    today = build_nabi_today_dashboard(
        metrics=metrics,
        coverage_pct=base_view.health.priced_position_coverage_pct,
        fx_service=FxRateService(client),
        pi_dashboard=dashboard,
        brief=operating.brief,
        presented_actions=presented,
        candidates=candidates,
    )
    render_nabi_today(today)

    nav_cols = st.columns(3)
    with nav_cols[0]:
        if st.button("Portföy Zekâsı", key="home_nav_portfolio", type="primary"):
            st.switch_page("pages/11_Portfolio_Intelligence.py")
    with nav_cols[1]:
        if st.button("Wealth", key="home_nav_wealth"):
            st.switch_page("pages/10_Wealth.py")
    with nav_cols[2]:
        if st.button("Aday Havuzu", key="home_nav_candidates"):
            st.switch_page("pages/2_Aday_Havuzu.py")
