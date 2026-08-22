"""NABI Wealth Brief. Composes existing outputs; no new financial math."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence, Tuple

from components.portfolio_decision_center_ui import (
    HEALTHY_MESSAGE,
    ActionCenterPresentation,
    PresentedAction,
    present_action_center,
)
from services.portfolio_decision_intelligence import PortfolioDecisionView
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_goal_center_presentation import (
    GoalCenterDashboard,
    format_money_display,
)
from services.wealth_history_service import WealthHistoryState
from services.wealth_new_money_allocation import AllocationPlan
from services.wealth_new_money_allocation_presentation import (
    recommendation_reason_label,
)
from services.wealth_institution_center_presentation import InstitutionCenterView
from services.wealth_purification_zakat import PurificationZakatResult
from services.wealth_performance_center_presentation import (
    INSUFFICIENT_COPY,
    PerformanceCenterView,
    PerformancePeriod,
)
from services.wealth_snapshot_serializer import valuation_is_complete

BRIEF_TITLE = "NABI Wealth Brief"
SECTION_TODAY = "Bugünün Özeti"
SECTION_PRIORITY = "NABI'nin Önceliği"
SECTION_GOAL = "2031 Hedefi"
SECTION_NEW_MONEY = "Yeni Para"
SECTION_PERFORMANCE = "Performans"
DETAILS_EXPANDER = "Detaylar"
VALUATION_COMPLETE_LABEL = "Değerleme tamam"
VALUATION_PARTIAL_LABEL = "Değerleme kısmi — gösterilen tutar alt sınırdır."
ALLOCATION_LIMIT_COPY = {
    "TARGET_NOT_CONFIGURED": "Kayıtlı hedef dağılım yok; dağılım önerisi üretilemedi.",
    "NON_POSITIVE_AMOUNT": "Dağıtılacak tutar yok.",
}
MAX_ALLOCATION_PREVIEW = 3


@dataclass(frozen=True)
class BriefHeader:
    title: str
    current_value_label: str
    valuation_status: str
    valuation_complete: bool
    as_of_label: str


@dataclass(frozen=True)
class BriefPriority:
    healthy: bool
    title: str
    severity_label: Optional[str]
    explanation: str
    evidence_lines: Tuple[str, ...]
    options: Tuple[str, ...]


@dataclass(frozen=True)
class BriefGoal:
    target_label: str
    current_progress: str
    projected_wealth_label: str
    attainment_label: str
    configured_monthly_label: str
    required_monthly_label: str
    target_date_alternative: Optional[str]
    status_copy: str


@dataclass(frozen=True)
class BriefAllocationRow:
    symbol: str
    kind_label: str
    amount_label: str
    reason: str


@dataclass(frozen=True)
class BriefNewMoney:
    amount_label: str
    allocated_label: str
    residual_label: str
    recommendations: Tuple[BriefAllocationRow, ...]
    unavailable_reason: Optional[str]


@dataclass(frozen=True)
class BriefPerformance:
    period_label: str
    return_label: Optional[str]
    best_label: Optional[str]
    weakest_label: Optional[str]
    limitation: Optional[str]


@dataclass(frozen=True)
class WealthBrief:
    header: BriefHeader
    today_lines: Tuple[str, ...]
    priority: BriefPriority
    goal: BriefGoal
    new_money: BriefNewMoney
    performance: BriefPerformance
    limitations: Tuple[str, ...]
    tracking_prestart_copy: Optional[str]


def _valuation_complete(portfolio_view: PortfolioIntelligenceView, dashboard: GoalCenterDashboard) -> bool:
    if not dashboard.snapshot.valuation_complete:
        return False
    return valuation_is_complete(portfolio_view)


def _today_lines(
    *,
    dashboard: GoalCenterDashboard,
    presented: ActionCenterPresentation,
    priority: BriefPriority,
    valuation_complete: bool,
    institution_line: Optional[str] = None,
    purification_line: Optional[str] = None,
) -> Tuple[str, ...]:
    lines = [f"Ölçülebilen servet: {dashboard.header.current_wealth_label}."]
    if not valuation_complete:
        lines.append(VALUATION_PARTIAL_LABEL)
    lines.extend(
        [
            dashboard.header.progress_caption + ".",
            dashboard.current_plan.status_copy,
        ]
    )
    if institution_line:
        lines.append(institution_line)
    if purification_line:
        lines.append(purification_line)
    if priority.healthy:
        lines.append(HEALTHY_MESSAGE)
    else:
        lines.append(f"Öncelik: {priority.title}.")
    if dashboard.tracking_prestart_copy:
        lines.append(dashboard.tracking_prestart_copy)
    return tuple(lines)


def _priority(presented: ActionCenterPresentation) -> BriefPriority:
    if presented.healthy or presented.actionable_count == 0:
        return BriefPriority(
            healthy=True,
            title=HEALTHY_MESSAGE,
            severity_label=None,
            explanation=HEALTHY_MESSAGE,
            evidence_lines=(),
            options=(),
        )
    action: Optional[PresentedAction] = next(
        (row for row in presented.visible_actions if row.id != "continue_observation"),
        None,
    )
    if action is None:
        return BriefPriority(
            healthy=True,
            title=HEALTHY_MESSAGE,
            severity_label=None,
            explanation=HEALTHY_MESSAGE,
            evidence_lines=(),
            options=(),
        )
    return BriefPriority(
        healthy=False,
        title=action.title,
        severity_label=action.priority_label,
        explanation=action.explanation,
        evidence_lines=action.evidence_lines[:3],
        options=action.options,
    )


def _goal(dashboard: GoalCenterDashboard) -> BriefGoal:
    alt = None
    if dashboard.target_date_alternative.available and dashboard.target_date_alternative.reach_date_label:
        alt = dashboard.target_date_alternative.reach_date_label
    return BriefGoal(
        target_label=dashboard.header.target_wealth_label,
        current_progress=dashboard.header.progress_caption,
        projected_wealth_label=dashboard.current_plan.projected_wealth_label,
        attainment_label=dashboard.current_plan.attainment_label,
        configured_monthly_label=dashboard.current_plan.starting_monthly_label,
        required_monthly_label=dashboard.required.required_label,
        target_date_alternative=alt,
        status_copy=dashboard.current_plan.status_copy,
    )


def _new_money(
    dashboard: GoalCenterDashboard,
    allocation: Optional[AllocationPlan],
    unavailable_reason: Optional[str],
) -> BriefNewMoney:
    amount = format_money_display(dashboard.plan.starting_monthly, dashboard.plan.currency)
    if allocation is None:
        return BriefNewMoney(
            amount_label=amount,
            allocated_label="—",
            residual_label="—",
            recommendations=(),
            unavailable_reason=unavailable_reason or "Dağılım önerisi üretilemedi.",
        )
    reason = unavailable_reason
    if allocation.recommendations == () and allocation.limitations:
        code = allocation.limitations[0]
        reason = ALLOCATION_LIMIT_COPY.get(code, code)
    rows = []
    for rec in allocation.recommendations[:MAX_ALLOCATION_PREVIEW]:
        kind = "Mevcut pozisyon" if rec.existing_or_new == "existing" else "Yeni fırsat"
        rows.append(
            BriefAllocationRow(
                symbol=rec.symbol,
                kind_label=kind,
                amount_label=format_money_display(rec.allocated_amount, allocation.currency),
                reason=recommendation_reason_label(rec),
            )
        )
    return BriefNewMoney(
        amount_label=amount,
        allocated_label=format_money_display(allocation.total_allocated, allocation.currency),
        residual_label=format_money_display(allocation.residual_cash, allocation.currency),
        recommendations=tuple(rows),
        unavailable_reason=reason if not rows else None,
    )


def _performance(view: Optional[PerformanceCenterView]) -> BriefPerformance:
    if view is None:
        return BriefPerformance(
            period_label=PerformancePeriod.MONTHLY.value,
            return_label=None,
            best_label=None,
            weakest_label=None,
            limitation=INSUFFICIENT_COPY,
        )
    history = view.history
    return_label = None
    if (
        view.sufficient
        and history is not None
        and history.history_state == WealthHistoryState.COMPARABLE
        and history.return_pct is not None
    ):
        return_label = f"{float(history.return_pct):.2f}%"
    best = view.best[0] if view.best else None
    weak = view.weakest[0] if view.weakest else None
    limitation = None
    if not view.sufficient or return_label is None:
        limitation = view.insufficient_reason or INSUFFICIENT_COPY
    return BriefPerformance(
        period_label=view.period.value,
        return_label=return_label,
        best_label=f"{best.symbol} {float(best.period_return) * 100:.1f}%" if best and best.period_return is not None else None,
        weakest_label=f"{weak.symbol} {float(weak.period_return) * 100:.1f}%" if weak and weak.period_return is not None else None,
        limitation=limitation,
    )


def _limitations(
    *,
    dashboard: GoalCenterDashboard,
    valuation_complete: bool,
    performance: BriefPerformance,
    new_money: BriefNewMoney,
) -> Tuple[str, ...]:
    notes: list[str] = []
    if not valuation_complete:
        notes.append(VALUATION_PARTIAL_LABEL)
        if dashboard.data_quality.partial_warning:
            notes.append(dashboard.data_quality.partial_warning)
    if dashboard.data_quality.fx_warning:
        notes.append(dashboard.data_quality.fx_warning)
    if dashboard.data_quality.missing_fx_years:
        notes.append("Planlama kur varsayımları eksik.")
    if performance.limitation:
        notes.append(performance.limitation)
    if new_money.unavailable_reason:
        notes.append(new_money.unavailable_reason)
    return tuple(dict.fromkeys(notes))


def build_wealth_brief(
    *,
    as_of_date: date,
    portfolio_view: PortfolioIntelligenceView,
    dashboard: GoalCenterDashboard,
    decision: PortfolioDecisionView,
    allocation: Optional[AllocationPlan] = None,
    allocation_unavailable_reason: Optional[str] = None,
    performance: Optional[PerformanceCenterView] = None,
    institution_center: Optional[InstitutionCenterView] = None,
    purification_zakat: Optional[PurificationZakatResult] = None,
) -> WealthBrief:
    """Compose canonical Goal / Decision / Allocation / Performance outputs."""
    presented = present_action_center(decision)
    valuation_complete = _valuation_complete(portfolio_view, dashboard)
    priority = _priority(presented)
    goal = _goal(dashboard)
    new_money = _new_money(dashboard, allocation, allocation_unavailable_reason)
    performance_preview = _performance(performance)
    institution_line = None
    if institution_center is not None and valuation_complete:
        institution_line = institution_center.brief_line
    purification_line = None
    if purification_zakat is not None:
        purification_line = purification_zakat.brief_line
    return WealthBrief(
        header=BriefHeader(
            title=BRIEF_TITLE,
            current_value_label=dashboard.header.current_wealth_label,
            valuation_status=(
                VALUATION_COMPLETE_LABEL if valuation_complete else VALUATION_PARTIAL_LABEL
            ),
            valuation_complete=valuation_complete,
            as_of_label=as_of_date.isoformat(),
        ),
        today_lines=_today_lines(
            dashboard=dashboard,
            presented=presented,
            priority=priority,
            valuation_complete=valuation_complete,
            institution_line=institution_line,
            purification_line=purification_line,
        ),
        priority=priority,
        goal=goal,
        new_money=new_money,
        performance=performance_preview,
        limitations=_limitations(
            dashboard=dashboard,
            valuation_complete=valuation_complete,
            performance=performance_preview,
            new_money=new_money,
        ),
        tracking_prestart_copy=dashboard.tracking_prestart_copy,
    )
