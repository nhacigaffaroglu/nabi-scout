"""Compact Research Intelligence contract. No scoring math."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

RESEARCH_STATE_BLOCKED = "BLOCKED"
RESEARCH_STATE_NOT_APPLICABLE = "NOT_APPLICABLE"
RESEARCH_STATE_INSUFFICIENT = "INSUFFICIENT"
RESEARCH_STATE_WATCH = "WATCH"
RESEARCH_STATE_READY = "READY"

VALUATION_ATTRACTIVE = "ATTRACTIVE"
VALUATION_FAIR = "FAIR"
VALUATION_EXPENSIVE = "EXPENSIVE"
VALUATION_UNKNOWN = "UNKNOWN"

COMPLETENESS_HIGH = "HIGH"
COMPLETENESS_MEDIUM = "MEDIUM"
COMPLETENESS_LOW = "LOW"

UNKNOWN = "UNKNOWN"
INSUFFICIENT = "INSUFFICIENT"

MAX_POINTS = 3

THESIS_VALUATION_MAP = {
    "VALUATION_SUPPORTIVE": VALUATION_ATTRACTIVE,
    "VALUATION_NEUTRAL": VALUATION_FAIR,
    "VALUATION_DEMANDING": VALUATION_EXPENSIVE,
    "VALUATION_UNAVAILABLE": VALUATION_UNKNOWN,
}

CONFIDENCE_LEVEL_MAP = {
    "HIGH": COMPLETENESS_HIGH,
    "MEDIUM": COMPLETENESS_MEDIUM,
    "LOW": COMPLETENESS_LOW,
    "YÜKSEK": COMPLETENESS_HIGH,
    "ORTA": COMPLETENESS_MEDIUM,
    "DÜŞÜK": COMPLETENESS_LOW,
}


@dataclass(frozen=True)
class ResearchEvidenceRef:
    source_type: str
    source_reference: str
    observed_at: Optional[str]
    evidence_type: str
    statement: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_reference": self.source_reference,
            "observed_at": self.observed_at,
            "evidence_type": self.evidence_type,
            "statement": self.statement,
        }


@dataclass(frozen=True)
class ResearchIntelligence:
    symbol: str
    research_state: str
    thesis_points: Tuple[str, ...]
    risk_points: Tuple[str, ...]
    catalyst_points: Tuple[str, ...]
    valuation_context: str
    quality_context: str
    why_now: Tuple[str, ...]
    why_not_now: Tuple[str, ...]
    research_completeness: str
    missing_evidence: Tuple[str, ...]
    evidence_references: Tuple[ResearchEvidenceRef, ...]
    generated_at: str
    persisted: bool
    investable: bool
    valuation_classification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "research_state": self.research_state,
            "thesis_points": list(self.thesis_points),
            "risk_points": list(self.risk_points),
            "catalyst_points": list(self.catalyst_points),
            "valuation_context": self.valuation_context,
            "quality_context": self.quality_context,
            "why_now": list(self.why_now),
            "why_not_now": list(self.why_not_now),
            "research_completeness": self.research_completeness,
            "missing_evidence": list(self.missing_evidence),
            "evidence_references": [item.to_dict() for item in self.evidence_references],
            "generated_at": self.generated_at,
            "persisted": self.persisted,
            "investable": self.investable,
            "valuation_classification": self.valuation_classification,
        }


@dataclass(frozen=True)
class ResearchIntelligenceBrief:
    interesting: Optional[str]
    risks: Optional[str]
    catalysts: Optional[str]
    valuation: Optional[str]
    timing: Optional[str]
