from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

DECISION_TYPES = frozenset({
    "initiated_position",
    "increased_position",
    "reduced_position",
    "closed_position",
    "held",
    "transferred",
    "reviewed_without_trade",
})

OUTCOME_STATUS_COMPLETE = "COMPLETE"
OUTCOME_STATUS_PARTIAL = "PARTIAL"
OUTCOME_STATUS_UNAVAILABLE = "UNAVAILABLE"
OUTCOME_STATUS_UNRESOLVED = "UNRESOLVED"

ACTION_TO_DECISION_TYPE = {
    "added": "initiated_position",
    "increased": "increased_position",
    "reduced": "reduced_position",
    "exited": "closed_position",
    "reviewed": "reviewed_without_trade",
    "considering": "held",
}


@dataclass(frozen=True)
class DecisionOutcome:
    journal_id: str
    symbol: str
    decision_date: str
    decision_type: str
    action_context: str
    account_id: Optional[str]
    quantity_at_decision: Optional[float]
    exposure_value_at_decision: Optional[float]
    decision_price: Optional[float]
    current_price: Optional[float]
    current_value: Optional[float]
    holding_period_days: Optional[int]
    absolute_outcome: Optional[float]
    percentage_outcome: Optional[float]
    dividend_income: Optional[float]
    fees_attributable: Optional[float]
    participation_status_at_decision: Optional[str]
    thesis_at_decision: Optional[str]
    invalidation_conditions_at_decision: Optional[str]
    research_reference: Optional[str]
    confidence_at_decision: Optional[str]
    outcome_status: str
    evidence_completeness: str
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionScorecard:
    total_evaluated: int
    positive_outcomes: int
    negative_outcomes: int
    neutral_outcomes: int
    unresolved_decisions: int
    evidence_complete_count: int
    evidence_complete_pct: Optional[float]
    average_outcome_pct: Optional[float]
    median_outcome_pct: Optional[float]
    thesis_aligned_count: int
    with_invalidation_conditions: int
    without_journal_rationale: int
    kontrol_et_decisions: int
    limited_research_decisions: int
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionLearningInsight:
    insight_type: str
    evidence_count: int
    severity: str
    description: str
    supporting_decision_ids: Tuple[str, ...]
    evidence_completeness: str
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
