from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from services.wealth_goal_models import (
    ContributionPlan,
    ConversionAssumption,
    CurrentWealthSnapshot,
    GoalEvidenceStatus,
    ProjectionLimitation,
    ProjectionResult,
    ReturnScenario,
    WealthGoal,
    default_wealth_goal_2031,
    quantize_money,
)
from services.wealth_performance_engine import aggregate_cash_flows
from services.wealth_projection_engine import project_wealth_goal

PLANNING_ASSUMPTION_NOTE = "Planlama varsayımı — tahmin değildir."
USER_ASSUMPTION_NOTE = "Kullanıcı varsayımı; NABI tahmini değildir."


@dataclass(frozen=True)
class ContributionYearRow:
    year: int
    monthly: Decimal
    annual_total: Decimal


@dataclass(frozen=True)
class PlanVsActual:
    year: int
    currency: str
    planned_year_total: Decimal
    actual_net_external: Optional[Decimal]
    difference: Optional[Decimal]
    completion_pct: Optional[Decimal]
    available: bool
    evidence_partial: bool
    warnings: Tuple[str, ...]


@dataclass(frozen=True)
class RequiredContributionResult:
    available: bool
    starting_monthly: Optional[Decimal]
    currency: str
    projected_target_date_value: Optional[Decimal]
    limitation: Optional[ProjectionLimitation]
    iterations: int


def monthly_for_year(plan: ContributionPlan, *, as_of: date, year: int) -> Decimal:
    """Same calendar-year step-up the projection engine uses: year - as_of.year."""
    plan.validate()
    offset = max(0, year - as_of.year)
    amount = plan.starting_monthly * ((Decimal(1) + plan.annual_increase_rate) ** offset)
    return quantize_money(amount)


def contribution_year_schedule(
    plan: ContributionPlan,
    *,
    as_of: date,
    through_year: int,
) -> Tuple[ContributionYearRow, ...]:
    rows = []
    for year in range(as_of.year, through_year + 1):
        monthly = monthly_for_year(plan, as_of=as_of, year=year)
        rows.append(
            ContributionYearRow(
                year=year,
                monthly=monthly,
                annual_total=quantize_money(monthly * Decimal(12)),
            )
        )
    return tuple(rows)


def current_year_plan_row(
    plan: ContributionPlan,
    *,
    as_of: date,
    through_year: int,
) -> ContributionYearRow:
    schedule = contribution_year_schedule(plan, as_of=as_of, through_year=through_year)
    for row in schedule:
        if row.year == as_of.year:
            return row
    return schedule[0]


def _year_flow_window(year: int, as_of: date) -> Tuple[datetime, datetime]:
    start = datetime(year, 1, 1, tzinfo=timezone.utc) - timedelta(microseconds=1)
    last = min(as_of, date(year, 12, 31))
    end = datetime.combine(last, time(23, 59, 59), tzinfo=timezone.utc)
    return start, end


def plan_vs_actual_for_year(
    plan: ContributionPlan,
    *,
    as_of: date,
    transactions: Iterable[Dict[str, Any]],
    account_ids: Sequence[str],
    year: Optional[int] = None,
) -> PlanVsActual:
    """Actual net external contributions via existing performance cash-flow rules.

    Deposits minus withdrawals in the plan currency. Transfers, dividends,
    trades, fees, and unrealized P/L are not contributions.
    """
    plan.validate()
    target_year = year or as_of.year
    planned = monthly_for_year(plan, as_of=as_of, year=target_year) * Decimal(12)
    planned = quantize_money(planned)
    ids = {str(item) for item in account_ids if str(item or "").strip()}
    txn_list = list(transactions)
    has_buy = any(str(row.get("txn_type") or "").strip().lower() == "buy" for row in txn_list)
    opening_note = (
        "Açılış/alış kayıtları nakit katkı sayılmaz. Gerçekleşen katkı geçmişi kısmi veya yok."
    )
    if not ids:
        return PlanVsActual(
            year=target_year,
            currency=plan.currency,
            planned_year_total=planned,
            actual_net_external=None,
            difference=None,
            completion_pct=None,
            available=False,
            evidence_partial=True,
            warnings=("Hesap bulunamadı; gerçekleşen katkı kanıtı yok.",),
        )

    period_start, period_end = _year_flow_window(target_year, as_of)
    inflows, outflows, _div, _fee, warnings = aggregate_cash_flows(
        txn_list,
        account_ids=ids,
        base_currency=plan.currency,
        period_start=period_start,
        period_end=period_end,
    )
    skipped_external = tuple(
        item
        for item in warnings
        if "Skipped" in str(item)
        and any(token in str(item) for token in ("deposit", "withdraw"))
    )
    notes = list(skipped_external)
    if skipped_external and inflows == 0 and outflows == 0:
        if has_buy:
            notes.append(opening_note)
        return PlanVsActual(
            year=target_year,
            currency=plan.currency,
            planned_year_total=planned,
            actual_net_external=None,
            difference=None,
            completion_pct=None,
            available=False,
            evidence_partial=True,
            warnings=tuple(notes)
            or ("Gerçekleşen katkı, plan para biriminde ölçülemedi.",),
        )

    actual = quantize_money(Decimal(str(inflows - outflows)))
    difference = quantize_money(actual - planned)
    completion = (
        quantize_money((actual / planned) * Decimal(100)) if planned > 0 else None
    )
    evidence_partial = has_buy and actual == 0
    if evidence_partial:
        notes.append(opening_note)
    return PlanVsActual(
        year=target_year,
        currency=plan.currency,
        planned_year_total=planned,
        actual_net_external=actual,
        difference=difference,
        completion_pct=None if evidence_partial else completion,
        available=True,
        evidence_partial=evidence_partial,
        warnings=tuple(notes),
    )


