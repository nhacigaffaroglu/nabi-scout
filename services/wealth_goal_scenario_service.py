"""Deterministic 2031 goal scenario matrix. Analysis only.

Reuses the canonical Goal Engine (`project_wealth_goal`, `solve_required_starting_monthly`,
`monthly_for_year`, planning FX schedule). Does not persist contribution plans, goals,
planning FX, prices, snapshots, or Decision Intelligence signals.

Report feasibility bands below are presentation labels only — not domain enums.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from services.wealth_goal_models import (
    ContributionPlan,
    CurrentWealthSnapshot,
    ProjectionLimitation,
    ProjectionResult,
    ReturnScenario,
    WealthGoal,
    default_contribution_plan,
    default_wealth_goal_2031,
    quantize_money,
)
from services.wealth_goal_planning import monthly_for_year, solve_required_starting_monthly
from services.wealth_planning_fx import (
    PlanningFxContinuationProposal,
    PlanningFxSchedule,
    propose_planning_fx_continuation,
    required_planning_fx_years,
)
from services.wealth_projection_engine import iter_month_ends_after, project_wealth_goal

BASE_RETURN_RATE = Decimal("0.08")
DEFAULT_TRACKING_START = date(2026, 9, 1)

CONTRIBUTION_SCENARIO_LEVELS_TRY = (
    Decimal("60000"),
    Decimal("80000"),
    Decimal("100000"),
    Decimal("120000"),
    Decimal("150000"),
    Decimal("180000"),
    Decimal("200000"),
)
RETURN_SCENARIO_RATES = (
    Decimal("0.06"),
    Decimal("0.08"),
    Decimal("0.10"),
    Decimal("0.12"),
)
MATRIX_CONTRIBUTION_LEVELS_TRY = (
    Decimal("60000"),
    Decimal("100000"),
    Decimal("150000"),
    Decimal("180000"),
)
GOAL_DATE_EXTENSIONS = (
    date(2031, 12, 31),
    date(2032, 12, 31),
    date(2033, 12, 31),
    date(2034, 12, 31),
    date(2035, 12, 31),
    date(2036, 12, 31),
)

# Report-only scenario bands. Not persisted. Not Decision Intelligence.
REPORT_BAND_TARGET_REACHED = "TARGET_REACHED"
REPORT_BAND_NEAR_TARGET = "NEAR_TARGET"
REPORT_BAND_MATERIAL_SHORTFALL = "MATERIAL_SHORTFALL"
REPORT_BAND_LARGE_SHORTFALL = "LARGE_SHORTFALL"
REPORT_BAND_UNAVAILABLE = "UNAVAILABLE"

GOAL_DATE_AVAILABLE = "AVAILABLE"
GOAL_DATE_UNAVAILABLE = "UNAVAILABLE"
MISSING_PLANNING_FX = "MISSING_PLANNING_FX"
EXTENDED_HORIZON_AVAILABLE = "AVAILABLE"
EXTENDED_HORIZON_BLOCKED = "BLOCKED_PENDING_FX_APPROVAL"
NOT_REACHED_BY_HORIZON = "NOT REACHED BY 2036"
EXTENDED_HORIZON_END = date(2036, 12, 31)
HORIZON_CONTRIBUTION_LEVELS_TRY = (
    Decimal("60000"),
    Decimal("100000"),
    Decimal("120000"),
    Decimal("150000"),
)
FIRST_REACH_CONTRIBUTION_LEVELS_TRY = (
    Decimal("60000"),
    Decimal("80000"),
    Decimal("100000"),
    Decimal("120000"),
    Decimal("150000"),
)
SENSITIVITY_CONTRIBUTION_LEVELS_TRY = (
    Decimal("60000"),
    Decimal("100000"),
    Decimal("150000"),
)
SENSITIVITY_RETURN_RATES = (
    Decimal("0.08"),
    Decimal("0.10"),
    Decimal("0.12"),
)


@dataclass(frozen=True)
class ScenarioProjection:
    starting_monthly: Decimal
    annual_return_rate: Decimal
    target_date: date
    projected_wealth: Optional[Decimal]
    surplus_or_shortfall: Optional[Decimal]
    attainment_pct: Optional[Decimal]
    target_reached: Optional[bool]
    report_band: str
    projection_complete: bool
    limitation: Optional[str]
    missing_planning_fx_years: Tuple[int, ...]
    total_projected_contributions_usd: Optional[Decimal]
    engine_result: Optional[ProjectionResult]


@dataclass(frozen=True)
class RequiredMonthlyRow:
    annual_return_rate: Decimal
    required_starting_monthly: Optional[Decimal]
    difference_vs_current_plan: Optional[Decimal]
    available: bool
    limitation: Optional[str]


@dataclass(frozen=True)
class BreakEvenContribution:
    return_rate: Decimal
    break_even_monthly: Optional[Decimal]
    current_monthly: Decimal
    absolute_gap: Optional[Decimal]
    percentage_increase_required: Optional[Decimal]
    available: bool


@dataclass(frozen=True)
class ContributionCalendarRow:
    year: int
    monthly: Decimal
    months: int
    annual_total: Decimal


@dataclass(frozen=True)
class GoalDateScenarioRow:
    target_date: date
    availability: str
    limitation: Optional[str]
    missing_planning_fx_years: Tuple[int, ...]
    projected_wealth: Optional[Decimal]
    surplus_or_shortfall: Optional[Decimal]
    attainment_pct: Optional[Decimal]
    target_reached: Optional[bool]


@dataclass(frozen=True)
class GoalScenarioMatrix:
    as_of_date: date
    current_wealth: Decimal
    valuation_complete: bool
    target_amount: Decimal
    goal_date: date
    base_return_rate: Decimal
    starting_monthly: Decimal
    indexation_rate: Decimal
    contribution_tracking_start: Optional[date]
    baseline: ScenarioProjection
    required_starting_monthly_base: Optional[Decimal]
    contribution_matrix: Tuple[ScenarioProjection, ...]
    return_matrix: Tuple[ScenarioProjection, ...]
    contribution_return_matrix: Tuple[Tuple[ScenarioProjection, ...], ...]
    required_monthly_by_return: Tuple[RequiredMonthlyRow, ...]
    break_even: BreakEvenContribution
    current_plan_schedule: Tuple[ContributionCalendarRow, ...]
    break_even_schedule: Tuple[ContributionCalendarRow, ...]
    goal_date_extensions: Tuple[GoalDateScenarioRow, ...]
    total_nominal_try_contributions: Decimal
    total_projected_contributions_usd: Optional[Decimal]


def report_feasibility_band(attainment_pct: Optional[Decimal]) -> str:
    """Presentation-only band. Not a production Goal/DI enum."""
    if attainment_pct is None:
        return REPORT_BAND_UNAVAILABLE
    if attainment_pct >= Decimal("100"):
        return REPORT_BAND_TARGET_REACHED
    if attainment_pct >= Decimal("90"):
        return REPORT_BAND_NEAR_TARGET
    if attainment_pct >= Decimal("70"):
        return REPORT_BAND_MATERIAL_SHORTFALL
    return REPORT_BAND_LARGE_SHORTFALL


def _planning_scenario(annual_return_rate: Decimal) -> ReturnScenario:
    pct = (annual_return_rate * Decimal("100")).quantize(Decimal("1"))
    return ReturnScenario(f"Planning {pct}%", annual_return_rate)


def _missing_fx_years(
    fx_schedule: PlanningFxSchedule,
    *,
    as_of: date,
    target_date: date,
    plan: ContributionPlan,
    goal: WealthGoal,
) -> Tuple[int, ...]:
    if plan.currency.strip().upper() == goal.currency.strip().upper():
        return ()
    required = required_planning_fx_years(as_of, target_date)
    return fx_schedule.missing_years(required)


def _plan_with_monthly(plan: ContributionPlan, monthly: Decimal) -> ContributionPlan:
    return replace(plan, starting_monthly=Decimal(str(monthly)))


def project_scenario(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    contribution_plan: ContributionPlan,
    annual_return_rate: Decimal,
    fx_schedule: PlanningFxSchedule,
    goal: Optional[WealthGoal] = None,
    starting_monthly: Optional[Decimal] = None,
    target_date: Optional[date] = None,
) -> ScenarioProjection:
    base_goal = goal or default_wealth_goal_2031()
    active_goal = (
        replace(base_goal, target_date=target_date) if target_date is not None else base_goal
    )
    active_plan = (
        contribution_plan
        if starting_monthly is None
        else _plan_with_monthly(contribution_plan, starting_monthly)
    )
    missing = _missing_fx_years(
        fx_schedule,
        as_of=as_of_date,
        target_date=active_goal.target_date,
        plan=active_plan,
        goal=active_goal,
    )
    result = project_wealth_goal(
        goal=active_goal,
        as_of_date=as_of_date,
        current=current,
        contribution_plan=active_plan,
        scenario=_planning_scenario(annual_return_rate),
        fx_schedule=fx_schedule,
    )
    fx_blocked = ProjectionLimitation.FX_CONVERSION_REQUIRED in result.limitations
    limitation = MISSING_PLANNING_FX if (missing or fx_blocked) else None
    if not result.projection_complete:
        return ScenarioProjection(
            starting_monthly=active_plan.starting_monthly,
            annual_return_rate=annual_return_rate,
            target_date=active_goal.target_date,
            projected_wealth=None,
            surplus_or_shortfall=None,
            attainment_pct=None,
            target_reached=None,
            report_band=REPORT_BAND_UNAVAILABLE,
            projection_complete=False,
            limitation=limitation or (
                result.limitations[0].value if result.limitations else None
            ),
            missing_planning_fx_years=missing,
            total_projected_contributions_usd=None,
            engine_result=result,
        )
    projected = result.projected_target_date_value
    surplus = None if projected is None else quantize_money(projected - active_goal.target_amount)
    attainment = None
    if projected is not None and active_goal.target_amount > 0:
        attainment = quantize_money((projected / active_goal.target_amount) * Decimal("100"))
    return ScenarioProjection(
        starting_monthly=active_plan.starting_monthly,
        annual_return_rate=annual_return_rate,
        target_date=active_goal.target_date,
        projected_wealth=projected,
        surplus_or_shortfall=surplus,
        attainment_pct=attainment,
        target_reached=result.projected_goal_reached,
        report_band=report_feasibility_band(attainment),
        projection_complete=True,
        limitation=None,
        missing_planning_fx_years=(),
        total_projected_contributions_usd=result.total_projected_contributions,
        engine_result=result,
    )


def contribution_calendar(
    plan: ContributionPlan,
    *,
    as_of: date,
    target_date: date,
    tracking_start: Optional[date] = None,
) -> Tuple[ContributionCalendarRow, ...]:
    """Canonical indexed monthly levels with remaining month-ends.

    Month-ends come from the projection calendar. If a contribution tracking
    start is set, month-ends before that date are excluded (no Jan–Aug 2026
    fabrication when tracking starts 2026-09-01).
    """
    plan.validate()
    steps = [
        step
        for step in iter_month_ends_after(as_of, target_date)
        if tracking_start is None or step >= tracking_start
    ]
    counts: dict[int, int] = {}
    for step in steps:
        counts[step.year] = counts.get(step.year, 0) + 1
    rows = []
    for year in sorted(counts):
        monthly = monthly_for_year(plan, as_of=as_of, year=year)
        months = counts[year]
        rows.append(
            ContributionCalendarRow(
                year=year,
                monthly=monthly,
                months=months,
                annual_total=quantize_money(monthly * Decimal(months)),
            )
        )
    return tuple(rows)


def required_starting_monthly_row(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    contribution_plan: ContributionPlan,
    annual_return_rate: Decimal,
    fx_schedule: PlanningFxSchedule,
    goal: Optional[WealthGoal] = None,
) -> RequiredMonthlyRow:
    solved = solve_required_starting_monthly(
        as_of_date=as_of_date,
        current=current,
        contribution_currency=contribution_plan.currency,
        annual_increase_rate=contribution_plan.annual_increase_rate,
        annual_return_rate=annual_return_rate,
        fx_schedule=fx_schedule,
        goal=goal,
    )
    required = solved.starting_monthly
    difference = None
    if required is not None:
        difference = quantize_money(required - contribution_plan.starting_monthly)
    limitation = None
    if solved.limitation is not None:
        limitation = (
            MISSING_PLANNING_FX
            if solved.limitation == ProjectionLimitation.FX_CONVERSION_REQUIRED
            else solved.limitation.value
        )
    return RequiredMonthlyRow(
        annual_return_rate=annual_return_rate,
        required_starting_monthly=required,
        difference_vs_current_plan=difference,
        available=solved.available,
        limitation=limitation,
    )


def build_goal_scenario_matrix(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    fx_schedule: PlanningFxSchedule,
    contribution_plan: Optional[ContributionPlan] = None,
    goal: Optional[WealthGoal] = None,
    contribution_tracking_start: Optional[date] = DEFAULT_TRACKING_START,
    contribution_levels: Sequence[Decimal] = CONTRIBUTION_SCENARIO_LEVELS_TRY,
    return_rates: Sequence[Decimal] = RETURN_SCENARIO_RATES,
    matrix_contribution_levels: Sequence[Decimal] = MATRIX_CONTRIBUTION_LEVELS_TRY,
    extension_dates: Sequence[date] = GOAL_DATE_EXTENSIONS,
    base_return_rate: Decimal = BASE_RETURN_RATE,
) -> GoalScenarioMatrix:
    plan = contribution_plan or default_contribution_plan()
    active_goal = goal or default_wealth_goal_2031()
    plan.validate()
    active_goal.validate()

    baseline = project_scenario(
        as_of_date=as_of_date,
        current=current,
        contribution_plan=plan,
        annual_return_rate=base_return_rate,
        fx_schedule=fx_schedule,
        goal=active_goal,
    )
    contribution_matrix = tuple(
        project_scenario(
            as_of_date=as_of_date,
            current=current,
            contribution_plan=plan,
            annual_return_rate=base_return_rate,
            fx_schedule=fx_schedule,
            goal=active_goal,
            starting_monthly=level,
        )
        for level in contribution_levels
    )
    return_matrix = tuple(
        project_scenario(
            as_of_date=as_of_date,
            current=current,
            contribution_plan=plan,
            annual_return_rate=rate,
            fx_schedule=fx_schedule,
            goal=active_goal,
        )
        for rate in return_rates
    )
    contribution_return_matrix = tuple(
        tuple(
            project_scenario(
                as_of_date=as_of_date,
                current=current,
                contribution_plan=plan,
                annual_return_rate=rate,
                fx_schedule=fx_schedule,
                goal=active_goal,
                starting_monthly=level,
            )
            for level in matrix_contribution_levels
        )
        for rate in return_rates
    )
    required_rows = tuple(
        required_starting_monthly_row(
            as_of_date=as_of_date,
            current=current,
            contribution_plan=plan,
            annual_return_rate=rate,
            fx_schedule=fx_schedule,
            goal=active_goal,
        )
        for rate in return_rates
    )
    base_required = next(
        (row for row in required_rows if row.annual_return_rate == base_return_rate),
        required_starting_monthly_row(
            as_of_date=as_of_date,
            current=current,
            contribution_plan=plan,
            annual_return_rate=base_return_rate,
            fx_schedule=fx_schedule,
            goal=active_goal,
        ),
    )
    break_even_monthly = base_required.required_starting_monthly
    absolute_gap = base_required.difference_vs_current_plan
    pct_increase = None
    if break_even_monthly is not None and plan.starting_monthly > 0:
        pct_increase = quantize_money(
            ((break_even_monthly - plan.starting_monthly) / plan.starting_monthly)
            * Decimal("100")
        )
    break_even = BreakEvenContribution(
        return_rate=base_return_rate,
        break_even_monthly=break_even_monthly,
        current_monthly=plan.starting_monthly,
        absolute_gap=absolute_gap,
        percentage_increase_required=pct_increase,
        available=base_required.available,
    )
    current_schedule = contribution_calendar(
        plan,
        as_of=as_of_date,
        target_date=active_goal.target_date,
        tracking_start=contribution_tracking_start,
    )
    break_even_schedule: Tuple[ContributionCalendarRow, ...] = ()
    if break_even_monthly is not None:
        break_even_schedule = contribution_calendar(
            _plan_with_monthly(plan, break_even_monthly),
            as_of=as_of_date,
            target_date=active_goal.target_date,
            tracking_start=contribution_tracking_start,
        )
    extensions = tuple(
        _goal_date_row(
            as_of_date=as_of_date,
            current=current,
            contribution_plan=plan,
            fx_schedule=fx_schedule,
            goal=active_goal,
            annual_return_rate=base_return_rate,
            target_date=target,
        )
        for target in extension_dates
    )
    total_nominal = quantize_money(
        sum((row.annual_total for row in current_schedule), Decimal("0"))
    )
    return GoalScenarioMatrix(
        as_of_date=as_of_date,
        current_wealth=current.current_value_lower_bound,
        valuation_complete=current.valuation_complete,
        target_amount=active_goal.target_amount,
        goal_date=active_goal.target_date,
        base_return_rate=base_return_rate,
        starting_monthly=plan.starting_monthly,
        indexation_rate=plan.annual_increase_rate,
        contribution_tracking_start=contribution_tracking_start,
        baseline=baseline,
        required_starting_monthly_base=break_even_monthly,
        contribution_matrix=contribution_matrix,
        return_matrix=return_matrix,
        contribution_return_matrix=contribution_return_matrix,
        required_monthly_by_return=required_rows,
        break_even=break_even,
        current_plan_schedule=current_schedule,
        break_even_schedule=break_even_schedule,
        goal_date_extensions=extensions,
        total_nominal_try_contributions=total_nominal,
        total_projected_contributions_usd=baseline.total_projected_contributions_usd,
    )


def _goal_date_row(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    contribution_plan: ContributionPlan,
    fx_schedule: PlanningFxSchedule,
    goal: WealthGoal,
    annual_return_rate: Decimal,
    target_date: date,
) -> GoalDateScenarioRow:
    projected = project_scenario(
        as_of_date=as_of_date,
        current=current,
        contribution_plan=contribution_plan,
        annual_return_rate=annual_return_rate,
        fx_schedule=fx_schedule,
        goal=goal,
        target_date=target_date,
    )
    if not projected.projection_complete:
        return GoalDateScenarioRow(
            target_date=target_date,
            availability=GOAL_DATE_UNAVAILABLE,
            limitation=projected.limitation or MISSING_PLANNING_FX,
            missing_planning_fx_years=projected.missing_planning_fx_years,
            projected_wealth=None,
            surplus_or_shortfall=None,
            attainment_pct=None,
            target_reached=None,
        )
    return GoalDateScenarioRow(
        target_date=target_date,
        availability=GOAL_DATE_AVAILABLE,
        limitation=None,
        missing_planning_fx_years=(),
        projected_wealth=projected.projected_wealth,
        surplus_or_shortfall=projected.surplus_or_shortfall,
        attainment_pct=projected.attainment_pct,
        target_reached=projected.target_reached,
    )


@dataclass(frozen=True)
class EarliestReachRow:
    starting_monthly: Decimal
    annual_return_rate: Decimal
    reached: bool
    reach_year: Optional[int]
    reach_date: Optional[date]
    label: str


@dataclass(frozen=True)
class RequiredMonthlyByGoalYearRow:
    goal_year: int
    target_date: date
    required_starting_monthly: Optional[Decimal]
    difference_vs_current_plan: Optional[Decimal]
    available: bool
    limitation: Optional[str]


@dataclass(frozen=True)
class ExtendedHorizonAnalysis:
    status: str
    as_of_date: date
    current_wealth: Decimal
    valuation_complete: bool
    existing_planning_fx: Tuple[Tuple[int, Decimal], ...]
    missing_planning_fx_years: Tuple[int, ...]
    proposal: PlanningFxContinuationProposal
    proposal_status: str
    target_year_matrix: Tuple[Tuple[ScenarioProjection, ...], ...]
    required_monthly_by_goal_year: Tuple[RequiredMonthlyByGoalYearRow, ...]
    earliest_reach: Tuple[EarliestReachRow, ...]
    return_sensitivity: Tuple[EarliestReachRow, ...]


def _existing_fx_pairs(fx_schedule: PlanningFxSchedule) -> Tuple[Tuple[int, Decimal], ...]:
    return tuple((row.year, row.usdtry) for row in fx_schedule.rates)


def _reach_row(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    contribution_plan: ContributionPlan,
    fx_schedule: PlanningFxSchedule,
    goal: WealthGoal,
    starting_monthly: Decimal,
    annual_return_rate: Decimal,
    horizon_end: date,
) -> EarliestReachRow:
    projected = project_scenario(
        as_of_date=as_of_date,
        current=current,
        contribution_plan=contribution_plan,
        annual_return_rate=annual_return_rate,
        fx_schedule=fx_schedule,
        goal=goal,
        starting_monthly=starting_monthly,
        target_date=horizon_end,
    )
    reach_date = (
        projected.engine_result.projected_goal_reach_date
        if projected.engine_result is not None
        else None
    )
    reached = bool(projected.target_reached) and reach_date is not None
    if not reached:
        return EarliestReachRow(
            starting_monthly=starting_monthly,
            annual_return_rate=annual_return_rate,
            reached=False,
            reach_year=None,
            reach_date=None,
            label=NOT_REACHED_BY_HORIZON,
        )
    return EarliestReachRow(
        starting_monthly=starting_monthly,
        annual_return_rate=annual_return_rate,
        reached=True,
        reach_year=reach_date.year,
        reach_date=reach_date,
        label=str(reach_date.year),
    )


def analyze_extended_goal_horizon(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    fx_schedule: PlanningFxSchedule,
    contribution_plan: Optional[ContributionPlan] = None,
    goal: Optional[WealthGoal] = None,
    horizon_end: date = EXTENDED_HORIZON_END,
    contribution_levels: Sequence[Decimal] = HORIZON_CONTRIBUTION_LEVELS_TRY,
    first_reach_levels: Sequence[Decimal] = FIRST_REACH_CONTRIBUTION_LEVELS_TRY,
    sensitivity_levels: Sequence[Decimal] = SENSITIVITY_CONTRIBUTION_LEVELS_TRY,
    sensitivity_returns: Sequence[Decimal] = SENSITIVITY_RETURN_RATES,
    base_return_rate: Decimal = BASE_RETURN_RATE,
) -> ExtendedHorizonAnalysis:
    """Read-only extended-horizon analysis. Never persists planning FX or goals.

    Projections run only when the persisted/approved schedule already covers
    every year through `horizon_end`. The continuation proposal is informational
    and is not merged into the schedule.
    """
    plan = contribution_plan or default_contribution_plan()
    active_goal = goal or default_wealth_goal_2031()
    plan.validate()
    active_goal.validate()
    proposal = propose_planning_fx_continuation(fx_schedule, through_year=horizon_end.year)
    missing = fx_schedule.missing_years(required_planning_fx_years(as_of_date, horizon_end))
    base = dict(
        status=EXTENDED_HORIZON_BLOCKED,
        as_of_date=as_of_date,
        current_wealth=current.current_value_lower_bound,
        valuation_complete=current.valuation_complete,
        existing_planning_fx=_existing_fx_pairs(fx_schedule),
        missing_planning_fx_years=missing,
        proposal=proposal,
        proposal_status=proposal.status,
        target_year_matrix=(),
        required_monthly_by_goal_year=(),
        earliest_reach=(),
        return_sensitivity=(),
    )
    if missing:
        return ExtendedHorizonAnalysis(**base)

    horizon_dates = tuple(
        date(year, 12, 31) for year in range(active_goal.target_date.year, horizon_end.year + 1)
    )
    target_year_matrix = tuple(
        tuple(
            project_scenario(
                as_of_date=as_of_date,
                current=current,
                contribution_plan=plan,
                annual_return_rate=base_return_rate,
                fx_schedule=fx_schedule,
                goal=active_goal,
                starting_monthly=level,
                target_date=target,
            )
            for target in horizon_dates
        )
        for level in contribution_levels
    )
    required_rows = []
    for target in horizon_dates:
        solved = required_starting_monthly_row(
            as_of_date=as_of_date,
            current=current,
            contribution_plan=plan,
            annual_return_rate=base_return_rate,
            fx_schedule=fx_schedule,
            goal=replace(active_goal, target_date=target),
        )
        required_rows.append(
            RequiredMonthlyByGoalYearRow(
                goal_year=target.year,
                target_date=target,
                required_starting_monthly=solved.required_starting_monthly,
                difference_vs_current_plan=solved.difference_vs_current_plan,
                available=solved.available,
                limitation=solved.limitation,
            )
        )
    earliest = tuple(
        _reach_row(
            as_of_date=as_of_date,
            current=current,
            contribution_plan=plan,
            fx_schedule=fx_schedule,
            goal=active_goal,
            starting_monthly=level,
            annual_return_rate=base_return_rate,
            horizon_end=horizon_end,
        )
        for level in first_reach_levels
    )
    sensitivity = tuple(
        _reach_row(
            as_of_date=as_of_date,
            current=current,
            contribution_plan=plan,
            fx_schedule=fx_schedule,
            goal=active_goal,
            starting_monthly=level,
            annual_return_rate=rate,
            horizon_end=horizon_end,
        )
        for level in sensitivity_levels
        for rate in sensitivity_returns
    )
    return ExtendedHorizonAnalysis(
        **{
            **base,
            "status": EXTENDED_HORIZON_AVAILABLE,
            "target_year_matrix": target_year_matrix,
            "required_monthly_by_goal_year": tuple(required_rows),
            "earliest_reach": earliest,
            "return_sensitivity": sensitivity,
        }
    )
