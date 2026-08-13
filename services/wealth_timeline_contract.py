from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PortfolioSnapshotView:
    id: str
    user_id: str
    portfolio_id: str
    captured_at: str
    base_currency: str
    priced_market_value: float
    total_cost_basis: float
    unrealized_pl: float
    cash_value: float
    invested_value: float
    liabilities_total: Optional[float]
    net_wealth_partial: Optional[float]
    priced_position_coverage_pct: float
    unpriced_position_count: int
    mixed_currency_warning: bool
    valuation_payload: Dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class PortfolioPerformancePeriod:
    period_start_at: str
    period_end_at: str
    base_currency: str
    start_priced_value: float
    end_priced_value: float
    portfolio_value_change: float
    external_inflows: float
    external_outflows: float
    net_external_flow: float
    investment_gain: float
    dividend_income: float
    fee_cost: float
    start_coverage_pct: float
    end_coverage_pct: float
    start_unpriced_count: int
    end_unpriced_count: int
    performance_comparable: bool
    simple_period_return_pct: Optional[float]
    warnings: List[str]


@dataclass(frozen=True)
class WealthTimelineView:
    portfolio_id: str
    portfolio_name: str
    base_currency: str
    snapshots: List[PortfolioSnapshotView]
    latest_period: Optional[PortfolioPerformancePeriod]
