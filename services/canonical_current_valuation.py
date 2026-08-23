"""Single current-wealth entry point. No new valuation math.

Canonical path:
  persisted candidate / BIST EOD prices (CandidatePriceService)
        ↓
  PortfolioIntelligenceService.build_view
        ↓
  apply_fx_to_portfolio_view via persisted FxRateService (current fx_rates)
        ↓
  PortfolioIntelligenceView.priced_total_market_value

Never uses WealthPriceService (FMP) or wealth_planning_fx_assumptions.
"""

from __future__ import annotations

from typing import Any, Optional

from services.fx_rate_service import FxRateService
from services.nabi_dashboard_presentation import (
    TryEquivalentView,
    present_current_try_equivalent,
)
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.total_wealth_service import TotalWealthMetrics, compute_total_wealth_metrics
from services.wealth_goal_models import CurrentWealthSnapshot, current_wealth_from_portfolio_view


def build_canonical_current_view(
    wealth,
    *,
    enrich_nabi: bool = False,
    account_id: Optional[str] = None,
    portfolio: Optional[dict[str, Any]] = None,
) -> PortfolioIntelligenceView:
    from services.candidate_price_service import CandidatePriceService
    from services.portfolio_intelligence_service import PortfolioIntelligenceService

    client = getattr(wealth, "client", None)
    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(
        wealth,
        price_service,
        nabi_client=client if enrich_nabi else None,
    )
    resolved = portfolio
    if resolved is None:
        getter = getattr(wealth, "ensure_default_portfolio", None)
        resolved = getter() if callable(getter) else None
    if resolved is None:
        resolved = {"id": "", "name": "", "base_currency": "USD"}
    return intelligence.build_view(
        resolved,
        enrich_nabi=enrich_nabi,
        account_id=account_id,
    )


def canonical_current_snapshot(
    view: PortfolioIntelligenceView,
    *,
    positions=None,
    assets=None,
    goal_currency: str = "USD",
) -> CurrentWealthSnapshot:
    return current_wealth_from_portfolio_view(
        view,
        goal_currency=goal_currency,
        positions=positions,
        assets=assets,
    )


def canonical_total_wealth_usd(view: PortfolioIntelligenceView) -> float:
    return float(view.priced_total_market_value or 0.0)


def canonical_wealth_metrics(
    view: PortfolioIntelligenceView,
    **kwargs: Any,
) -> TotalWealthMetrics:
    return compute_total_wealth_metrics(view, **kwargs)


def canonical_try_equivalent(
    view: PortfolioIntelligenceView,
    fx_service: Optional[FxRateService],
) -> TryEquivalentView:
    return present_current_try_equivalent(canonical_total_wealth_usd(view), fx_service)
