from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


class PortfolioAllocationPolicyRepository:
    def __init__(self, client) -> None:
        self.client = client
        self.table = "portfolio_allocation_policies"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_for_portfolio(self, user_id: str, portfolio_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def upsert(self, user_id: str, portfolio_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.get_for_portfolio(user_id, portfolio_id)
        body = dict(payload)
        body["updated_at"] = self._now_iso()
        if existing:
            response = (
                self.client.table(self.table)
                .update(body)
                .eq("user_id", user_id)
                .eq("portfolio_id", portfolio_id)
                .execute()
            )
        else:
            body.update(
                {
                    "user_id": user_id,
                    "portfolio_id": portfolio_id,
                    "created_at": self._now_iso(),
                }
            )
            response = self.client.table(self.table).insert(body).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Hedef dağılım kaydedilemedi.")
        return rows[0]

    def delete_for_portfolio(self, user_id: str, portfolio_id: str) -> None:
        (
            self.client.table(self.table)
            .delete()
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .execute()
        )
