from __future__ import annotations

from typing import Optional, Tuple

from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.unified_research_contract import WealthExposureContext


def build_wealth_exposure_context(
    portfolio_view: Optional[PortfolioIntelligenceView],
    symbol: str,
    *,
    high_concentration_threshold_pct: float = 15.0,
) -> WealthExposureContext:
    normalized = str(symbol or "").strip().upper()
    if not normalized or portfolio_view is None:
        return WealthExposureContext(
            symbol=normalized,
            held=False,
            quantity=None,
            market_value=None,
            portfolio_weight_pct=None,
            cost_basis=None,
            unrealized_pl=None,
            account_names=(),
            concentration_context=None,
            limitations=("Portföy verisi mevcut değil.",),
        )

    matches = [
        row
        for row in portfolio_view.positions
        if str(row.symbol or "").strip().upper() == normalized and not row.is_cash
    ]
    if not matches:
        return WealthExposureContext(
            symbol=normalized,
            held=False,
            quantity=None,
            market_value=None,
            portfolio_weight_pct=None,
            cost_basis=None,
            unrealized_pl=None,
            account_names=(),
            concentration_context="Portföyde açık pozisyon yok.",
            limitations=(),
        )

    quantity = sum(row.quantity for row in matches)
    market_value = sum(row.market_value or 0.0 for row in matches if row.market_value is not None)
    if not any(row.market_value is not None for row in matches):
        market_value = None
    cost_basis = sum(row.cost_basis for row in matches)
    unrealized = None
    if market_value is not None:
        unrealized = market_value - cost_basis
    weight = sum(row.weight_pct or 0.0 for row in matches if row.weight_pct is not None)
    if not any(row.weight_pct is not None for row in matches):
        weight = None
    accounts = tuple(sorted({row.account_name for row in matches if row.account_name}))

    concentration = None
    limitations: Tuple[str, ...] = ()
    if weight is None:
        limitations = ("Pozisyon ağırlığı fiyat eksikliği nedeniyle hesaplanamadı.",)
    elif weight >= high_concentration_threshold_pct:
        concentration = f"Pozisyon portföyün yaklaşık %{weight:.1f}'ini oluşturuyor."
    else:
        concentration = f"Pozisyon portföyde %{weight:.1f} ağırlığında."

    return WealthExposureContext(
        symbol=normalized,
        held=True,
        quantity=quantity,
        market_value=market_value,
        portfolio_weight_pct=weight,
        cost_basis=cost_basis,
        unrealized_pl=unrealized,
        account_names=accounts,
        concentration_context=concentration,
        limitations=limitations,
    )
