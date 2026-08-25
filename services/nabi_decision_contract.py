"""NABI Decision Orchestrator v3 contract. No scoring math."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from services.research_intelligence_contract import ResearchEvidenceRef

DECISION_PRECEDENCE = (
    "PARTICIPATION",
    "EVIDENCE_COMPLETENESS",
    "COMPANY_ATTRACTIVENESS",
    "TIMING",
    "PORTFOLIO_FIT",
    "WEALTH_NEW_MONEY",
    "FINAL_RECOMMENDATION",
)

ACTION_BLOCKED_PARTICIPATION = "BLOCKED_PARTICIPATION"
ACTION_RESEARCH_FIRST = "RESEARCH_FIRST"
ACTION_WATCH = "WATCH"
ACTION_WAIT = "WAIT"
ACTION_CONSIDER_NEW_POSITION = "CONSIDER_NEW_POSITION"
ACTION_CONSIDER_TOP_UP = "CONSIDER_TOP_UP"
ACTION_NO_ACTION = "NO_ACTION"

INVESTMENT_ACTIONS = (
    ACTION_BLOCKED_PARTICIPATION,
    ACTION_RESEARCH_FIRST,
    ACTION_WATCH,
    ACTION_WAIT,
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    ACTION_NO_ACTION,
)

TIMING_FAVORABLE = "FAVORABLE"
TIMING_NEUTRAL = "NEUTRAL"
TIMING_WAIT = "WAIT"
TIMING_UNKNOWN = "UNKNOWN"

REASON_PARTICIPATION_BLOCKED = "PARTICIPATION_BLOCKED"
REASON_EVIDENCE_LOW = "EVIDENCE_LOW"
REASON_EVIDENCE_MEDIUM = "EVIDENCE_MEDIUM"
REASON_ATTRACTIVENESS_WATCH = "ATTRACTIVENESS_WATCH"
REASON_TIMING_WAIT = "TIMING_WAIT"
REASON_TIMING_UNKNOWN = "TIMING_UNKNOWN"
REASON_TIMING_FAVORABLE = "TIMING_FAVORABLE"
REASON_TIMING_NEUTRAL = "TIMING_NEUTRAL"
REASON_FIT_POOR = "FIT_POOR"
REASON_NO_DEPLOYMENT_SUPPORT = "NO_DEPLOYMENT_SUPPORT"
REASON_DEPLOY_NEW = "DEPLOY_NEW"
REASON_DEPLOY_TOP_UP = "DEPLOY_TOP_UP"
REASON_EXTERNAL_SIGNAL_NOT_AUTHORITY = "EXTERNAL_SIGNAL_NOT_AUTHORITY"
REASON_WEALTH_PRIORITY = "WEALTH_PRIORITY"

FIT_PRESENTATION = {
    "GOOD_FIT": "GOOD",
    "NEUTRAL_FIT": "NEUTRAL",
    "POOR_FIT": "POOR",
    "UNKNOWN": "UNKNOWN",
}


@dataclass(frozen=True)
class CandidateInvestmentDecision:
    symbol: str
    final_action: str
    participation_status: str
    research_completeness: str
    decision_class: str
    nabi_score: Optional[float]
    timing_state: str
    portfolio_fit: str
    reason_codes: Tuple[str, ...]
    evidence_references: Tuple[ResearchEvidenceRef, ...]
    why: str
    investable_research: bool


@dataclass(frozen=True)
class DecisionAuditRecord:
    recommendation_id: str
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
    persisted: bool = False
    logical_event_id: str = ""

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
            "persisted": self.persisted,
        }


@dataclass(frozen=True)
class NabiDecisionV3:
    decision_precedence: Tuple[str, ...]
    opportunity_ranking: Tuple[str, ...]
    opportunity_leader: Optional[str]
    deployment_symbol: Optional[str]
    final_action: str
    wealth_action: str
    dashboard_primary: str
    timing_state: str
    portfolio_fit: str
    why: str
    candidate_decisions: Tuple[CandidateInvestmentDecision, ...]
    audit: DecisionAuditRecord
    persisted: bool = False


@dataclass(frozen=True)
class DecisionV3Brief:
    final_action: str
    timing_state: str
    portfolio_fit: str
    why: str
    symbol: Optional[str]
