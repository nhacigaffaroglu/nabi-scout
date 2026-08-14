from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from services.company_intelligence_utils import serialize_optional

THESIS_VERSION = "investment-thesis-v2"
THESIS_STATUSES = ("SUPPORTED", "MIXED", "WEAKENING", "INSUFFICIENT_DATA")
EVIDENCE_POLARITIES = ("SUPPORTS", "WEAKENS", "NEUTRAL", "UNKNOWN")
EVIDENCE_CATEGORIES = (
    "BUSINESS",
    "GROWTH",
    "PROFITABILITY",
    "CASH_FLOW",
    "BALANCE_SHEET",
    "VALUATION",
    "EARNINGS",
    "PEERS",
    "NEWS",
    "CATALYST",
    "RISK",
    "PARTICIPATION",
    "NABI_CONTEXT",
    "DATA_QUALITY",
)
CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")
EVIDENCE_BALANCE = (
    "SUPPORT_DOMINANT",
    "BALANCED",
    "WEAKNESS_DOMINANT",
    "INSUFFICIENT_DATA",
)
VALUATION_CONTEXT = (
    "VALUATION_SUPPORTIVE",
    "VALUATION_NEUTRAL",
    "VALUATION_DEMANDING",
    "VALUATION_UNAVAILABLE",
)
EARNINGS_CONTEXT = (
    "EARNINGS_SUPPORT",
    "EARNINGS_MIXED",
    "EARNINGS_WEAKENING",
    "EARNINGS_UNAVAILABLE",
)


@dataclass(frozen=True)
class ThesisEvidence:
    evidence_id: str
    code: str
    category: str
    polarity: str
    materiality: str
    statement: str
    evidence: Tuple[Tuple[str, Any], ...]
    source: str
    confidence: str
    as_of: Optional[str]
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "code": self.code,
            "category": self.category,
            "polarity": self.polarity,
            "materiality": self.materiality,
            "statement": self.statement,
            "evidence": dict(self.evidence),
            "source": self.source,
            "confidence": self.confidence,
            "as_of": self.as_of,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class ExpectationTension:
    code: str
    statement: str
    status: str
    confidence: str
    evidence: Tuple[Tuple[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "statement": self.statement,
            "status": self.status,
            "confidence": self.confidence,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class ThesisRisk:
    risk_id: str
    code: str
    category: str
    severity: str
    statement: str
    evidence: Tuple[Tuple[str, Any], ...]
    likelihood: str
    impact: str
    monitoring_metric: Optional[str]
    source: str
    confidence: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_id": self.risk_id,
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "statement": self.statement,
            "evidence": dict(self.evidence),
            "likelihood": self.likelihood,
            "impact": self.impact,
            "monitoring_metric": self.monitoring_metric,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ThesisCatalyst:
    catalyst_id: str
    catalyst_type: str
    description: str
    expected_date: Optional[str]
    status: str
    source: str
    confidence: str
    thesis_relevance: str
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "catalyst_id": self.catalyst_id,
            "catalyst_type": self.catalyst_type,
            "description": self.description,
            "expected_date": self.expected_date,
            "status": self.status,
            "source": self.source,
            "confidence": self.confidence,
            "thesis_relevance": self.thesis_relevance,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class InvalidationCondition:
    condition_id: str
    code: str
    statement: str
    linked_evidence_ids: Tuple[str, ...]
    monitoring_metric: Optional[str]
    source: str
    confidence: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "code": self.code,
            "statement": self.statement,
            "linked_evidence_ids": list(self.linked_evidence_ids),
            "monitoring_metric": self.monitoring_metric,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ThesisAssumption:
    assumption_id: str
    statement: str
    basis: str
    confidence: str
    required_evidence: Tuple[str, ...]
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "statement": self.statement,
            "basis": self.basis,
            "confidence": self.confidence,
            "required_evidence": list(self.required_evidence),
            "status": self.status,
        }


@dataclass(frozen=True)
class MonitoringItem:
    item_id: str
    metric_or_event: str
    why_it_matters: str
    current_state: str
    invalidation_link: Optional[str]
    next_known_date: Optional[str]
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "metric_or_event": self.metric_or_event,
            "why_it_matters": self.why_it_matters,
            "current_state": self.current_state,
            "invalidation_link": self.invalidation_link,
            "next_known_date": self.next_known_date,
            "source": self.source,
        }


