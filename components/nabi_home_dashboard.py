from __future__ import annotations

from components.nabi_design_system import (
    render_empty_state,
    render_page_header,
    render_section_title,
)
from components.portfolio_decision_center_ui import present_action_center
from components.wealth_brief_ui import compose_wealth_operating_views
from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from services.auth_service import get_current_user_id
from services.candidate_surface_service import filter_equity_candidate_surface
from services.canonical_current_valuation import (
    build_canonical_current_view,
    canonical_wealth_metrics,
)
from services.fx_rate_service import FxRateService
from services.nabi_dashboard_presentation import present_wealth_section
from services.participation_authority import overlay_candidate_rows
from services.nabi_today_presentation import (
    ALLOCATION_OPEN_LABEL,
    FIRSATLARI_GOR_LABEL,
    NEW_MONEY_ADVISORY,
    SECTION_DETAILS,
    SECTION_OPPORTUNITIES,
    SECTION_PERFORMANCE,
    SECTION_PORTFOLIO,
    SECTION_STATUS,
    WEALTH_OPEN_LABEL,
    WEALTH_PAGE,
    NabiTodayExecutive,
    build_nabi_today_executive,
)
from services.nabi_recommendation import present_recommendation_card
from services.opportunity_center_presentation import FIRSATLAR_PAGE
from services.portfolio_cockpit_presentation import build_portfolio_cockpit
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.wealth_core_service import WealthCoreService


def _load_candidates(client) -> list:
    try:
        return list(CandidateRepository(client).get_all(limit=500) or [])
    except Exception:
        return []


def _load_opportunity_candidates(client) -> list:
    try:
        rows = CandidateRepository(client).get_all(
            order_by="nabi_score",
            descending=True,
        ) or []
        return filter_equity_candidate_surface(rows)
    except Exception:
        return []


def render_nabi_today(today: NabiTodayExecutive) -> None:
    import streamlit as st

    rec = today.recommendation
    card = present_recommendation_card(rec)
    render_page_header(today.title, caption=card.today)
    if today.material_alert:
        st.warning(today.material_alert)

    render_section_title(card.section_title)
    with st.container(border=True):
        st.markdown(f"**Bugün:** {card.today}")
        st.caption(f"Neden: {card.why}")
        st.caption(f"Yeni para: {card.new_money}")
        if card.featured_symbol:
            st.caption(f"Öne çıkan fırsat: {card.featured_symbol}")
            if card.featured_why:
                st.caption(card.featured_why)
            if card.featured_fit_label:
                st.caption(f"Portföy uyumu: {card.featured_fit_label}")
            if card.alternative_symbol:
                st.caption(f"Alternative: {card.alternative_symbol}")
            if card.alternative_line:
                st.caption(card.alternative_line)
        else:
            st.caption(f"Fırsat: {card.opportunity}")
        if card.existing_vs_new:
            st.caption(card.existing_vs_new)
        st.caption(f"Risk: {card.risk}")
        st.caption(f"Güven: {card.confidence}")
        if today.decision_v3 is not None:
            st.caption(f"Final action: {today.decision_v3.final_action}")
            st.caption(f"Timing: {today.decision_v3.timing_state}")
            st.caption(
                "Portfolio fit: "
                + (today.decision_v3.portfolio_fit or "UNKNOWN")
            )
            if today.decision_v3.why:
                st.caption(f"Why / reason: {today.decision_v3.why}")
        cta_cols = st.columns(2)
        if cta_cols[0].button(card.wealth_cta, key="today_rec_wealth"):
            st.switch_page(WEALTH_PAGE)
        if cta_cols[1].button(card.firsatlar_cta, key="today_rec_firsatlar"):
            st.switch_page(FIRSATLAR_PAGE)

    render_section_title(SECTION_STATUS)
    cols = st.columns(len(today.kpis))
    for col, kpi in zip(cols, today.kpis):
        col.metric(kpi.label, kpi.value, kpi.caption)

    render_section_title(SECTION_OPPORTUNITIES)
    st.caption(today.opportunities.teaser)
    if today.opportunities.research_line:
        st.caption(today.opportunities.research_line)
    if st.button(FIRSATLARI_GOR_LABEL, key="today_go_opportunities", type="primary"):
        st.switch_page(FIRSATLAR_PAGE)

    render_section_title(SECTION_PORTFOLIO)
    port = today.portfolio
    if port.largest_symbol:
        st.markdown(
            f"**{port.largest_symbol}** · {port.largest_weight or '—'}"
        )
    if port.gain_usd:
        st.caption(f"Gerçekleşmemiş K/Z: {port.gain_usd} {port.gain_pct or ''}".strip())
    st.caption(f"2031 projeksiyon: {port.projected_label}")
    if port.reach_year:
        st.caption(f"Tahmini ulaşma: {port.reach_year}")
    if port.interpretation:
        st.caption(port.interpretation)
    if today.new_money.ready:
        st.caption(today.new_money.line)
        if today.new_money.symbols:
            st.caption("Öneri: " + " · ".join(today.new_money.symbols))
        st.caption(NEW_MONEY_ADVISORY)
        if st.button(ALLOCATION_OPEN_LABEL, key="today_go_allocation"):
            st.switch_page(WEALTH_PAGE)
    elif today.new_money.limitation:
        st.caption(today.new_money.limitation)
    if st.button(WEALTH_OPEN_LABEL, key="today_go_wealth"):
        st.switch_page(WEALTH_PAGE)

    render_section_title(SECTION_PERFORMANCE)
    perf = today.performance
    if perf.comparable:
        st.metric("Getiri", perf.period_return or "—")
        if perf.best:
            st.caption(f"En iyi: {perf.best}")
        if perf.weakest:
            st.caption(f"En zayıf: {perf.weakest}")
    else:
        st.info(perf.copy)

    with st.expander(SECTION_DETAILS, expanded=False):
        for line in today.details:
            st.caption(line)


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

    fx_service = FxRateService(client)
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
    try:
        snapshots = ParticipationAssessmentRepository(client).list_latest_by_symbol()
    except Exception:
        snapshots = {}
    opportunity_candidates = overlay_candidate_rows(
        _load_opportunity_candidates(client),
        snapshots,
    )
    operating = compose_wealth_operating_views(
        portfolio_view=base_view,
        wealth=wealth,
        accounts=accounts,
        candidates=candidates,
    )
    presented = present_action_center(operating.decision)
    wealth_section = present_wealth_section(
        metrics,
        coverage_pct=base_view.health.priced_position_coverage_pct,
        fx_service=fx_service,
        performance=operating.brief.performance,
    )
    cockpit = build_portfolio_cockpit(
        base_view,
        fx_service=fx_service,
        accounts=accounts,
        assets=wealth.list_assets(),
        positions=positions,
        candidates=candidates,
        performance=operating.performance,
    )
    today = build_nabi_today_executive(
        wealth=wealth_section,
        cockpit=cockpit,
        goal_dashboard=operating.goal_dashboard,
        presented_actions=presented,
        candidates=opportunity_candidates,
        new_money=operating.brief.new_money,
        performance=operating.performance,
        decision=operating.decision,
        allocation=operating.allocation,
        portfolio_view=base_view,
    )
    render_nabi_today(today)
