from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, Optional, Tuple

from services.participation_intelligence_contract import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
)

BUSINESS_SCREEN_OUTCOME_PASS = RULE_OUTCOME_PASS
BUSINESS_SCREEN_OUTCOME_FAIL = RULE_OUTCOME_FAIL
BUSINESS_SCREEN_OUTCOME_REVIEW_REQUIRED = RULE_OUTCOME_REVIEW_REQUIRED
BUSINESS_SCREEN_OUTCOME_INSUFFICIENT_DATA = RULE_OUTCOME_INSUFFICIENT_DATA

EVIDENCE_COMPLETENESS_NONE = "none"
EVIDENCE_COMPLETENESS_PARTIAL = "partial"
EVIDENCE_COMPLETENESS_COMPLETE = "complete"

EVIDENCE_TYPE_STRUCTURED_SECTOR = "structured_sector"
EVIDENCE_TYPE_STRUCTURED_INDUSTRY = "structured_industry"
EVIDENCE_TYPE_SIC = "sic"
EVIDENCE_TYPE_REVENUE_SEGMENT = "revenue_segment"
EVIDENCE_TYPE_DESCRIPTION_KEYWORD = "description_keyword"
EVIDENCE_TYPE_MANUAL = "manual"


@dataclass(frozen=True)
class BusinessRevenueEvidence:
    category: str
    segment_name: str
    revenue_value: Optional[float] = None
    revenue_pct: Optional[float] = None
    source: str = ""
    source_date: Optional[date] = None
    confidence: str = CONFIDENCE_LOW

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.source_date is not None:
            payload["source_date"] = self.source_date.isoformat()
        return payload


@dataclass(frozen=True)
class BusinessActivityEvidence:
    symbol: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    sic_code: Optional[str] = None
    sic_description: Optional[str] = None
    business_description: Optional[str] = None
    revenue_segments: Tuple[BusinessRevenueEvidence, ...] = field(default_factory=tuple)
    source: str = ""
    source_date: Optional[date] = None
    evidence_refs: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "sector": self.sector,
            "industry": self.industry,
            "sic_code": self.sic_code,
            "sic_description": self.sic_description,
            "business_description": self.business_description,
            "revenue_segments": [segment.to_dict() for segment in self.revenue_segments],
            "source": self.source,
            "evidence_refs": dict(self.evidence_refs),
            "warnings": list(self.warnings),
        }
        if self.source_date is not None:
            payload["source_date"] = self.source_date.isoformat()
        return payload


@dataclass(frozen=True)
class BusinessActivityRuleResult:
    rule_id: str
    category: str
    outcome: str = RULE_OUTCOME_INSUFFICIENT_DATA
    evidence_type: str = ""
    matched_values: Tuple[str, ...] = field(default_factory=tuple)
    source_refs: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    confidence: str = CONFIDENCE_LOW
    threshold_pct: Optional[float] = None
    comparator: Optional[str] = None
    ratio_pct: Optional[float] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["source_refs"] = dict(self.source_refs)
        return payload


@dataclass(frozen=True)
class BusinessActivityScreenResult:
    symbol: str
    methodology_id: str
    methodology_version: str
    rule_results: Tuple[BusinessActivityRuleResult, ...]
    overall_outcome: str
    evidence_completeness: str = EVIDENCE_COMPLETENESS_NONE
    business_rules_evaluated: bool = False
    methodology_complete: bool = False
    as_of_date: Optional[date] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "methodology_id": self.methodology_id,
            "methodology_version": self.methodology_version,
            "rule_results": [rule.to_dict() for rule in self.rule_results],
            "overall_outcome": self.overall_outcome,
            "evidence_completeness": self.evidence_completeness,
            "business_rules_evaluated": self.business_rules_evaluated,
            "methodology_complete": self.methodology_complete,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "warnings": list(self.warnings),
        }
