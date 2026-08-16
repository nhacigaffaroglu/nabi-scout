from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple


MONITOR_EVENT_STATUSES = frozenset({"new", "reviewed", "dismissed", "resolved"})
MONITOR_MATERIALITY_LEVELS = frozenset({"info", "low", "medium", "high", "critical"})
MONITOR_SEVERITIES = frozenset({"info", "watch", "high", "critical"})

MONITOR_CATEGORIES = frozenset({
    "portfolio",
    "research",
    "financial",
    "filing",
    "thesis",
    "participation",
    "wealth",
})

# Portfolio events
EVENT_POSITION_OPENED = "POSITION_OPENED"
EVENT_POSITION_CLOSED = "POSITION_CLOSED"
EVENT_POSITION_INCREASED = "POSITION_INCREASED"
EVENT_POSITION_REDUCED = "POSITION_REDUCED"
EVENT_PORTFOLIO_WEIGHT_CHANGED = "PORTFOLIO_WEIGHT_CHANGED"
EVENT_CONCENTRATION_CHANGED = "CONCENTRATION_CHANGED"
EVENT_PORTFOLIO_VALUE_CHANGED = "PORTFOLIO_VALUE_CHANGED"
EVENT_RESEARCH_COVERAGE_CHANGED = "RESEARCH_COVERAGE_CHANGED"
EVENT_SECTOR_ALLOCATION_CHANGED = "SECTOR_ALLOCATION_CHANGED"

# Research / participation / thesis
EVENT_NEW_RESEARCH_AVAILABLE = "NEW_RESEARCH_AVAILABLE"
EVENT_RESEARCH_STATUS_CHANGED = "RESEARCH_STATUS_CHANGED"
EVENT_PARTICIPATION_STATUS_CHANGED = "PARTICIPATION_STATUS_CHANGED"
EVENT_PARTICIPATION_REVIEW_REQUIRED = "PARTICIPATION_REVIEW_REQUIRED"
EVENT_THESIS_STATUS_CHANGED = "THESIS_STATUS_CHANGED"
EVENT_THESIS_CONFIDENCE_CHANGED = "THESIS_CONFIDENCE_CHANGED"
EVENT_THESIS_EVIDENCE_CHANGED = "THESIS_EVIDENCE_CHANGED"
EVENT_POSSIBLE_INVALIDATION_SIGNAL = "POSSIBLE_INVALIDATION_SIGNAL"
EVENT_RESEARCH_BECAME_STALE = "RESEARCH_BECAME_STALE"

# Wealth
EVENT_GOAL_PROGRESS_CHANGED = "GOAL_PROGRESS_CHANGED"
EVENT_INCOME_RECEIVED = "INCOME_RECEIVED"

# Wave 3 construction / decision events
EVENT_REFERENCE_LIMIT_BREACHED = "REFERENCE_LIMIT_BREACHED"
EVENT_CONCENTRATION_THRESHOLD_CROSSED = "CONCENTRATION_THRESHOLD_CROSSED"
EVENT_DECISION_EVIDENCE_GAP = "DECISION_EVIDENCE_GAP"
EVENT_DECISION_OUTCOME_UPDATED = "DECISION_OUTCOME_UPDATED"


@dataclass(frozen=True)
class MonitorEventDraft:
    user_id: Optional[str]
    portfolio_id: Optional[str]
    symbol: Optional[str]
    event_type: str
    event_category: str
    severity: str
    materiality: str
    occurred_at: str
    dedupe_key: str
    title: str
    summary: str
    evidence_type: Optional[str] = None
    evidence_reference: Optional[str] = None
    previous_value: Optional[str] = None
    current_value: Optional[str] = None
    absolute_change: Optional[float] = None
    percentage_change: Optional[float] = None
    event_payload: Dict[str, Any] = field(default_factory=dict)
    notification_eligible: bool = False
    notification_reason: Optional[str] = None


@dataclass(frozen=True)
class PortfolioImpactView:
    held: bool
    total_quantity: Optional[float]
    portfolio_weight: Optional[float]
    account_count: int
    account_breakdown: Tuple[Dict[str, Any], ...]
    concentration_rank: Optional[int]
    participation_status: Optional[str]
    research_coverage: Optional[str]
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ThesisRelevanceView:
    relevance: str
    thesis_status: Optional[str]
    thesis_confidence: Optional[str]
    invalidation_match: bool
    explanation: str
    journal_entry_count: int = 0
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MonitorEventView:
    event_id: str
    user_id: Optional[str]
    portfolio_id: Optional[str]
    symbol: Optional[str]
    event_type: str
    event_category: str
    severity: str
    materiality: str
    occurred_at: str
    detected_at: str
    title: str
    summary: str
    evidence_type: Optional[str]
    evidence_reference: Optional[str]
    previous_value: Optional[str]
    current_value: Optional[str]
    absolute_change: Optional[float]
    percentage_change: Optional[float]
    event_payload: Dict[str, Any]
    notification_eligible: bool
    notification_reason: Optional[str]
    review_status: str
    portfolio_impact: Optional[PortfolioImpactView]
    thesis_relevance: Optional[ThesisRelevanceView]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.portfolio_impact is not None:
            payload["portfolio_impact"] = asdict(self.portfolio_impact)
        if self.thesis_relevance is not None:
            payload["thesis_relevance"] = asdict(self.thesis_relevance)
        return payload


@dataclass(frozen=True)
class DailyPortfolioBriefContext:
    brief_date: str
    portfolio_id: str
    portfolio_name: str
    event_counts: Dict[str, int]
    highest_priority_events: Tuple[MonitorEventView, ...]
    portfolio_affected_events: Tuple[MonitorEventView, ...]
    thesis_relevant_events: Tuple[MonitorEventView, ...]
    participation_events: Tuple[MonitorEventView, ...]
    research_events: Tuple[MonitorEventView, ...]
    unresolved_attention: Tuple[str, ...]
    data_quality: Dict[str, Any]
    source_freshness: Dict[str, Any]
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "brief_date": self.brief_date,
            "portfolio_id": self.portfolio_id,
            "portfolio_name": self.portfolio_name,
            "event_counts": dict(self.event_counts),
            "highest_priority_events": [event.to_dict() for event in self.highest_priority_events],
            "portfolio_affected_events": [
                event.to_dict() for event in self.portfolio_affected_events
            ],
            "thesis_relevant_events": [event.to_dict() for event in self.thesis_relevant_events],
            "participation_events": [event.to_dict() for event in self.participation_events],
            "research_events": [event.to_dict() for event in self.research_events],
            "unresolved_attention": list(self.unresolved_attention),
            "data_quality": dict(self.data_quality),
            "source_freshness": dict(self.source_freshness),
            "limitations": list(self.limitations),
        }
