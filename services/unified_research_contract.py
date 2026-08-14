from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

UNIFIED_RESEARCH_SCHEMA_VERSION = "unified-research-v1"

PORTFOLIO_FIT_CODES = (
    "COMPANY_THESIS_STRONG_PORTFOLIO_CONCENTRATED",
    "THESIS_MIXED_HIGH_EXPOSURE",
    "THESIS_WEAKENING_HIGH_EXPOSURE",
    "THESIS_SUPPORTED_LOW_EXPOSURE",
    "DATA_GAP_PORTFOLIO_FIT",
    "NOT_HELD",
    "NEUTRAL_FIT",
)


@dataclass(frozen=True)
class WealthExposureContext:
    symbol: str
    held: bool
    quantity: Optional[float]
    market_value: Optional[float]
    portfolio_weight_pct: Optional[float]
    cost_basis: Optional[float]
    unrealized_pl: Optional[float]
    account_names: Tuple[str, ...]
    concentration_context: Optional[str]
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "held": self.held,
            "quantity": self.quantity,
            "market_value": self.market_value,
            "portfolio_weight_pct": self.portfolio_weight_pct,
            "cost_basis": self.cost_basis,
            "unrealized_pl": self.unrealized_pl,
            "account_names": list(self.account_names),
            "concentration_context": self.concentration_context,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class PortfolioCompanyFitAssessment:
    code: str
    statement: str
    confidence: str
    evidence: Tuple[Tuple[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "statement": self.statement,
            "confidence": self.confidence,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class NabiResearchContext:
    decision: Optional[str]
    nabi_score: Optional[float]
    research_status: Optional[str]
    decision_label: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "nabi_score": self.nabi_score,
            "research_status": self.research_status,
            "decision_label": self.decision_label,
        }


@dataclass(frozen=True)
class ParticipationResearchContext:
    status: Optional[str]
    confidence: Optional[str]
    assessed_at: Optional[str]
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "assessed_at": self.assessed_at,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class MonitoringPlanItem:
    item_id: str
    source: str
    metric_or_event: str
    why_it_matters: str
    current_state: str
    next_known_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source": self.source,
            "metric_or_event": self.metric_or_event,
            "why_it_matters": self.why_it_matters,
            "current_state": self.current_state,
            "next_known_date": self.next_known_date,
        }


@dataclass(frozen=True)
class UnifiedResearchContext:
    symbol: str
    company_name: Optional[str]
    schema_version: str
    generated_at: str
    company_intelligence: Optional[Dict[str, Any]]
    investment_thesis: Optional[Dict[str, Any]]
    nabi_context: Optional[NabiResearchContext]
    participation_context: Optional[ParticipationResearchContext]
    wealth_exposure_context: Optional[WealthExposureContext]
    portfolio_fit: Tuple[PortfolioCompanyFitAssessment, ...] = ()
    investor_profile: Dict[str, Any] = field(default_factory=dict)
    active_goals: Tuple[Dict[str, Any], ...] = ()
    monitoring_plan: Tuple[MonitoringPlanItem, ...] = ()
    thesis_change_summary: Tuple[Dict[str, Any], ...] = ()
    data_quality: Dict[str, Any] = field(default_factory=dict)
    provenance: Tuple[Tuple[str, str], ...] = ()
    focus_symbol: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "company_intelligence": self.company_intelligence,
            "investment_thesis": self.investment_thesis,
            "nabi_context": self.nabi_context.to_dict() if self.nabi_context else None,
            "participation_context": (
                self.participation_context.to_dict() if self.participation_context else None
            ),
            "wealth_exposure_context": (
                self.wealth_exposure_context.to_dict() if self.wealth_exposure_context else None
            ),
            "portfolio_fit": [item.to_dict() for item in self.portfolio_fit],
            "investor_profile": dict(self.investor_profile),
            "active_goals": list(self.active_goals),
            "monitoring_plan": [item.to_dict() for item in self.monitoring_plan],
            "thesis_change_summary": list(self.thesis_change_summary),
            "data_quality": dict(self.data_quality),
            "provenance": dict(self.provenance),
            "focus_symbol": self.focus_symbol,
        }