def build_what_if_projection(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    monthly_contribution: Decimal,
    contribution_currency: str,
    annual_increase_rate: Decimal,
    annual_return_rate: Decimal,
    target_date: Optional[date] = None,
    conversion: Optional[ConversionAssumption] = None,
    goal: Optional[WealthGoal] = None,
) -> ProjectionResult:
    base_goal = goal or default_wealth_goal_2031()
    if target_date is not None:
        base_goal = WealthGoal(
            name=base_goal.name,
            target_amount=base_goal.target_amount,
            target_date=target_date,
            currency=base_goal.currency,
        )
    plan = ContributionPlan(
        starting_monthly=monthly_contribution,
        currency=contribution_currency,
        annual_increase_rate=annual_increase_rate,
    )
    return project_wealth_goal(
        goal=base_goal,
        as_of_date=as_of_date,
        current=current,
        contribution_plan=plan,
        scenario=ReturnScenario("What-if", annual_return_rate),
        conversion=conversion,
    )


def projected_surplus(result: ProjectionResult) -> Optional[Decimal]:
    if result.projected_target_date_value is None:
        return None
    return quantize_money(result.projected_target_date_value - result.target_amount)


def solve_required_starting_monthly(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    contribution_currency: str,
    annual_increase_rate: Decimal,
    annual_return_rate: Decimal,
    conversion: Optional[ConversionAssumption] = None,
    goal: Optional[WealthGoal] = None,
    tolerance: Decimal = Decimal("1.00"),
    max_monthly: Decimal = Decimal("100000000"),
) -> RequiredContributionResult:
    """Binary search for the smallest starting monthly contribution that reaches the goal."""
    base_goal = goal or default_wealth_goal_2031()
    currency = str(contribution_currency or "").strip().upper()
    scenario = ReturnScenario("Required", annual_return_rate)

    def _run(monthly: Decimal) -> ProjectionResult:
        return project_wealth_goal(
            goal=base_goal,
            as_of_date=as_of_date,
            current=current,
            contribution_plan=ContributionPlan(
                starting_monthly=monthly,
                currency=currency,
                annual_increase_rate=annual_increase_rate,
            ),
            scenario=scenario,
            conversion=conversion,
        )

    probe = _run(Decimal("0"))
    if ProjectionLimitation.FX_CONVERSION_REQUIRED in probe.limitations:
        return RequiredContributionResult(
            available=False,
            starting_monthly=None,
            currency=currency,
            projected_target_date_value=None,
            limitation=ProjectionLimitation.FX_CONVERSION_REQUIRED,
            iterations=1,
        )
    if not probe.projection_complete and probe.status != GoalEvidenceStatus.REACHED:
        limitation = probe.limitations[0] if probe.limitations else None
        return RequiredContributionResult(
            available=False,
            starting_monthly=None,
            currency=currency,
            projected_target_date_value=None,
            limitation=limitation,
            iterations=1,
        )
    if probe.status == GoalEvidenceStatus.REACHED or (
        probe.projected_target_date_value is not None
        and probe.projected_target_date_value + tolerance >= base_goal.target_amount
    ):
        return RequiredContributionResult(
            available=True,
            starting_monthly=Decimal("0.00"),
            currency=currency,
            projected_target_date_value=probe.projected_target_date_value,
            limitation=None,
            iterations=1,
        )

    def _reaches(monthly: Decimal) -> Tuple[bool, ProjectionResult]:
        result = _run(monthly)
        value = result.projected_target_date_value
        ok = (
            result.projection_complete
            and value is not None
            and value + tolerance >= base_goal.target_amount
        )
        return ok, result

    high = Decimal("1")
    iterations = 1
    high_result: Optional[ProjectionResult] = None
    while high <= max_monthly:
        ok, high_result = _reaches(high)
        iterations += 1
        if ok:
            break
        high *= Decimal("2")
    else:
        return RequiredContributionResult(
            available=False,
            starting_monthly=None,
            currency=currency,
            projected_target_date_value=None,
            limitation=None,
            iterations=iterations,
        )

    low = Decimal("0")
    best = high
    best_result = high_result
    for _ in range(48):
        mid = quantize_money((low + high) / Decimal("2"))
        if mid <= low or mid >= high:
            break
        ok, result = _reaches(mid)
        iterations += 1
        if ok:
            high = mid
            best = mid
            best_result = result
        else:
            low = mid

    return RequiredContributionResult(
        available=True,
        starting_monthly=quantize_money(best),
        currency=currency,
        projected_target_date_value=(
            best_result.projected_target_date_value if best_result else None
        ),
        limitation=None,
        iterations=iterations,
    )


def planning_conversion(
    usdtry_rate: Optional[Decimal],
    *,
    contribution_currency: str = "TRY",
    goal_currency: str = "USD",
) -> Optional[ConversionAssumption]:
    if usdtry_rate is None or usdtry_rate <= 0:
        return None
    from_ccy = contribution_currency.strip().upper()
    to_ccy = goal_currency.strip().upper()
    if from_ccy == to_ccy:
        return None
    return ConversionAssumption(from_ccy, to_ccy, usdtry_rate)
