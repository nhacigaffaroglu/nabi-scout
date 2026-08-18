from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.wealth_contribution_intelligence import (
    BASE_RETURN_RATE,
    ContributionEvidenceQuality,
    ContributionIntelligenceView,
    PerformanceEvidenceQuality,
    PlanAdequacyStatus,
    build_contribution_intelligence,
)
from services.wealth_goal_models import (
    ContributionPlan,
    ConversionAssumption,
    CurrentWealthSnapshot,
    WealthGoal,
    current_wealth_from_portfolio_view,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_history_service import WealthHistoryView
from services.wealth_timeline_contract import PortfolioSnapshotView

# Existing PI product review trigger (not a sell recommendation).
CONCENTRATION_REVIEW_THRESHOLD_PCT = CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT


class DecisionPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class DecisionCategory(str, Enum):
    DATA = "DATA"
    PLAN = "PLAN"
    PORTFOLIO = "PORTFOLIO"
    MONITOR = "MONITOR"


class DecisionActionStatus(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    INDETERMINATE = "INDETERMINATE"
    OBSERVE = "OBSERVE"


_PRIORITY_RANK = {
    DecisionPriority.CRITICAL: 0,
    DecisionPriority.HIGH: 1,
    DecisionPriority.MEDIUM: 2,
    DecisionPriority.LOW: 3,
    DecisionPriority.INFO: 4,
}
_CATEGORY_RANK = {
    DecisionCategory.DATA: 0,
    DecisionCategory.PLAN: 1,
    DecisionCategory.PORTFOLIO: 2,
    DecisionCategory.MONITOR: 3,
}


@dataclass(frozen=True)
class DecisionAction:
    id: str
    category: DecisionCategory
    priority: DecisionPriority
    title: str
    explanation: str
    evidence: Tuple[str, ...]
    status: DecisionActionStatus
    limitations: Tuple[str, ...] = ()
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category.value,
            "priority": self.priority.value,
            "title": self.title,
            "explanation": self.explanation,
            "evidence": list(self.evidence),
            "status": self.status.value,
            "limitations": list(self.limitations),
            "context": dict(self.context),
        }


@dataclass(frozen=True)
class PortfolioDecisionView:
    actions: Tuple[DecisionAction, ...]
    primary_action: DecisionAction
    evidence_complete: bool
    limitations: Tuple[str, ...]
    generated_from: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actions": [row.to_dict() for row in self.actions],
            "primary_action": self.primary_action.to_dict(),
            "evidence_complete": self.evidence_complete,
            "limitations": list(self.limitations),
            "generated_from": list(self.generated_from),
        }


def _sort_key(action: DecisionAction) -> Tuple[int, int, str]:
    return (
        _PRIORITY_RANK[action.priority],
        _CATEGORY_RANK[action.category],
        action.id,
    )


def _planning_fx_missing(plan: ContributionPlan, goal: WealthGoal, conversion) -> bool:
    return (
        plan.currency.strip().upper() != goal.currency.strip().upper()
        and conversion is None
    )


def _largest_priced_holding(
    view: PortfolioIntelligenceView,
) -> Optional[Tuple[str, float]]:
    priced = [
        row
        for row in view.priced_positions
        if row.included_in_base_totals and row.weight_pct is not None
    ]
    if not priced:
        return None
    top = max(priced, key=lambda row: float(row.weight_pct or 0.0))
    return str(top.symbol or ""), float(top.weight_pct or 0.0)


def _rule_partial_valuation(current: CurrentWealthSnapshot) -> Optional[DecisionAction]:
    if current.valuation_complete and not current.unvalued_symbols:
        return None
    symbols = current.unvalued_symbols
    listed = ", ".join(symbols) if symbols else "unpriced holdings"
    return DecisionAction(
        id="incomplete_valuation",
        category=DecisionCategory.DATA,
        priority=DecisionPriority.HIGH,
        title="Complete valuation evidence",
        explanation=(
            "Portfolio totals are a lower bound because some holdings are not "
            f"in the comparable base-currency valuation ({listed}). "
            "Missing prices remain unavailable and are never assigned a market value of zero."
        ),
        evidence=tuple(symbols) or ("PARTIAL_VALUATION",),
        status=DecisionActionStatus.OPEN,
        limitations=("PARTIAL_VALUATION", "LOWER_BOUND_MARKET_VALUE"),
        context={
            "unvalued_symbols": list(symbols),
            "current_value_lower_bound": str(current.current_value_lower_bound),
            "valuation_complete": False,
        },
    )


