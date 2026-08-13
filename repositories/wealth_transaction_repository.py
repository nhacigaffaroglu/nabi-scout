from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class WealthTransactionRepository:
    def __init__(self, client):
        self.client = client
        self.table = "wealth_transactions"

    def list_for_user(self, user_id: str, *, limit: int = 200) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .order("executed_at", desc=True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or []

    def list_for_position(
        self,
        user_id: str,
        account_id: str,
        asset_id: str,
    ) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("account_id", account_id)
            .eq("asset_id", asset_id)
            .order("executed_at")
            .order("created_at")
            .execute()
        )
        return response.data or []

    def get_by_id(self, user_id: str, txn_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", txn_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def has_reversal_for(self, user_id: str, original_id: str) -> bool:
        response = (
            self.client.table(self.table)
            .select("id")
            .eq("user_id", user_id)
            .eq("reversal_of_id", original_id)
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def insert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("İşlem kaydedilemedi.")
        return rows[0]