@dataclass(frozen=True)
class ThesisChangeItem:
    code: str
    statement: str
    evidence: Tuple[Tuple[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "statement": self.statement,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class EvidenceCoverage:
    financials: str
    earnings: str
    valuation: str
    peers: str
    news: str
    participation: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "financials": self.financials,
            "earnings": self.earnings,
            "valuation": self.valuation,
            "peers": self.peers,
            "news": self.news,
            "participation": self.participation,
        }


@dataclass(frozen=True)
class DecisionIntelligenceView:
    thesis_status: str
    evidence_balance: str
    key_question: str
    strongest_support: Optional[str]
    strongest_weakness: Optional[str]
    primary_risk: Optional[str]
    primary_catalyst: Optional[str]
    valuation_tension: Optional[str]
    invalidation_watch: Optional[str]
    data_quality: str
    nabi_decision_context: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thesis_status": self.thesis_status,
            "evidence_balance": self.evidence_balance,
            "key_question": self.key_question,
            "strongest_support": self.strongest_support,
            "strongest_weakness": self.strongest_weakness,
            "primary_risk": self.primary_risk,
            "primary_catalyst": self.primary_catalyst,
            "valuation_tension": self.valuation_tension,
            "invalidation_watch": self.invalidation_watch,
            "data_quality": self.data_quality,
            "nabi_decision_context": self.nabi_decision_context,
        }


@dataclass(frozen=True)
class InvestmentThesisView:
    symbol: str
    company_name: Optional[str]
    as_of: Optional[str]
    thesis_version: str
    thesis_status: str
    thesis_summary: str
    key_question: str
    supporting_evidence: Tuple[ThesisEvidence, ...]
    weakening_evidence: Tuple[ThesisEvidence, ...]
    risks: Tuple[ThesisRisk, ...]
    catalysts: Tuple[ThesisCatalyst, ...]
    invalidation_conditions: Tuple[InvalidationCondition, ...]
    assumptions: Tuple[ThesisAssumption, ...]
    valuation_context: str
    earnings_context: str
    peer_context: Optional[str]
    news_context: Optional[str]
    expectation_tensions: Tuple[ExpectationTension, ...] = ()
    participation_context: Optional[str] = None
    nabi_context: Optional[str] = None
    confidence: str = "LOW"
    evidence_coverage: Optional[EvidenceCoverage] = None
    change_summary: Tuple[ThesisChangeItem, ...] = ()
    monitoring_plan: Tuple[MonitoringItem, ...] = ()
    decision_intelligence: Optional[DecisionIntelligenceView] = None
    data_quality_notes: Tuple[str, ...] = ()
    provenance: Tuple[Tuple[str, str], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        payload = serialize_optional(
            {
                "symbol": self.symbol,
                "company_name": self.company_name,
                "as_of": self.as_of,
                "thesis_version": self.thesis_version,
                "thesis_status": self.thesis_status,
                "thesis_summary": self.thesis_summary,
                "key_question": self.key_question,
                "supporting_evidence": self.supporting_evidence,
                "weakening_evidence": self.weakening_evidence,
                "risks": self.risks,
                "catalysts": self.catalysts,
                "invalidation_conditions": self.invalidation_conditions,
                "assumptions": self.assumptions,
                "valuation_context": self.valuation_context,
                "earnings_context": self.earnings_context,
                "peer_context": self.peer_context,
                "news_context": self.news_context,
                "expectation_tensions": self.expectation_tensions,
                "participation_context": self.participation_context,
                "nabi_context": self.nabi_context,
                "confidence": self.confidence,
                "evidence_coverage": self.evidence_coverage,
                "change_summary": self.change_summary,
                "monitoring_plan": self.monitoring_plan,
                "decision_intelligence": self.decision_intelligence,
                "data_quality_notes": self.data_quality_notes,
                "provenance": dict(self.provenance),
            }
        )
        return payload
