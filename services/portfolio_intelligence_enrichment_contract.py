from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from services.nabi_intelligence_facade import InvestmentIntelligenceView
from services.participation_filter_service import PARTICIPATION_UNKNOWN
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioIntelligenceView,
    PositionValuationRow,
)

RESEARCH_COVERAGE_AVAILABLE = "research_available"
RESEARCH_COVERAGE_LIMITED = "limited_evidence"
RESEARCH_COVERAGE_REVIEW = "participation_review_required"
RESEARCH_COVERAGE_UNAVAILABLE = "research_unavailable"
RESEARCH_COVERAGE_NOT_EVALUATED = "not_evaluated"

RESEARCH_COVERAGE_LABELS = {
    RESEARCH_COVERAGE_AVAILABLE: "Araştırma mevcut",
    RESEARCH_COVERAGE_LIMITED: "Sınırlı kanıt",
    RESEARCH_COVERAGE_REVIEW: "Katılım incelemesi gerekli",
    RESEARCH_COVERAGE_UNAVAILABLE: "Araştırma kullanılamaz",
    RESEARCH_COVERAGE_NOT_EVALUATED: "Değerlendirilmedi",
}

ATTENTION_SEVERITY_HIGH = "high"
ATTENTION_SEVERITY_WATCH = "watch"
ATTENTION_SEVERITY_INFO = "info"

CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT = 20.0
CONCENTRATION_TOP3_THRESHOLD_PCT = 50.0
UNRESEARCHED_WEIGHT_THRESHOLD_PCT = 30.0


@dataclass(frozen=True)
class SymbolAccountBreakdown:
    account_id: str
    account_label: str
    quantity: float
    market_value: Optional[float]
    average_cost: float


@dataclass(frozen=True)
class ConsolidatedSymbolRow:
    symbol: str
    company_name: str
    total_quantity: float
    total_cost_basis: float
    total_market_value: Optional[float]
    total_unrealized_pl: Optional[float]
    portfolio_weight_pct: Optional[float]
    participation_status: str
    research_coverage_label: str
    account_breakdown: Tuple[SymbolAccountBreakdown, ...]


@dataclass(frozen=True)
class EnrichedPositionRow:
    valuation: PositionValuationRow
    company_name: str
    account_id: str
    account_label: str
    institution: Optional[str]
    account_weight_pct: Optional[float]
    sector: Optional[str]
    industry: Optional[str]
    country: Optional[str]
    participation_status: str
    research_coverage: str
    research_coverage_label: str
    research_allowed_inferred: Optional[bool]
    research_status: Optional[str]
    has_candidate: bool
    has_participation_snapshot: bool


@dataclass(frozen=True)
class CoverageMetadata:
    priced_market_value_coverage_pct: float
    participation_status_coverage_pct: float
    sector_coverage_pct: float
    price_data_complete: bool
    limitations: Tuple[str, ...]


@dataclass(frozen=True)
class PortfolioAttentionItem:
    code: str
    severity: str
    title: str
    detail: str
    affected_symbols: Tuple[str, ...] = ()
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    evidence_source: str = "portfolio_intelligence"


@dataclass(frozen=True)
class PortfolioIntelligenceDashboardView:
    base: PortfolioIntelligenceView
    enriched_positions: Tuple[EnrichedPositionRow, ...]
    sector_allocation: Tuple[AllocationSlice, ...]
    country_allocation: Tuple[AllocationSlice, ...]
    currency_allocation: Tuple[AllocationSlice, ...]
    participation_allocation: Tuple[AllocationSlice, ...]
    research_coverage_allocation: Tuple[AllocationSlice, ...]
    account_allocation: Tuple[AllocationSlice, ...]
    consolidated_symbols: Tuple[ConsolidatedSymbolRow, ...]
    selected_account_id: Optional[str]
    participation_eligible_weight_pct: float
    participation_non_eligible_weight_pct: float
    participation_review_weight_pct: float
    participation_unknown_weight_pct: float
    research_coverage_weight_pct: float
    unresearched_weight_pct: float
    top5_concentration_pct: float
    return_pct: Optional[float]
    coverage: CoverageMetadata
    attention_items: Tuple[PortfolioAttentionItem, ...]


def participation_status_from_nabi(
    nabi: Optional[InvestmentIntelligenceView],
) -> str:
    if nabi is None:
        return PARTICIPATION_UNKNOWN
    return str(nabi.participation_status or PARTICIPATION_UNKNOWN).strip() or PARTICIPATION_UNKNOWN
