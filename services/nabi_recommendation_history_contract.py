"""Recommendation history / outcome contract. Observational only. No scoring."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple

from services.nabi_decision_contract import (
    ACTION_BLOCKED_PARTICIPATION,
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    ACTION_NO_ACTION,
    ACTION_RESEARCH_FIRST,
    ACTION_WAIT,
    ACTION_WATCH,
    DecisionAuditRecord,
)

AUTO_POLICY_LEARNING = False
POLICY_LEARNING_STATE = "DISABLED"

OUTCOME_WINDOWS = ("7D", "30D", "90D", "365D")
WINDOW_DAYS = {"7D": 7, "30D": 30, "90D": 90, "365D": 365}

OUTCOME_POSITIVE = "POSITIVE"
OUTCOME_NEGATIVE = "NEGATIVE"
OUTCOME_FLAT = "FLAT"
OUTCOME_UNKNOWN = "UNKNOWN"

INTERPRET_INVESTMENT_MEASURED = "INVESTMENT_MEASURED"
INTERPRET_NON_DEPLOYMENT = "NON_DEPLOYMENT_OBSERVATION"
INTERPRET_OBSERVATION_ONLY = "OBSERVATION_ONLY"
INTERPRET_NOT_INVESTMENT = "NOT_INVESTMENT_EVALUATED"

ACTION_INTERPRETATION = {
    ACTION_CONSIDER_NEW_POSITION: INTERPRET_INVESTMENT_MEASURED,
    ACTION_CONSIDER_TOP_UP: INTERPRET_INVESTMENT_MEASURED,
    ACTION_WAIT: INTERPRET_NON_DEPLOYMENT,
    ACTION_WATCH: INTERPRET_NON_DEPLOYMENT,
    ACTION_RESEARCH_FIRST: INTERPRET_OBSERVATION_ONLY,
    ACTION_BLOCKED_PARTICIPATION: INTERPRET_NOT_INVESTMENT,
    ACTION_NO_ACTION: INTERPRET_OBSERVATION_ONLY,
}

PROTECTED_POLICY_DOMAINS = (
    "participation_criteria",
    "religious_rules",
    "safe_zero",
    "npr",
    "nabi_score_weights",
    "valuation_thresholds",
    "opportunity_thresholds",
    "portfolio_concentration_threshold",
    "goal_assumptions",
    "new_money_allocation_rules",
    "timing_rules",
)

SMALL_SAMPLE_THRESHOLD = 5
OBSERVATION_NOT_CAUSAL = (
    "Historical observations only. This does not prove causality and does not change policy."
)


def logical_event_identity(
    *,
    symbol: Optional[str],
    final_action: str,
    participation_status: Optional[str],
    research_completeness: Optional[str],
    decision_class: Optional[str],
    nabi_score: Optional[float],
    timing_state: Optional[str],
    portfolio_fit: Optional[str],
    wealth_action: str,
    reason_codes: Sequence[str],
) -> str:
    score = "" if nabi_score is None else f"{float(nabi_score):.4f}"
    payload = "|".join(
        (
            str(symbol or "").strip().upper(),
            str(final_action or "").strip(),
            str(participation_status or "").strip(),
            str(research_completeness or "").strip(),
            str(decision_class or "").strip(),
            score,
            str(timing_state or "").strip(),
            str(portfolio_fit or "").strip(),
            str(wealth_action or "").strip(),
            ",".join(str(code).strip() for code in reason_codes if str(code).strip()),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def logical_event_identity_from_audit(audit: DecisionAuditRecord) -> str:
    return logical_event_identity(
        symbol=audit.symbol,
        final_action=audit.final_action,
        participation_status=audit.participation_status,
        research_completeness=audit.research_completeness,
        decision_class=audit.decision_class,
        nabi_score=audit.nabi_score,
        timing_state=audit.timing_state,
        portfolio_fit=audit.portfolio_fit,
        wealth_action=audit.wealth_action,
        reason_codes=audit.reason_codes,
    )


def apply_outcome_to_policy(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("AUTO_POLICY_LEARNING is DISABLED")


@dataclass(frozen=True)
class RecommendationHistoryRecord:
    recommendation_id: str
    logical_event_id: str
    generated_at: str
    symbol: Optional[str]
    final_action: str
    participation_status: Optional[str]
    research_completeness: Optional[str]
    decision_class: Optional[str]
    nabi_score: Optional[float]
    timing_state: Optional[str]
    portfolio_fit: Optional[str]
    wealth_action: str
    reason_codes: Tuple[str, ...]
    evidence_references: Tuple[Any, ...]
    why: Optional[str] = None
    portfolio_snapshot_reference: Optional[str] = None
    participation_snapshot_reference: Optional[str] = None
    research_reference: Optional[str] = None
    evaluation_reference: Optional[str] = None
    price_at_recommendation: Optional[float] = None
    price_currency: Optional[str] = None
    persisted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "logical_event_id": self.logical_event_id,
            "generated_at": self.generated_at,
            "symbol": self.symbol,
            "final_action": self.final_action,
            "participation_status": self.participation_status,
            "research_completeness": self.research_completeness,
            "decision_class": self.decision_class,
            "nabi_score": self.nabi_score,
            "timing_state": self.timing_state,
            "portfolio_fit": self.portfolio_fit,
            "wealth_action": self.wealth_action,
            "reason_codes": list(self.reason_codes),
            "evidence_references": [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in self.evidence_references
            ],
            "why": self.why,
            "portfolio_snapshot_reference": self.portfolio_snapshot_reference,
            "participation_snapshot_reference": self.participation_snapshot_reference,
            "research_reference": self.research_reference,
            "evaluation_reference": self.evaluation_reference,
            "price_at_recommendation": self.price_at_recommendation,
            "price_currency": self.price_currency,
            "persisted": self.persisted,
        }


@dataclass(frozen=True)
class OutcomeObservation:
    recommendation_id: str
    symbol: Optional[str]
    window: str
    recommendation_date: str
    observation_date: str
    entry_price: Optional[float]
    observation_price: Optional[float]
    price_currency: Optional[str]
    return_pct: Optional[float]
    outcome_state: str
    source_reference: Optional[str]
    interpretation: str
    mature: bool
    action: str


@dataclass(frozen=True)
class PerformanceBucket:
    action: Optional[str]
    window: Optional[str]
    research_completeness: Optional[str]
    timing_state: Optional[str]
    portfolio_fit: Optional[str]
    decision_class: Optional[str]
    count: int
    observed_count: int
    unknown_count: int
    average_return: Optional[float]
    median_return: Optional[float]
    positive_count: int
    negative_count: int
    small_sample: bool
    investment_evaluated: bool


@dataclass(frozen=True)
class PerformanceSummary:
    buckets: Tuple[PerformanceBucket, ...]
    limitation: str = OBSERVATION_NOT_CAUSAL
    auto_policy_learning: str = POLICY_LEARNING_STATE
