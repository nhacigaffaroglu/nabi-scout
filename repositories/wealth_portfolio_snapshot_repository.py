from __future__ import annotations

from typing import Any, Dict, List


class WealthPortfolioSnapshotRepository:
    def __init__(self, client):
        self.client = client
        self.table = "wealth_portfolio_snapshots"

    def insert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Portföy görüntüsü kaydedilemedi.")
        return rows[0]

    def list_for_portfolio(
        self,
        user_id: str,
        portfolio_id: str,
        *,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .order("captured_at", desc=True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or []
