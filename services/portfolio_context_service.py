from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from services.candidate_price_service import CandidatePriceService
from services.portfolio_account_helpers import format_account_display
from services.portfolio_intelligence_helpers import iter_all_position_rows
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.wealth_core_service import WealthCoreService
from services.wealth_exposure_bridge import build_wealth_exposure_context


@dataclass(frozen=True)
class AccountHoldingBreakdown:
    account_id: str
    account_label: str
    quantity: float
    market_value: Optional[float]
    cost_basis: float


@dataclass(frozen=True)
class PortfolioSymbolContext:
    symbol: str
    held: bool
    quantity: Optional[float]
    portfolio_weight_pct: Optional[float]
    cost_basis: Optional[float]
    unrealized_pl: Optional[float]
    market_value: Optional[float]
    account_names: Tuple[str, ...]
    account_breakdown: Tuple[AccountHoldingBreakdown, ...]
    limitations: Tuple[str, ...]


def build_symbol_portfolio_context(
    client,
    user_id: str,
    symbol: str,
) -> Optional[PortfolioSymbolContext]:
    """Lightweight portfolio context for Company Report — no FMP/LLM calls."""
    wealth = WealthCoreService(client, user_id)
    portfolio = wealth.portfolios.get_default_for_user(user_id)
    if portfolio is None:
        return None

    accounts = {str(row["id"]): row for row in wealth.list_accounts()}
    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(
        wealth,
        price_service,
        nabi_client=client,
    )
    view = intelligence.build_view(portfolio, enrich_nabi=False)
    exposure = build_wealth_exposure_context(view, symbol)
    if not exposure.held:
        return None

    normalized = str(symbol or "").strip().upper()
    breakdown: list[AccountHoldingBreakdown] = []
    for row in iter_all_position_rows(view):
        if str(row.symbol or "").strip().upper() != normalized or row.is_cash:
            continue
        account = accounts.get(str(row.account_id or ""), {})
        breakdown.append(
            AccountHoldingBreakdown(
                account_id=str(row.account_id or ""),
                account_label=format_account_display(account),
                quantity=float(row.quantity),
                market_value=row.market_value,
                cost_basis=float(row.cost_basis),
            )
        )

    return PortfolioSymbolContext(
        symbol=exposure.symbol,
        held=True,
        quantity=exposure.quantity,
        portfolio_weight_pct=exposure.portfolio_weight_pct,
        cost_basis=exposure.cost_basis,
        unrealized_pl=exposure.unrealized_pl,
        market_value=exposure.market_value,
        account_names=exposure.account_names,
        account_breakdown=tuple(
            sorted(breakdown, key=lambda item: item.account_label)
        ),
        limitations=exposure.limitations,
    )
