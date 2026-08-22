from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from services.wealth_contract import WealthValidationError
from services.wealth_goal_models import (
    COMPOUNDING_CONVENTION,
    ContributionPlan,
    ConversionAssumption,
    CurrentWealthSnapshot,
    GoalEvidenceStatus,
    ProjectionLimitation,
    ProjectionResult,
    ReturnScenario,
    WealthGoal,
    default_return_scenarios,
    default_wealth_goal_2031,
    quantize_money,
)
from services.wealth_planning_fx import PlanningFxSchedule, conversion_for_year


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def iter_month_ends_after(as_of: date, until: date) -> List[date]:
    """Calendar month-ends strictly after `as_of` and on or before `until`."""
    year, month = as_of.year, as_of.month
    cursor = month_end(year, month)
    if cursor <= as_of:
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
        cursor = month_end(year, month)
    ends: List[date] = []
    while cursor <= until:
        ends.append(cursor)
        if cursor.month == 12:
            year, month = cursor.year + 1, 1
        else:
            year, month = cursor.year, cursor.month + 1
        cursor = month_end(year, month)
    return ends


def _period_compound_factor(monthly_rate: Decimal, *, as_of: date, step: date, is_first: bool) -> Decimal:
    one = Decimal(1)
    if is_first and as_of < step:
        days_in_month = Decimal(step.day)
        remaining = Decimal((step - as_of).days)
        if remaining <= 0 or days_in_month <= 0:
            return one
        fraction = remaining / days_in_month
        return (one + monthly_rate) ** fraction
    return one + monthly_rate


def _monthly_contribution(
    plan: ContributionPlan,
    *,
    as_of: date,
    step: date,
) -> Decimal:
    year_offset = step.year - as_of.year
    if year_offset < 0:
        year_offset = 0
    growth = (Decimal(1) + plan.annual_increase_rate) ** year_offset
    return plan.starting_monthly * growth


def _convert_contribution(
    amount: Decimal,
    *,
    plan: ContributionPlan,
    goal: WealthGoal,
    conversion: Optional[ConversionAssumption],
    fx_schedule: Optional[PlanningFxSchedule] = None,
    step_year: Optional[int] = None,
) -> Tuple[Optional[Decimal], Tuple[ProjectionLimitation, ...]]:
    plan_ccy = plan.currency.strip().upper()
    goal_ccy = goal.currency.strip().upper()
    if plan_ccy == goal_ccy:
        return amount, ()
    active = conversion
    if fx_schedule is not None and step_year is not None:
        active = conversion_for_year(
            fx_schedule,
            year=step_year,
            contribution_currency=plan_ccy,
            goal_currency=goal_ccy,
        )
        if active is None:
            return None, (ProjectionLimitation.FX_CONVERSION_REQUIRED,)
    if active is None:
        return None, (ProjectionLimitation.FX_CONVERSION_REQUIRED,)
    from_ccy = active.from_currency.strip().upper()
    to_ccy = active.to_currency.strip().upper()
    if from_ccy != plan_ccy or to_ccy != goal_ccy:
        return None, (ProjectionLimitation.CONTRIBUTION_CURRENCY_MISMATCH,)
    return active.convert(amount), ()


def _status_for(
    *,
    already_reached: bool,
    projection_complete: bool,
    projected_reached: Optional[bool],
    valuation_complete: bool,
) -> GoalEvidenceStatus:
    if already_reached:
        return GoalEvidenceStatus.REACHED
    if not projection_complete:
        return GoalEvidenceStatus.INDETERMINATE
    if projected_reached:
        return GoalEvidenceStatus.PROJECTED_TO_REACH
    if not valuation_complete:
        return GoalEvidenceStatus.INDETERMINATE
    return GoalEvidenceStatus.PROJECTED_SHORTFALL


