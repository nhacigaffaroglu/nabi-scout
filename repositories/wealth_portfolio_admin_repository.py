from __future__ import annotations

from typing import Any, Dict, List


class WealthPortfolioAdminRepository:
    """Headless scheduler access to active portfolios — service role only."""

    def __init__(self, client) -> None:
        self.client = client

    def list_active_portfolios_for_snapshot(self) -> List[Dict[str, Any]]:
        portfolios = (
            self.client.table("wealth_portfolios")
            .select("id,user_id,name,base_currency,is_default")
            .limit(5000)
            .execute()
            .data
            or []
        )
        active: List[Dict[str, Any]] = []
        for portfolio in portfolios:
            portfolio_id = str(portfolio.get("id") or "")
            if not portfolio_id:
                continue
            accounts = (
                self.client.table("wealth_accounts")
                .select("id")
                .eq("portfolio_id", portfolio_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not accounts:
                continue
            active.append(portfolio)
        return active