def _rule_planning_fx(
    plan: ContributionPlan,
    goal: WealthGoal,
    conversion: Optional[ConversionAssumption],
) -> Optional[DecisionAction]:
    if not _planning_fx_missing(plan, goal, conversion):
        return None
    return DecisionAction(
        id="missing_planning_fx",
        category=DecisionCategory.DATA,
        priority=DecisionPriority.HIGH,
        title="Planning assumption required",
        explanation=(
            f"{plan.currency}→{goal.currency} 2031 projection cannot be completed "
            "without an explicit planning FX assumption. No live FX rate is fetched "
            "or invented."
        ),
        evidence=(f"{plan.currency}->{goal.currency}",),
        status=DecisionActionStatus.BLOCKED,
        limitations=("FX_CONVERSION_REQUIRED",),
        context={
            "from_currency": plan.currency,
            "to_currency": goal.currency,
            "conversion_present": False,
        },
    )


def _rule_contribution_evidence(
    contribution: ContributionIntelligenceView,
) -> Optional[DecisionAction]:
    if contribution.evidence_quality == ContributionEvidenceQuality.COMPLETE:
        return None
    actual = contribution.actual_monthly_net_contribution
    return DecisionAction(
        id="contribution_evidence_incomplete",
        category=DecisionCategory.DATA,
        priority=DecisionPriority.MEDIUM,
        title="Add contribution evidence",
        explanation=(
            "Plan-versus-actual contribution tracking cannot yet be verified. "
            "BUY lots are not deposits and are not treated as contribution actuals."
        ),
        evidence=(
            contribution.evidence_quality.value,
            contribution.monthly_evidence_quality.value,
        ),
        status=DecisionActionStatus.OPEN,
        limitations=("CONTRIBUTION_EVIDENCE_INCOMPLETE",),
        context={
            "evidence_quality": contribution.evidence_quality.value,
            "actual_monthly_net_contribution": (
                None if actual is None else str(actual)
            ),
            "actual_is_zero": False,
        },
    )


def _rule_goal_plan(
    contribution: ContributionIntelligenceView,
    *,
    fx_missing: bool,
    valuation_complete: bool,
) -> Optional[DecisionAction]:
    status = contribution.plan_adequacy_status
    if fx_missing or not valuation_complete or status == PlanAdequacyStatus.INDETERMINATE:
        return None
    required = contribution.required_starting_monthly_contribution
    planned = contribution.planned_monthly_contribution
    if status == PlanAdequacyStatus.BELOW_REQUIRED:
        return DecisionAction(
            id="contribution_plan_below_required",
            category=DecisionCategory.PLAN,
            priority=DecisionPriority.HIGH,
            title="Current plan appears below required level",
            explanation=(
                "Under the Base 8% planning scenario, the current starting monthly "
                "contribution is below the required starting monthly contribution."
            ),
            evidence=(
                f"planned={planned}",
                f"required={required}",
                status.value,
            ),
            status=DecisionActionStatus.OPEN,
            limitations=(),
            context={
                "planned_monthly": str(planned),
                "required_starting_monthly": None if required is None else str(required),
                "plan_adequacy_status": status.value,
            },
        )
    return None


def _rule_concentration(
    view: PortfolioIntelligenceView,
    *,
    valuation_complete: bool,
) -> Optional[DecisionAction]:
    largest = _largest_priced_holding(view)
    if largest is None:
        return None
    symbol, weight = largest
    if weight < CONCENTRATION_REVIEW_THRESHOLD_PCT:
        return None
    limitations = []
    if not valuation_complete:
        limitations.append("WEIGHTS_USE_PRICED_MV_ONLY")
        limitations.append("PARTIAL_VALUATION")
    return DecisionAction(
        id="concentration_review",
        category=DecisionCategory.PORTFOLIO,
        priority=DecisionPriority.MEDIUM,
        title="Review concentration",
        explanation=(
            f"{symbol} is about {weight:.1f}% of priced base-currency market value, "
            f"at or above the {CONCENTRATION_REVIEW_THRESHOLD_PCT:.0f}% review trigger. "
            "This is a review flag, not a recommendation to sell."
        ),
        evidence=(symbol, f"{weight:.1f}%"),
        status=DecisionActionStatus.OPEN,
        limitations=tuple(limitations),
        context={
            "symbol": symbol,
            "weight_pct": round(weight, 4),
            "threshold_pct": CONCENTRATION_REVIEW_THRESHOLD_PCT,
            "partial_valuation": not valuation_complete,
        },
    )


