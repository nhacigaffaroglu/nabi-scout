from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class WealthPositionRepository:
    def __init__(self, client):
        self.client = client
        self.table = "wealth_positions"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        return response.data or []

    def get_for_account_asset(
        self,
        user_id: str,
        account_id: str,
        asset_id: str,
    ) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("account_id", account_id)
            .eq("asset_id", asset_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def upsert(
        self,
        *,
        user_id: str,
        account_id: str,
        asset_id: str,
        quantity: float,
        average_cost: float,
        cost_currency: str,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "account_id": account_id,
            "asset_id": asset_id,
            "quantity": quantity,
            "average_cost": average_cost,
            "cost_currency": cost_currency,
            "updated_at": self._now_iso(),
        }
        response = (
            self.client.table(self.table)
            .upsert(payload, on_conflict="user_id,account_id,asset_id")
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise RuntimeError("Pozisyon güncellenemedi.")
        return rows[0]

    def delete_for_account_asset(
        self,
        user_id: str,
        account_id: str,
        asset_id: str,
    ) -> None:
        (
            self.client.table(self.table)
            .delete()
            .eq("user_id", user_id)
            .eq("account_id", account_id)
            .eq("asset_id", asset_id)
            .execute()
        )