def project_wealth_goal(
    *,
    goal: Optional[WealthGoal] = None,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    contribution_plan: ContributionPlan,
    scenario: ReturnScenario,
    conversion: Optional[ConversionAssumption] = None,
    fx_schedule: Optional[PlanningFxSchedule] = None,
) -> ProjectionResult:
    goal = goal or default_wealth_goal_2031()
    goal.validate()
    contribution_plan.validate()
    if conversion is not None:
        conversion.validate()
    if as_of_date > goal.target_date:
        raise WealthValidationError("As-of tarihi hedef tarihinden sonra olamaz.")
    monthly_rate = scenario.monthly_rate
    if Decimal(1) + monthly_rate <= 0:
        raise WealthValidationError("Aylık getiri -100% veya daha düşük olamaz.")

    limitations: List[ProjectionLimitation] = []
    snapshot_ccy = current.currency.strip().upper()
    goal_ccy = goal.currency.strip().upper()
    currency_aligned = snapshot_ccy == goal_ccy
    if not currency_aligned:
        limitations.append(ProjectionLimitation.BASE_CURRENCY_MISMATCH)
    if not current.valuation_complete:
        limitations.append(ProjectionLimitation.PARTIAL_VALUATION)

    # Never add a non-goal-currency amount into USD math. Unpriced holdings
    # stay excluded (lower bound), not coerced to zero market value.
    usable_lower_bound = (
        current.current_value_lower_bound if currency_aligned else None
    )
    target = goal.target_amount
    if usable_lower_bound is None:
        measurable_gap = target
        progress = Decimal(0)
        already_reached = False
    else:
        measurable_gap = max(Decimal(0), target - usable_lower_bound)
        progress = (usable_lower_bound / target) * Decimal(100)
        already_reached = usable_lower_bound >= target

    schedule_incomplete = False
    if fx_schedule is not None:
        schedule_incomplete = not fx_schedule.is_complete(
            as_of=as_of_date,
            target_date=goal.target_date,
            contribution_currency=contribution_plan.currency,
            goal_currency=goal.currency,
        )
        if schedule_incomplete:
            limitations.append(ProjectionLimitation.FX_CONVERSION_REQUIRED)
    converted_probe, conv_limits = _convert_contribution(
        contribution_plan.starting_monthly,
        plan=contribution_plan,
        goal=goal,
        conversion=conversion,
        fx_schedule=fx_schedule,
        step_year=as_of_date.year,
    )
    if schedule_incomplete:
        converted_probe = None
    else:
        limitations.extend(conv_limits)
    can_project = usable_lower_bound is not None and converted_probe is not None
    steps = iter_month_ends_after(as_of_date, goal.target_date)

    projected_value: Optional[Decimal] = None
    total_contrib: Optional[Decimal] = None
    growth: Optional[Decimal] = None
    reach_date: Optional[date] = as_of_date if already_reached else None
    projected_reached: Optional[bool] = True if already_reached else None

    if can_project:
        balance = usable_lower_bound
        contrib_sum = Decimal(0)
        for index, step in enumerate(steps):
            balance *= _period_compound_factor(
                monthly_rate,
                as_of=as_of_date,
                step=step,
                is_first=index == 0,
            )
            native_contrib = _monthly_contribution(
                contribution_plan,
                as_of=as_of_date,
                step=step,
            )
            usd_contrib, step_limits = _convert_contribution(
                native_contrib,
                plan=contribution_plan,
                goal=goal,
                conversion=conversion,
                fx_schedule=fx_schedule,
                step_year=step.year,
            )
            if usd_contrib is None:
                can_project = False
                limitations.extend(step_limits)
                break
            balance += usd_contrib
            contrib_sum += usd_contrib
            if reach_date is None and balance >= target:
                reach_date = step
        else:
            projected_value = quantize_money(balance)
            total_contrib = quantize_money(contrib_sum)
            growth = quantize_money(balance - usable_lower_bound - contrib_sum)
            if already_reached:
                projected_reached = True
            else:
                projected_reached = projected_value >= target

    projection_complete = can_project and converted_probe is not None
    if not projection_complete:
        projected_value = None
        total_contrib = None
        growth = None
        if not already_reached:
            reach_date = None
            projected_reached = None

    status = _status_for(
        already_reached=already_reached,
        projection_complete=projection_complete,
        projected_reached=projected_reached,
        valuation_complete=current.valuation_complete and currency_aligned,
    )
    if status == GoalEvidenceStatus.INDETERMINATE:
        projected_reached = None
        if not already_reached:
            reach_date = None
    # Unique limitations, stable order
    seen = set()
    unique_limits: List[ProjectionLimitation] = []
    for item in limitations:
        if item in seen:
            continue
        seen.add(item)
        unique_limits.append(item)

    return ProjectionResult(
        scenario_name=scenario.name,
        annual_rate=scenario.annual_rate,
        as_of_date=as_of_date,
        target_date=goal.target_date,
        target_amount=quantize_money(target),
        current_value_lower_bound=quantize_money(
            current.current_value_lower_bound
        ),
        measurable_gap=quantize_money(measurable_gap),
        progress_pct_lower_bound=progress.quantize(Decimal("0.01")),
        month_count=len(steps),
        projected_target_date_value=projected_value,
        projected_goal_reached=projected_reached,
        projected_goal_reach_date=reach_date,
        total_projected_contributions=total_contrib,
        projected_investment_growth=growth,
        valuation_complete=current.valuation_complete and currency_aligned,
        projection_complete=projection_complete,
        status=status,
        limitations=tuple(unique_limits),
        compounding_convention=COMPOUNDING_CONVENTION,
    )


def project_wealth_goal_scenarios(
    *,
    goal: Optional[WealthGoal] = None,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    contribution_plan: ContributionPlan,
    scenarios: Optional[Sequence[ReturnScenario]] = None,
    conversion: Optional[ConversionAssumption] = None,
    fx_schedule: Optional[PlanningFxSchedule] = None,
) -> Tuple[ProjectionResult, ...]:
    selected = tuple(scenarios) if scenarios is not None else default_return_scenarios()
    return tuple(
        project_wealth_goal(
            goal=goal,
            as_of_date=as_of_date,
            current=current,
            contribution_plan=contribution_plan,
            scenario=scenario,
            conversion=conversion,
            fx_schedule=fx_schedule,
        )
        for scenario in selected
    )
