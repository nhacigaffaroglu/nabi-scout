"""NABI Wealth Brief UI. Advisory landing summary; no writes or providers."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional, Sequence

import streamlit as st

from components.nabi_design_system import (
    render_kpi_row,
    render_section_title,
    render_status_badge,
)
from services.portfolio_decision_intelligence import build_portfolio_decision
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_brief_presentation import (
    BRIEF_TITLE,
    DETAILS_EXPANDER,
    SECTION_GOAL,
    SECTION_NEW_MONEY,
    SECTION_PERFORMANCE,
    SECTION_PRIORITY,
    SECTION_TODAY,
    WealthBrief,
    build_wealth_brief,
)
from services.wealth_contribution_intelligence import build_contribution_intelligence
from services.wealth_external_cash_flow import (
    contribution_reconciliations_for_wealth,
    load_contribution_tracking_start,
)
from services.wealth_goal_center_presentation import build_goal_center_dashboard
from services.wealth_institution_center_presentation import present_institution_center
from components.wealth_purification_zakat_ui import try_session_result
from services.wealth_goal_models import (
    current_wealth_from_portfolio_view,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_goal_planning import planning_conversion
from services.wealth_new_money_allocation import allocate_new_money
from services.wealth_performance_center_presentation import (
    PerformancePeriod,
    build_performance_center,
)
from services.wealth_planning_fx import load_planning_fx_schedule
from services.wealth_projection_engine import project_wealth_goal_scenarios


def _load_policy(wealth, portfolio_id: str):
    client = getattr(wealth, "client", None)
    user_id = getattr(wealth, "user_id", None)
    if client is None or not user_id or not portfolio_id:
        return None
    from services.portfolio_allocation_policy_service import PortfolioAllocationPolicyService

    try:
        return PortfolioAllocationPolicyService(client, user_id).get_policy(str(portfolio_id))
    except Exception:
        return None


def _load_candidates(wealth) -> list:
    client = getattr(wealth, "client", None)
    if client is None:
        return []
    from repositories.candidate_repository import CandidateRepository

    try:
        return list(CandidateRepository(client).get_all(limit=500) or [])
    except Exception:
        return []


def _load_snapshots(wealth, portfolio_id: str):
    if wealth is None or not portfolio_id:
        return []
    from services.wealth_timeline_service import WealthTimelineService

    try:
        return WealthTimelineService(wealth).list_snapshots(str(portfolio_id), limit=50)
    except Exception:
        return []


def compose_wealth_brief(
    *,
    portfolio_view: PortfolioIntelligenceView,
    wealth,
    accounts: Sequence[Dict[str, Any]] = (),
    as_of: Optional[date] = None,
    policy=None,
    candidates=None,
    snapshots=None,
    allocation=None,
    decision=None,
    purification_zakat=None,
) -> WealthBrief:
    as_of_date = as_of or date.today()
    goal = default_wealth_goal_2031()
    plan = default_contribution_plan()
    assets = wealth.list_assets() if wealth is not None else []
    positions = wealth.list_positions() if wealth is not None else []
    snapshot = current_wealth_from_portfolio_view(
        portfolio_view,
        goal_currency=goal.currency,
        positions=positions,
        assets=assets,
    )
    portfolio_id = str(getattr(portfolio_view, "portfolio_id", "") or "")
    tracking_start = (
        load_contribution_tracking_start(wealth, portfolio_id) if wealth is not None else None
    )
    fx_schedule = (
        load_planning_fx_schedule(wealth, portfolio_id) if wealth is not None else None
    )
    if fx_schedule is None:
        from services.wealth_planning_fx import PlanningFxSchedule

        fx_schedule = PlanningFxSchedule()
    bands = project_wealth_goal_scenarios(
        goal=goal,
        as_of_date=as_of_date,
        current=snapshot,
        contribution_plan=plan,
        fx_schedule=fx_schedule,
    )
    txns = wealth.list_transactions(limit=2000) if wealth is not None else []
    account_ids = [str(row.get("id") or "") for row in accounts]
    recons = (
        contribution_reconciliations_for_wealth(wealth, portfolio_id)
        if wealth is not None
        else ()
    )
    intelligence = build_contribution_intelligence(
        as_of_date=as_of_date,
        current=snapshot,
        transactions=txns,
        account_ids=account_ids,
        plan=plan,
        goal=goal,
        contribution_reconciliations=recons,
        portfolio_id=portfolio_id or None,
        contribution_tracking_start=tracking_start,
        fx_schedule=fx_schedule,
    )
    decision_view = decision or build_portfolio_decision(
        portfolio_view,
        as_of_date=as_of_date,
        goal=goal,
        plan=plan,
        current_wealth=snapshot,
        contribution=intelligence,
        transactions=txns,
        account_ids=account_ids,
        positions=positions,
        assets=assets,
        contribution_reconciliations=recons,
        contribution_tracking_start=tracking_start,
        fx_schedule=fx_schedule,
    )
    dashboard = build_goal_center_dashboard(
        as_of_date=as_of_date,
        goal=goal,
        plan=plan,
        snapshot=snapshot,
        fx_schedule=fx_schedule,
        intelligence=intelligence,
        tracking_start=tracking_start,
        decision=decision_view,
        bands=bands,
    )
    allocation_plan = allocation
    allocation_reason = None
    if allocation_plan is None:
        loaded_policy = policy if policy is not None else _load_policy(wealth, portfolio_id)
        loaded_candidates = (
            list(candidates) if candidates is not None else _load_candidates(wealth)
        )
        rate = fx_schedule.usdtry_for_year(as_of_date.year)
        conversion = planning_conversion(rate, contribution_currency=plan.currency)
        allocation_plan = allocate_new_money(
            available_amount=plan.starting_monthly,
            amount_currency=plan.currency,
            portfolio_view=portfolio_view,
            policy=loaded_policy,
            candidates=loaded_candidates,
            conversion=conversion,
            assets=assets,
            positions=positions,
        )
    snaps = snapshots if snapshots is not None else _load_snapshots(wealth, portfolio_id)
    performance = build_performance_center(
        snaps,
        period=PerformancePeriod.MONTHLY,
        transactions=txns,
        account_ids=account_ids,
        contribution_reconciliations=recons,
        portfolio_id=portfolio_id or None,
    )
    if not performance.sufficient:
        performance = build_performance_center(
            snaps,
            period=PerformancePeriod.ALL,
            transactions=txns,
            account_ids=account_ids,
            contribution_reconciliations=recons,
            portfolio_id=portfolio_id or None,
        )
    institution_center = present_institution_center(portfolio_view, accounts)
    if purification_zakat is None:
        purification_zakat = try_session_result(
            portfolio_view,
            accounts=accounts,
            assets=assets,
            transactions=txns,
        )
    return build_wealth_brief(
        as_of_date=as_of_date,
        portfolio_view=portfolio_view,
        dashboard=dashboard,
        decision=decision_view,
        allocation=allocation_plan,
        allocation_unavailable_reason=allocation_reason,
        performance=performance,
        institution_center=institution_center,
        purification_zakat=purification_zakat,
    )


def _render_brief(brief: WealthBrief) -> None:
    render_section_title(brief.header.title)
    tone = "success" if brief.header.valuation_complete else "warning"
    st.markdown(
        render_status_badge(brief.header.valuation_status, tone),
        unsafe_allow_html=True,
    )
    render_kpi_row(
        [
            ("Güncel portföy değeri", brief.header.current_value_label, None),
            ("Kanıt tarihi", brief.header.as_of_label, None),
        ]
    )
    if brief.limitations:
        for note in brief.limitations[:3]:
            st.caption(note)

    st.markdown(f"**{SECTION_TODAY}**")
    for line in brief.today_lines:
        st.write(line)

    st.markdown(f"**{SECTION_PRIORITY}**")
    if brief.priority.healthy:
        st.success(brief.priority.title)
    else:
        if brief.priority.severity_label:
            st.markdown(
                render_status_badge(brief.priority.severity_label, "warning"),
                unsafe_allow_html=True,
            )
        st.markdown(f"**{brief.priority.title}**")
        st.write(brief.priority.explanation)
        for line in brief.priority.evidence_lines:
            st.caption(line)
        for option in brief.priority.options:
            st.caption(option)

    st.markdown(f"**{SECTION_GOAL}**")
    render_kpi_row(
        [
            ("Hedef", brief.goal.target_label, None),
            ("İlerleme", brief.goal.current_progress, None),
            ("2031 tahmini", brief.goal.projected_wealth_label, None),
            ("Ulaşım", brief.goal.attainment_label, None),
        ]
    )
    st.caption(f"Aylık katkı: {brief.goal.configured_monthly_label}")
    st.caption(f"Gerekli başlangıç aylık: {brief.goal.required_monthly_label}")
    st.caption(brief.goal.status_copy)
    if brief.goal.target_date_alternative:
        st.caption(f"Hedef tarihi alternatifi: {brief.goal.target_date_alternative}")

    st.markdown(f"**{SECTION_NEW_MONEY}**")
    st.caption(f"Değerlendirilen tutar: {brief.new_money.amount_label}")
    if brief.new_money.unavailable_reason:
        st.info(brief.new_money.unavailable_reason)
    else:
        st.caption(f"Kullanılacak: {brief.new_money.allocated_label}")
        st.caption(f"Kalan nakit: {brief.new_money.residual_label}")
        for row in brief.new_money.recommendations:
            st.write(
                f"{row.symbol} · {row.kind_label} · {row.amount_label} · {row.reason}"
            )

    st.markdown(f"**{SECTION_PERFORMANCE}**")
    st.caption(f"Dönem: {brief.performance.period_label}")
    if brief.performance.return_label:
        st.write(f"Portföy getirisi: {brief.performance.return_label}")
    if brief.performance.best_label:
        st.write(f"En iyi: {brief.performance.best_label}")
    if brief.performance.weakest_label:
        st.write(f"En zayıf: {brief.performance.weakest_label}")
    if brief.performance.limitation:
        st.caption(brief.performance.limitation)

    if brief.tracking_prestart_copy:
        st.caption(brief.tracking_prestart_copy)

    with st.expander(DETAILS_EXPANDER, expanded=False):
        for note in brief.limitations:
            st.caption(note)
        st.caption(f"as_of: {brief.header.as_of_label}")


def render_wealth_brief(
    *,
    portfolio_view: Optional[PortfolioIntelligenceView] = None,
    wealth=None,
    accounts: Sequence[Dict[str, Any]] = (),
    as_of: Optional[date] = None,
    brief: Optional[WealthBrief] = None,
    **compose_kwargs,
) -> Optional[WealthBrief]:
    presented = brief
    if presented is None:
        if portfolio_view is None:
            return None
        presented = compose_wealth_brief(
            portfolio_view=portfolio_view,
            wealth=wealth,
            accounts=accounts,
            as_of=as_of,
            **compose_kwargs,
        )
    _render_brief(presented)
    return presented
