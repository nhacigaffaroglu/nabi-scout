from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

ADVISER_SCHEMA_VERSION = "wealth-adviser-v1"

PROHIBITED_CLAIMS: Tuple[str, ...] = (
    "Do not claim fiduciary status.",
    "Do not claim certainty about future returns.",
    "Do not invent missing financial data.",
    "Do not override deterministic calculations.",
    "Do not treat missing prices as zero.",
    "Do not present NABI metadata as portfolio valuation evidence.",
    "Do not call Modified Dietz TWR.",
    "Do not call partial base-currency valuation total net worth.",
    "Do not fabricate benchmark comparisons.",
    "Do not issue transaction instructions unless a later explicitly designed adviser policy allows them.",
)


@dataclass(frozen=True)
class AdviserFinding:
    finding_id: str
    diagnostic_code: str
    category: str
    severity: str
    confidence: str
    title: str
    statement: str
    evidence: Dict[str, Any]
    affected_symbols: Tuple[str, ...]
    source: str
    priority_score: int
    actionable: bool
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "diagnostic_code": self.diagnostic_code,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "title": self.title,
            "statement": self.statement,
            "evidence": dict(self.evidence),
            "affected_symbols": list(self.affected_symbols),
            "source": self.source,
            "priority_score": self.priority_score,
            "actionable": self.actionable,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class AdviserPortfolioFacts:
    portfolio_id: str
    portfolio_name: str
    base_currency: str
    priced_market_value: float
    total_cost_basis: float
    unrealized_pl: float
    cash_pct: float
    invested_pct: float
    largest_position_pct: float
    top3_concentration_pct: float
    largest_asset_class_pct: float
    priced_position_coverage_pct: float
    unpriced_position_count: int
    mixed_currency_warning: bool
    foreign_currency_position_count: int
    linked_return_pct: Optional[float]
    benchmark_return_pct: Optional[float]
    relative_return_pct: Optional[float]
    performance_comparable: bool
    benchmark_available: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "portfolio_name": self.portfolio_name,
            "base_currency": self.base_currency,
            "priced_market_value": self.priced_market_value,
            "total_cost_basis": self.total_cost_basis,
            "unrealized_pl": self.unrealized_pl,
            "cash_pct": self.cash_pct,
            "invested_pct": self.invested_pct,
            "largest_position_pct": self.largest_position_pct,
            "top3_concentration_pct": self.top3_concentration_pct,
            "largest_asset_class_pct": self.largest_asset_class_pct,
            "priced_position_coverage_pct": self.priced_position_coverage_pct,
            "unpriced_position_count": self.unpriced_position_count,
            "mixed_currency_warning": self.mixed_currency_warning,
            "foreign_currency_position_count": self.foreign_currency_position_count,
            "linked_return_pct": self.linked_return_pct,
            "benchmark_return_pct": self.benchmark_return_pct,
            "relative_return_pct": self.relative_return_pct,
            "performance_comparable": self.performance_comparable,
            "benchmark_available": self.benchmark_available,
        }


@dataclass(frozen=True)
class AdviserDataQuality:
    valuation_complete: bool
    performance_comparable: bool
    benchmark_available: bool
    transaction_history_complete: bool
    mixed_currency: bool
    unpriced_position_count: int
    warnings: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valuation_complete": self.valuation_complete,
            "performance_comparable": self.performance_comparable,
            "benchmark_available": self.benchmark_available,
            "transaction_history_complete": self.transaction_history_complete,
            "mixed_currency": self.mixed_currency,
            "unpriced_position_count": self.unpriced_position_count,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AdviserContext:
    portfolio: AdviserPortfolioFacts
    findings: Tuple[AdviserFinding, ...]
    data_quality: AdviserDataQuality
    generated_from_snapshot_count: int
    deterministic_only: bool
    schema_version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio": self.portfolio.to_dict(),
            "findings": [item.to_dict() for item in self.findings],
            "data_quality": self.data_quality.to_dict(),
            "generated_from_snapshot_count": self.generated_from_snapshot_count,
            "deterministic_only": self.deterministic_only,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class AdviserBrief:
    headline: str
    portfolio_summary: str
    top_findings: Tuple[AdviserFinding, ...]
    supporting_findings: Tuple[AdviserFinding, ...]
    data_quality_notes: Tuple[str, ...]
    questions_for_user: Tuple[str, ...]
    prohibited_claims: Tuple[str, ...]
    context: AdviserContext

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headline": self.headline,
            "portfolio_summary": self.portfolio_summary,
            "top_findings": [item.to_dict() for item in self.top_findings],
            "supporting_findings": [item.to_dict() for item in self.supporting_findings],
            "data_quality_notes": list(self.data_quality_notes),
            "questions_for_user": list(self.questions_for_user),
            "prohibited_claims": list(self.prohibited_claims),
            "context": self.context.to_dict(),
        }
