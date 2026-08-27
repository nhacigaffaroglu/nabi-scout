"""New-money allocation scenario UI. Recommendation only; no execution."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Callable, Optional, Sequence

import streamlit as st

from components.nabi_design_system import render_section_title, render_status_badge
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_goal_models import ContributionPlan
from services.wealth_goal_planning import planning_conversion
from services.wealth_new_money_allocation import allocate_new_money
from services.wealth_new_money_allocation_presentation import (
    AMOUNT_LABEL,
    DETAILS_EXPANDER,
    EXISTING_LABEL,
    EXTRA_CAPTION,
    MIN_TRADE_CAPTION,
    MIN_TRADE_LABEL,
    MODE_EXTRA,
    MODE_MONTHLY,
    MONTHLY_CAPTION,
    NEW_LABEL,
    RESIDUAL_LABEL,
    RUN_LABEL,
    SCENARIO_DISCLAIMER,
    SECTION_TITLE,
    SKIPPED_EXPANDER,
    TOTAL_ALLOCATED_LABEL,
    format_allocation_amount,
    format_quantity,
    holding_kind_label,
    recommendation_reason_label,
    residual_explanation,
    skip_reason_label,
)
from services.wealth_planning_fx import PlanningFxSchedule

RESULT_STATE_KEY = "wealth_new_money_allocation_result"
DEFAULT_MIN_TRADE = Decimal("0")

AllocateFn = Callable[..., Any]


def _decimal_input(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _read_policy(*, wealth, portfolio_id: str, policy=None, policy_service=None):
    if policy is not None:
        return policy
    service = policy_service
    if service is None:
        client = getattr(wealth, "client", None)
        user_id = getattr(wealth, "user_id", None)
        if client is None or not user_id or not portfolio_id:
            return None
        from services.portfolio_allocation_policy_service import (
            PortfolioAllocationPolicyService,
        )

        service = PortfolioAllocationPolicyService(client, user_id)
    try:
        return service.get_policy(str(portfolio_id))
    except Exception:
        return None


def _read_candidates(*, wealth, candidates=None, candidate_loader=None) -> list:
    if candidates is not None:
        return list(candidates)
    if candidate_loader is not None:
        return list(candidate_loader() or [])
    client = getattr(wealth, "client", None)
    if client is None:
        return []
    from repositories.candidate_repository import CandidateRepository

    try:
        return list(CandidateRepository(client).get_all(limit=500) or [])
    except Exception:
        return []


def _planning_conversion(plan: ContributionPlan, fx_schedule, as_of: date):
    if fx_schedule is None:
        return None
    rate = fx_schedule.usdtry_for_year(as_of.year)
    return planning_conversion(
        rate,
        contribution_currency=plan.currency,
    )


def _render_recommendations(plan) -> None:
    currency = plan.currency
    for row in plan.recommendations:
        kind = holding_kind_label(row.existing_or_new)
        tone = "info" if row.existing_or_new == "existing" else "neutral"
        with st.container(border=True):
            st.markdown(
                f"{render_status_badge(kind, tone)} **{row.symbol}**",
                unsafe_allow_html=True,
            )
            st.write(f"Katman: {row.layer}")
            st.write(f"Miktar: {format_quantity(row.quantity)}")
            st.write(
                "Tahmini tutar: "
                f"{format_allocation_amount(row.allocated_amount, currency)}"
            )
            st.write(recommendation_reason_label(row))
            with st.expander(DETAILS_EXPANDER, expanded=False):
                st.caption(f"reason_code: {row.reason_code}")
                st.caption(row.reason_text)
                if row.decision:
                    st.caption(f"decision: {row.decision}")


def _render_totals(plan) -> None:
    currency = plan.currency
    left, right = st.columns(2)
    left.metric(
        TOTAL_ALLOCATED_LABEL,
        format_allocation_amount(plan.total_allocated, currency),
    )
    right.metric(
        RESIDUAL_LABEL,
        format_allocation_amount(plan.residual_cash, currency),
    )
    note = residual_explanation(plan.residual_cash)
    if note:
        st.caption(note)
    if plan.limitations:
        with st.expander(DETAILS_EXPANDER, expanded=False):
            for item in plan.limitations:
                st.caption(item)


def _render_skipped(plan) -> None:
    if not plan.skipped:
        return
    with st.expander(SKIPPED_EXPANDER, expanded=False):
        for row in plan.skipped:
            st.write(f"**{row.symbol}** — {skip_reason_label(row)}")
            st.caption(f"reason_code: {row.reason_code}")


def render_new_money_allocation(
    *,
    portfolio_view: PortfolioIntelligenceView,
    wealth,
    plan: ContributionPlan,
    fx_schedule: Optional[PlanningFxSchedule] = None,
    as_of: Optional[date] = None,
    assets: Optional[Sequence[dict]] = None,
    positions: Optional[Sequence[dict]] = None,
    policy=None,
    candidates=None,
    conversion=None,
    policy_service=None,
    candidate_loader=None,
    allocate_fn: Optional[AllocateFn] = None,
    session_state: Optional[Any] = None,
) -> None:
    """Render a recommendation-only allocation scenario. No writes or providers."""
    state = session_state if session_state is not None else st.session_state
    as_of_date = as_of or date.today()
    render_section_title(SECTION_TITLE)
    st.caption(SCENARIO_DISCLAIMER)

    mode = st.radio(
        "Kaynak",
        (MODE_MONTHLY, MODE_EXTRA),
        horizontal=True,
        key="wealth_new_money_mode",
    )
    if mode == MODE_MONTHLY:
        amount = plan.starting_monthly
        st.metric(AMOUNT_LABEL, format_allocation_amount(amount, plan.currency))
        st.caption(MONTHLY_CAPTION)
    else:
        extra_value = st.number_input(
            AMOUNT_LABEL,
            min_value=0.0,
            value=0.0,
            step=1000.0,
            key="wealth_new_money_extra_amount",
        )
        amount = _decimal_input(extra_value)
        st.caption(EXTRA_CAPTION)

    min_trade_value = st.number_input(
        MIN_TRADE_LABEL,
        min_value=0.0,
        value=float(DEFAULT_MIN_TRADE),
        step=100.0,
        key="wealth_new_money_min_trade",
    )
    min_trade = _decimal_input(min_trade_value)
    st.caption(MIN_TRADE_CAPTION)

    if st.button(RUN_LABEL, key="wealth_new_money_run"):
        runner = allocate_fn or allocate_new_money
        loaded_policy = _read_policy(
            wealth=wealth,
            portfolio_id=str(getattr(portfolio_view, "portfolio_id", "") or ""),
            policy=policy,
            policy_service=policy_service,
        )
        loaded_candidates = _read_candidates(
            wealth=wealth,
            candidates=candidates,
            candidate_loader=candidate_loader,
        )
        conv = conversion
        if conv is None:
            conv = _planning_conversion(plan, fx_schedule, as_of_date)
        from components.portfolio_economic_exposure_ui import load_persisted_fund_snapshots

        fund_symbols = [
            str(row.symbol or "").strip().upper()
            for row in (
                list(portfolio_view.priced_positions)
                + list(getattr(portfolio_view, "unpriced_positions", ()) or [])
                + list(getattr(portfolio_view, "foreign_currency_positions", ()) or [])
            )
            if str(getattr(row, "asset_class", "") or "").strip().lower() in {"etf", "fund"}
            and str(getattr(row, "symbol", "") or "").strip()
        ]
        state[RESULT_STATE_KEY] = runner(
            available_amount=amount,
            amount_currency=plan.currency,
            portfolio_view=portfolio_view,
            policy=loaded_policy,
            candidates=loaded_candidates,
            conversion=conv,
            assets=assets if assets is not None else wealth.list_assets(),
            positions=positions if positions is not None else wealth.list_positions(),
            minimum_trade_amount=min_trade,
            fund_snapshots=load_persisted_fund_snapshots(wealth, fund_symbols),
        )

    result = state.get(RESULT_STATE_KEY)
    if result is None:
        return
    _render_totals(result)
    _render_recommendations(result)
    _render_skipped(result)
