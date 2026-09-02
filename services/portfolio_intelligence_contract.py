from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from services.nabi_intelligence_facade import InvestmentIntelligenceView


@dataclass(frozen=True)
class PriceQuote:
    """External read-only market price snapshot."""

    price: Optional[float]
    currency: Optional[str]
    available: bool
    source: str = "unknown"
    error: Optional[str] = None
    as_of: Optional[str] = None


@dataclass(frozen=True)
class PositionValuationRow:
    position_id: str
    account_id: str
    asset_id: str
    symbol: str
    asset_class: str
    account_name: str
    quantity: float
    average_cost: float
    valuation_currency: str
    price: Optional[float]
    price_available: bool
    market_value: Optional[float]
    cost_basis: float
    unrealized_pl: Optional[float]
    weight_pct: Optional[float]
    is_cash: bool
    included_in_base_totals: bool
    nabi: Optional[InvestmentIntelligenceView] = None
    native_market_value: Optional[float] = None
    fx_converted: bool = False
    fx_rate_used: Optional[float] = None
    fx_rate_date: Optional[str] = None
    fx_stale: bool = False
    fx_unavailable: bool = False
    price_as_of: Optional[str] = None
    cost_basis_unresolved: bool = False


@dataclass(frozen=True)
class AllocationSlice:
    key: str
    label: str
    market_value: float
    weight_pct: float


@dataclass(frozen=True)
class PortfolioHealthMetrics:
    """Concentration/weight metrics use priced base-currency positions only.

    priced_position_coverage_pct is count-based across all open positions
    (price_available / total_position_count), regardless of currency.
    """

    largest_position_weight_pct: float
    top3_concentration_pct: float
    largest_asset_class_concentration_pct: float
    cash_pct: float
    invested_pct: float
    priced_position_coverage_pct: float


@dataclass(frozen=True)
class PortfolioIntelligenceView:
    portfolio_id: str
    portfolio_name: str
    base_currency: str
    priced_total_market_value: float
    priced_total_cost_basis: float
    priced_total_unrealized_pl: float
    priced_position_count: int
    unpriced_position_count: int
    foreign_currency_position_count: int
    total_position_count: int
    mixed_currency_warning: bool
    fx_supported: bool
    priced_positions: List[PositionValuationRow]
    unpriced_positions: List[PositionValuationRow]
    foreign_currency_positions: List[PositionValuationRow]
    asset_class_allocation: List[AllocationSlice]
    account_allocation: List[AllocationSlice]
    health: PortfolioHealthMetrics
    valuation_errors: List[str]
    price_provider: str
    unique_price_symbols_fetched: int
