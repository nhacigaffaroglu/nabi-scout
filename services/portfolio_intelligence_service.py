from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from services.nabi_intelligence_facade import (
    InvestmentIntelligenceView,
    get_investment_intelligence,
)
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.portfolio_intelligence_engine import (
    rollup_portfolio_intelligence,
    value_position,
)
from services.wealth_core_service import WealthCoreService
from services.wealth_price_service import WealthPriceService


class PortfolioIntelligenceService:
    """Build read-only portfolio valuation and allocation rollups."""

    def __init__(
        self,
        wealth: WealthCoreService,
        price_service: WealthPriceService,
        *,
        nabi_client=None,
        intelligence_loader: Optional[
            Callable[..., InvestmentIntelligenceView]
        ] = None,
    ) -> None:
        self.wealth = wealth
        self.price_service = price_service
        self.nabi_client = nabi_client
        self._load_intelligence = intelligence_loader or get_investment_intelligence

    def build_view(
        self,
        portfolio: Dict[str, Any],
        *,
        enrich_nabi: bool = False,
    ) -> PortfolioIntelligenceView:
        positions = self.wealth.list_positions()
        accounts = self.wealth.list_accounts()
        assets = self.wealth.list_assets()

        account_by_id = {row["id"]: row for row in accounts}
        asset_by_id = {row["id"]: row for row in assets}

        prefetch_inputs = []
        for position in positions:
            asset = asset_by_id.get(position.get("asset_id"), {})
            prefetch_inputs.append(
                (
                    str(asset.get("symbol") or ""),
                    str(asset.get("asset_class") or ""),
                    str(asset.get("currency") or "USD"),
                )
            )
        self.price_service.prefetch_assets(prefetch_inputs)

        valuation_errors: List[str] = []
        nabi_cache: Dict[str, InvestmentIntelligenceView] = {}
        rows = []
        for position in positions:
            asset = asset_by_id.get(position.get("asset_id"), {})
            account = account_by_id.get(position.get("account_id"), {})
            quote = self.price_service.get_quote_for_asset(
                str(asset.get("symbol") or ""),
                str(asset.get("asset_class") or ""),
                str(asset.get("currency") or "USD"),
            )
            if quote.error and quote.error not in {"missing_price"}:
                valuation_errors.append(f"{asset.get('symbol')}: {quote.error}")

            row = value_position(
                position=position,
                asset=asset,
                account=account,
                base_currency=str(portfolio.get("base_currency") or "USD"),
                quote=quote,
            )
            if enrich_nabi and self.nabi_client is not None:
                symbol_key = row.symbol.strip().upper()
                if symbol_key not in nabi_cache:
                    nabi_cache[symbol_key] = self._load_intelligence(
                        self.nabi_client,
                        row.symbol,
                        market=asset.get("market"),
                    )
                row = self._attach_nabi(row, nabi_cache[symbol_key])
            rows.append(row)

        provider = (
            self.price_service.PROVIDER_NAME
            if self.price_service.fetch_count > 0
            else "none"
        )
        if any(row.is_cash for row in rows):
            provider = f"{provider}+nominal_cash"

        return rollup_portfolio_intelligence(
            portfolio_id=str(portfolio.get("id") or ""),
            portfolio_name=str(portfolio.get("name") or ""),
            base_currency=str(portfolio.get("base_currency") or "USD"),
            rows=rows,
            price_provider=provider,
            unique_price_symbols_fetched=self.price_service.fetch_count,
            valuation_errors=valuation_errors,
        )

    def _attach_nabi(
        self,
        row,
        intel: InvestmentIntelligenceView,
    ):
        from services.portfolio_intelligence_contract import PositionValuationRow

        return PositionValuationRow(
            position_id=row.position_id,
            account_id=row.account_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            asset_class=row.asset_class,
            account_name=row.account_name,
            quantity=row.quantity,
            average_cost=row.average_cost,
            valuation_currency=row.valuation_currency,
            price=row.price,
            price_available=row.price_available,
            market_value=row.market_value,
            cost_basis=row.cost_basis,
            unrealized_pl=row.unrealized_pl,
            weight_pct=row.weight_pct,
            is_cash=row.is_cash,
            included_in_base_totals=row.included_in_base_totals,
            nabi=intel,
        )