def _performance_limitation(
    *,
    history: Optional[WealthHistoryView],
    contribution: ContributionIntelligenceView,
) -> Optional[str]:
    quality = contribution.performance_evidence_quality
    if history is not None:
        quality = history.evidence_quality
    if quality == PerformanceEvidenceQuality.COMPLETE:
        return None
    return "PERFORMANCE_EVIDENCE_INCOMPLETE"


def _monitor_fallback() -> DecisionAction:
    return DecisionAction(
        id="continue_observation",
        category=DecisionCategory.MONITOR,
        priority=DecisionPriority.INFO,
        title="Continue observation",
        explanation=(
            "No HIGH or MEDIUM intervention is supported by current evidence. "
            "Continue monitoring the plan and portfolio."
        ),
        evidence=("HEALTHY_FALLBACK",),
        status=DecisionActionStatus.OBSERVE,
    )


def build_portfolio_decision(
    portfolio_view: PortfolioIntelligenceView,
    *,
    as_of_date: Optional[date] = None,
    goal: Optional[WealthGoal] = None,
    plan: Optional[ContributionPlan] = None,
    conversion: Optional[ConversionAssumption] = None,
    transactions: Iterable[Dict[str, Any]] = (),
    account_ids: Sequence[str] = (),
    positions: Optional[Sequence[dict]] = None,
    assets: Optional[Sequence[dict]] = None,
    contribution: Optional[ContributionIntelligenceView] = None,
    history: Optional[WealthHistoryView] = None,
    start_snapshot: Optional[PortfolioSnapshotView] = None,
    end_snapshot: Optional[PortfolioSnapshotView] = None,
    current_wealth: Optional[CurrentWealthSnapshot] = None,
) -> PortfolioDecisionView:
    """Deterministic evidence/action-priority engine. No LLM, providers, or writes."""
    as_of = as_of_date or date.today()
    goal = goal or default_wealth_goal_2031()
    plan = plan or default_contribution_plan()
    goal.validate()
    plan.validate()
    current = current_wealth or current_wealth_from_portfolio_view(
        portfolio_view,
        goal_currency=goal.currency,
        positions=positions,
        assets=assets,
    )
    contrib = contribution or build_contribution_intelligence(
        as_of_date=as_of,
        current=current,
        transactions=transactions,
        account_ids=account_ids,
        plan=plan,
        goal=goal,
        conversion=conversion,
        annual_return_rate=BASE_RETURN_RATE,
        start_snapshot=start_snapshot,
        end_snapshot=end_snapshot,
    )
    fx_missing = _planning_fx_missing(plan, goal, conversion)

    actions: list[DecisionAction] = []
    for builder in (
        lambda: _rule_partial_valuation(current),
        lambda: _rule_planning_fx(plan, goal, conversion),
        lambda: _rule_contribution_evidence(contrib),
        lambda: _rule_goal_plan(
            contrib, fx_missing=fx_missing, valuation_complete=current.valuation_complete
        ),
        lambda: _rule_concentration(
            portfolio_view, valuation_complete=current.valuation_complete
        ),
    ):
        item = builder()
        if item is not None:
            actions.append(item)

    actionable = {
        DecisionPriority.CRITICAL,
        DecisionPriority.HIGH,
        DecisionPriority.MEDIUM,
    }
    if not any(row.priority in actionable for row in actions):
        actions.append(_monitor_fallback())

    ordered = tuple(sorted(actions, key=_sort_key))
    limitations: list[str] = []
    perf_limit = _performance_limitation(history=history, contribution=contrib)
    if perf_limit:
        limitations.append(perf_limit)
    for row in ordered:
        for note in row.limitations:
            if note not in limitations:
                limitations.append(note)
    evidence_complete = (
        current.valuation_complete
        and not fx_missing
        and contrib.evidence_quality == ContributionEvidenceQuality.COMPLETE
    )
    generated_from = (
        "portfolio_intelligence_view",
        "current_wealth_from_portfolio_view",
        "build_contribution_intelligence",
        "solve_required_starting_monthly",
        "CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT",
    )
    return PortfolioDecisionView(
        actions=ordered,
        primary_action=ordered[0],
        evidence_complete=evidence_complete,
        limitations=tuple(limitations),
        generated_from=generated_from,
    )
