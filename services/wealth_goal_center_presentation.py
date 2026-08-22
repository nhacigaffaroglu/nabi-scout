"""Goal Center presentation models.

Translates canonical Goal Engine, scenario, and Decision Intelligence outputs
into dashboard copy. Does not recompute valuation, projection, required
contribution, planning FX, or contribution accounting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from services.portfolio_decision_intelligence import PortfolioDecisionView
from services.wealth_contribution_intelligence import ContributionIntelligenceView
from services.wealth_external_cash_flow import ContributionTrackingScope
from services.wealth_goal_models import (
    COMPOUNDING_CONVENTION,
    ContributionPlan,
    CurrentWealthSnapshot,
    GoalEvidenceStatus,
    ProjectionResult,
    WealthGoal,
)
from services.wealth_goal_planning import solve_required_starting_monthly
from services.wealth_goal_scenario_service import (
    BASE_RETURN_RATE,
    EXTENDED_HORIZON_BLOCKED,
    EXTENDED_HORIZON_END,
    MATRIX_CONTRIBUTION_LEVELS_TRY,
    EarliestReachRow,
    ScenarioProjection,
    earliest_target_reach,
    project_scenario,
)
from services.wealth_planning_fx import (
    PlanningFxCompleteness,
    PlanningFxSchedule,
    missing_years_copy,
    required_planning_fx_years,
)

GOAL_HEADER_TITLE = "2031 Servet Hedefi"
PLAN_STATUS_TARGET_REACHED = "Hedefe ulaşılıyor."
PLAN_STATUS_SHORTFALL = "Mevcut plan 2031 hedefi için yeterli görünmüyor."
PLAN_STATUS_INDETERMINATE = "Mevcut veriler hedef değerlendirmesi için yeterli değil."
PARTIAL_NOT_DECISION_GRADE = (
    "Kısmi değerleme: hedef sonuçları karar kalitesinde değildir."
)
SCENARIO_EXPLORER_DISCLAIMER = (
    "Bu yalnızca senaryodur; mevcut planınızı değiştirmez."
)
TRACKING_STARTS_TEMPLATE = "Katkı takibi {when} tarihinde başlayacak."
NABI_BELOW_REQUIRED_TEMPLATE = (
    "2031 hedefi mevcut katkı planıyla yakalanamıyor. "
    "Aylık başlangıç katkısının yaklaşık {required} seviyesine çıkması "
    "veya hedef tarihinin uzatılması gerekiyor."
)
NABI_ON_TRACK = "Mevcut plan, 2031 hedefine ulaşmayı destekliyor."
NABI_INDETERMINATE = "Mevcut veriler hedef değerlendirmesi için yeterli değil."
NABI_PARTIAL = (
    "Değerleme kısmi olduğu için NABI değerlendirmesi karar kalitesinde değildir."
)
NABI_NO_PLAN_SIGNAL = "Şu anda katkı planı için ek bir uyarı yok."

_MONTHS_TR = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
}

SCENARIO_CARD_LEVELS = MATRIX_CONTRIBUTION_LEVELS_TRY[:3]


def format_long_date_tr(value: date) -> str:
    return f"{value.day} {_MONTHS_TR[value.month]} {value.year}"


def format_money_display(value: Optional[Decimal | float], currency: str) -> str:
    if value is None:
        return "—"
    amount = float(value)
    code = currency.strip().upper()
    if code == "USD":
        return f"${amount:,.0f}"
    if code == "TRY":
        return f"{amount:,.0f} TL"
    return f"{amount:,.0f} {code}"


def format_pct_display(value: Optional[Decimal | float]) -> str:
    if value is None:
        return "—"
    return f"%{float(value):.1f}"


def plan_status_copy(status: GoalEvidenceStatus) -> str:
    if status in (GoalEvidenceStatus.REACHED, GoalEvidenceStatus.PROJECTED_TO_REACH):
        return PLAN_STATUS_TARGET_REACHED
    if status == GoalEvidenceStatus.PROJECTED_SHORTFALL:
        return PLAN_STATUS_SHORTFALL
    return PLAN_STATUS_INDETERMINATE


def contribution_tracking_starts_copy(tracking_start: date) -> str:
    return TRACKING_STARTS_TEMPLATE.format(when=format_long_date_tr(tracking_start))


def _safe_pct_increase(required: Decimal, current: Decimal) -> Optional[Decimal]:
    if current <= 0:
        return None
    return ((required - current) / current) * Decimal("100")


@dataclass(frozen=True)
class GoalHeaderPresentation:
    title: str
    current_wealth_label: str
    target_wealth_label: str
    progress_pct: Decimal
    progress_caption: str
    measurable_gap_label: Optional[str]
    valuation_complete: bool


@dataclass(frozen=True)
class CurrentPlanPresentation:
    starting_monthly_label: str
    annual_increase_label: str
    base_return_label: str
    projected_wealth_label: str
    attainment_label: str
    gap_label: str
    gap_is_surplus: bool
    status: GoalEvidenceStatus
    status_copy: str
    projection_complete: bool


@dataclass(frozen=True)
class RequiredContributionPresentation:
    required_label: str
    current_label: str
    difference_label: str
    pct_increase_label: Optional[str]
    available: bool
    required_monthly: Optional[Decimal]


@dataclass(frozen=True)
class TargetDateAlternativePresentation:
    available: bool
    reach_year: Optional[int]
    reach_date_label: Optional[str]
    missing_fx_years: Tuple[int, ...]
    blocked: bool


@dataclass(frozen=True)
class ScenarioCardPresentation:
    starting_monthly: Decimal
    monthly_label: str
    projected_2031_label: str
    attainment_label: str
    earliest_year_label: str
    projected_wealth: Optional[Decimal]
    attainment_pct: Optional[Decimal]
    earliest_year: Optional[int]


@dataclass(frozen=True)
class NabiEvaluationPresentation:
    copy: str
    signal_id: Optional[str]


@dataclass(frozen=True)
class DataQualityPresentation:
    valuation_complete: bool
    decision_grade: bool
    missing_fx_years: Tuple[int, ...]
    partial_warning: Optional[str]
    fx_warning: Optional[str]
    show_technical_warnings: bool


@dataclass(frozen=True)
class GoalCenterDashboard:
    as_of_date: date
    goal: WealthGoal
    plan: ContributionPlan
    snapshot: CurrentWealthSnapshot
    fx_schedule: PlanningFxSchedule
    header: GoalHeaderPresentation
    current_plan: CurrentPlanPresentation
    required: RequiredContributionPresentation
    target_date_alternative: TargetDateAlternativePresentation
    scenario_cards: Tuple[ScenarioCardPresentation, ...]
    nabi: NabiEvaluationPresentation
    data_quality: DataQualityPresentation
    tracking_start: Optional[date]
    tracking_prestart_copy: Optional[str]
    monthly_tracking_scope: ContributionTrackingScope
    compounding_convention: str
    baseline: ScenarioProjection
    earliest_current_plan: EarliestReachRow
    base_projection: Optional[ProjectionResult]


def _progress_caption(progress_pct: Decimal, *, complete: bool) -> str:
    label = format_pct_display(progress_pct)
    if complete:
        return f"Hedefin {label}'u tamamlandı"
    return f"Hedefin en az {label}'u ölçüldü"


def _nabi_copy(
    *,
    snapshot: CurrentWealthSnapshot,
    status: GoalEvidenceStatus,
    required_label: Optional[str],
    decision: Optional[PortfolioDecisionView],
) -> NabiEvaluationPresentation:
    if not snapshot.valuation_complete:
        return NabiEvaluationPresentation(copy=NABI_PARTIAL, signal_id=None)
    signal = None
    if decision is not None:
        signal = next(
            (row for row in decision.actions if row.id == "contribution_plan_below_required"),
            None,
        )
    if signal is not None and required_label:
        return NabiEvaluationPresentation(
            copy=NABI_BELOW_REQUIRED_TEMPLATE.format(required=required_label),
            signal_id=signal.id,
        )
    if status in (GoalEvidenceStatus.REACHED, GoalEvidenceStatus.PROJECTED_TO_REACH):
        return NabiEvaluationPresentation(copy=NABI_ON_TRACK, signal_id=None)
    if status == GoalEvidenceStatus.INDETERMINATE:
        return NabiEvaluationPresentation(copy=NABI_INDETERMINATE, signal_id=None)
    if status == GoalEvidenceStatus.PROJECTED_SHORTFALL and required_label:
        return NabiEvaluationPresentation(
            copy=NABI_BELOW_REQUIRED_TEMPLATE.format(required=required_label),
            signal_id="contribution_plan_below_required",
        )
    return NabiEvaluationPresentation(copy=NABI_NO_PLAN_SIGNAL, signal_id=None)


def _card_from_engines(
    *,
    projected: ScenarioProjection,
    reach: EarliestReachRow,
    currency: str,
) -> ScenarioCardPresentation:
    year_label = "—"
    if reach.reached and reach.reach_year is not None:
        year_label = str(reach.reach_year)
    elif reach.label == EXTENDED_HORIZON_BLOCKED:
        year_label = "Kur varsayımı eksik"
    elif not reach.reached:
        year_label = reach.label
    return ScenarioCardPresentation(
        starting_monthly=projected.starting_monthly,
        monthly_label=f"{format_money_display(projected.starting_monthly, currency)} / ay",
        projected_2031_label=format_money_display(projected.projected_wealth, "USD"),
        attainment_label=format_pct_display(projected.attainment_pct),
        earliest_year_label=year_label,
        projected_wealth=projected.projected_wealth,
        attainment_pct=projected.attainment_pct,
        earliest_year=reach.reach_year if reach.reached else None,
    )


def build_goal_center_dashboard(
    *,
    as_of_date: date,
    goal: WealthGoal,
    plan: ContributionPlan,
    snapshot: CurrentWealthSnapshot,
    fx_schedule: PlanningFxSchedule,
    intelligence: ContributionIntelligenceView,
    tracking_start: Optional[date],
    decision: Optional[PortfolioDecisionView] = None,
    bands: Sequence[ProjectionResult] = (),
    scenario_levels: Sequence[Decimal] = SCENARIO_CARD_LEVELS,
    base_return_rate: Decimal = BASE_RETURN_RATE,
) -> GoalCenterDashboard:
    baseline = project_scenario(
        as_of_date=as_of_date,
        current=snapshot,
        contribution_plan=plan,
        annual_return_rate=base_return_rate,
        fx_schedule=fx_schedule,
        goal=goal,
    )
    base_row = next((row for row in bands if row.scenario_name == "Base"), None)
    engine_status = (
        baseline.engine_result.status
        if baseline.engine_result is not None
        else GoalEvidenceStatus.INDETERMINATE
    )
    progress = (
        base_row.progress_pct_lower_bound
        if base_row is not None
        else (
            baseline.engine_result.progress_pct_lower_bound
            if baseline.engine_result is not None
            else Decimal("0")
        )
    )
    measurable_gap = None
    if base_row is not None:
        measurable_gap = format_money_display(base_row.measurable_gap, goal.currency)
    elif baseline.engine_result is not None:
        measurable_gap = format_money_display(
            baseline.engine_result.measurable_gap, goal.currency
        )

    solved = solve_required_starting_monthly(
        as_of_date=as_of_date,
        current=snapshot,
        contribution_currency=plan.currency,
        annual_increase_rate=plan.annual_increase_rate,
        annual_return_rate=base_return_rate,
        fx_schedule=fx_schedule,
        goal=goal,
    )
    required_monthly = solved.starting_monthly if solved.available else None
    difference = None
    pct_increase = None
    if required_monthly is not None:
        difference = required_monthly - plan.starting_monthly
        pct_increase = _safe_pct_increase(required_monthly, plan.starting_monthly)

    horizon_missing = fx_schedule.missing_years(
        required_planning_fx_years(as_of_date, EXTENDED_HORIZON_END)
    )
    earliest = earliest_target_reach(
        as_of_date=as_of_date,
        current=snapshot,
        contribution_plan=plan,
        fx_schedule=fx_schedule,
        goal=goal,
        annual_return_rate=base_return_rate,
    )
    cards = []
    for level in scenario_levels:
        projected = project_scenario(
            as_of_date=as_of_date,
            current=snapshot,
            contribution_plan=plan,
            annual_return_rate=base_return_rate,
            fx_schedule=fx_schedule,
            goal=goal,
            starting_monthly=level,
        )
        reach = earliest_target_reach(
            as_of_date=as_of_date,
            current=snapshot,
            contribution_plan=plan,
            fx_schedule=fx_schedule,
            goal=goal,
            starting_monthly=level,
            annual_return_rate=base_return_rate,
        )
        cards.append(
            _card_from_engines(projected=projected, reach=reach, currency=plan.currency)
        )

    goal_years = required_planning_fx_years(as_of_date, goal.target_date)
    missing_goal_fx = fx_schedule.missing_years(goal_years)
    completeness = fx_schedule.completeness(
        as_of=as_of_date,
        target_date=goal.target_date,
        contribution_currency=plan.currency,
        goal_currency=goal.currency,
    )
    fx_warning = None
    if completeness == PlanningFxCompleteness.NONE:
        fx_warning = missing_years_copy(missing_goal_fx) if missing_goal_fx else None
    elif completeness == PlanningFxCompleteness.PARTIAL:
        fx_warning = missing_years_copy(missing_goal_fx)
    partial_warning = None if snapshot.valuation_complete else PARTIAL_NOT_DECISION_GRADE
    decision_grade = snapshot.valuation_complete and completeness in (
        PlanningFxCompleteness.COMPLETE,
        PlanningFxCompleteness.NOT_REQUIRED,
    )

    gap = baseline.surplus_or_shortfall
    gap_is_surplus = bool(gap is not None and gap >= 0)
    gap_label = format_money_display(gap, goal.currency)
    if gap is not None and not gap_is_surplus:
        gap_label = f"-{format_money_display(abs(gap), goal.currency)}"

    required_label = format_money_display(required_monthly, plan.currency)
    header = GoalHeaderPresentation(
        title=GOAL_HEADER_TITLE,
        current_wealth_label=format_money_display(
            snapshot.current_value_lower_bound, snapshot.currency
        ),
        target_wealth_label=format_money_display(goal.target_amount, goal.currency),
        progress_pct=progress,
        progress_caption=_progress_caption(progress, complete=snapshot.valuation_complete),
        measurable_gap_label=measurable_gap,
        valuation_complete=snapshot.valuation_complete,
    )
    current_plan = CurrentPlanPresentation(
        starting_monthly_label=f"{format_money_display(plan.starting_monthly, plan.currency)} / ay",
        annual_increase_label=format_pct_display(plan.annual_increase_rate * Decimal("100")),
        base_return_label=format_pct_display(base_return_rate * Decimal("100")),
        projected_wealth_label=format_money_display(baseline.projected_wealth, goal.currency),
        attainment_label=format_pct_display(baseline.attainment_pct),
        gap_label=gap_label,
        gap_is_surplus=gap_is_surplus,
        status=engine_status,
        status_copy=plan_status_copy(engine_status),
        projection_complete=baseline.projection_complete,
    )
    required = RequiredContributionPresentation(
        required_label=required_label if solved.available else "—",
        current_label=format_money_display(plan.starting_monthly, plan.currency),
        difference_label=format_money_display(difference, plan.currency) if difference is not None else "—",
        pct_increase_label=format_pct_display(pct_increase) if pct_increase is not None else None,
        available=solved.available,
        required_monthly=required_monthly,
    )
    target_alt = TargetDateAlternativePresentation(
        available=earliest.reached,
        reach_year=earliest.reach_year,
        reach_date_label=(
            format_long_date_tr(earliest.reach_date) if earliest.reach_date else None
        ),
        missing_fx_years=tuple(horizon_missing),
        blocked=earliest.label == EXTENDED_HORIZON_BLOCKED,
    )
    prestart = None
    if (
        tracking_start is not None
        and intelligence.monthly_tracking_scope == ContributionTrackingScope.NOT_TRACKED
    ):
        prestart = contribution_tracking_starts_copy(tracking_start)

    return GoalCenterDashboard(
        as_of_date=as_of_date,
        goal=goal,
        plan=plan,
        snapshot=snapshot,
        fx_schedule=fx_schedule,
        header=header,
        current_plan=current_plan,
        required=required,
        target_date_alternative=target_alt,
        scenario_cards=tuple(cards),
        nabi=_nabi_copy(
            snapshot=snapshot,
            status=engine_status,
            required_label=required.required_label if required.available else None,
            decision=decision,
        ),
        data_quality=DataQualityPresentation(
            valuation_complete=snapshot.valuation_complete,
            decision_grade=decision_grade,
            missing_fx_years=missing_goal_fx,
            partial_warning=partial_warning,
            fx_warning=fx_warning,
            show_technical_warnings=bool(partial_warning or fx_warning),
        ),
        tracking_start=tracking_start,
        tracking_prestart_copy=prestart,
        monthly_tracking_scope=intelligence.monthly_tracking_scope,
        compounding_convention=COMPOUNDING_CONVENTION,
        baseline=baseline,
        earliest_current_plan=earliest,
        base_projection=baseline.engine_result,
    )


def explorer_is_read_only() -> bool:
    """Scenario explorer never persists plan, return, target, or planning FX."""
    return True
