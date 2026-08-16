from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

from services.fx_conversion_engine import FxAdjustedTotals
from services.portfolio_intelligence_contract import PortfolioIntelligenceView


@dataclass(frozen=True)
class TotalWealthMetrics:
    base_currency: str
    total_wealth: Optional[float]
    invested_assets: float
    cash: float
    equity: float
    funds_etfs: float
    other_assets: float
    unconverted_value: float
    unpriced_count: int
    participation_covered_pct: Optional[float]
    research_covered_pct: Optional[float]
    fx_conversion_coverage_pct: Optional[float]
    partial_total: bool
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_total_wealth_metrics(
    view: PortfolioIntelligenceView,
    *,
    fx_totals: Optional[FxAdjustedTotals] = None,
    participation_covered_pct: Optional[float] = None,
    research_covered_pct: Optional[float] = None,
) -> TotalWealthMetrics:
    base = view.base_currency
    converted = fx_totals.converted_market_value if fx_totals else view.priced_total_market_value
    unconverted = fx_totals.unconverted_market_value if fx_totals else 0.0
    unpriced = view.unpriced_position_count

    cash = sum(
        float(row.market_value or 0.0)
        for row in view.priced_positions
        if row.is_cash
    )
    equity = sum(
        float(row.market_value or 0.0)
        for row in view.priced_positions
        if row.asset_class == "equity" and not row.is_cash
    )
    funds = sum(
        float(row.market_value or 0.0)
        for row in view.priced_positions
        if row.asset_class in {"etf", "fund"}
    )
    other = sum(
        float(row.market_value or 0.0)
        for row in view.priced_positions
        if row.asset_class not in {"equity", "etf", "fund", "cash"}
    )
    invested = converted - cash if converted else 0.0

    partial = unpriced > 0 or unconverted > 0
    limitation_parts = []
    if unpriced:
        limitation_parts.append(f"{unpriced} fiyatlanmamış pozisyon.")
    if unconverted > 0:
        limitation_parts.append(f"{unconverted:.2f} {base} dönüştürülemedi.")
    limitation = " ".join(limitation_parts)

    total = converted if not partial else converted
    return TotalWealthMetrics(
        base_currency=base,
        total_wealth=total if converted > 0 or not partial else None,
        invested_assets=invested,
        cash=cash,
        equity=equity,
        funds_etfs=funds,
        other_assets=other,
        unconverted_value=unconverted,
        unpriced_count=unpriced,
        participation_covered_pct=participation_covered_pct,
        research_covered_pct=research_covered_pct,
        fx_conversion_coverage_pct=fx_totals.conversion_coverage_pct if fx_totals else None,
        partial_total=partial,
        limitation=limitation,
    )
