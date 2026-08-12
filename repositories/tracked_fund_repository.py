from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.fund_tracking_contract import prepare_tracked_fund_payload


class TrackedFundRepository:
    def __init__(self, client) -> None:
        self.client = client
        self.table = "tracked_funds"

    def upsert_by_symbol(
        self,
        payload: Dict[str, Any],
        *,
        touch_last_reviewed: bool = True,
    ) -> Dict[str, Any]:
        cleaned = prepare_tracked_fund_payload(
            payload,
            touch_last_reviewed=touch_last_reviewed,
        )
        response = (
            self.client.table(self.table)
            .upsert(cleaned, on_conflict="symbol")
            .execute()
        )
        return response.data[0] if response.data else cleaned

    def get_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return None
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("symbol", normalized)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def is_tracked(self, symbol: str) -> bool:
        return self.get_by_symbol(symbol) is not None

    def list_all(
        self,
        *,
        order_by: str = "updated_at",
        descending: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        query = (
            self.client.table(self.table)
            .select("*")
            .order(order_by, desc=descending)
        )
        if limit is not None:
            query = query.limit(limit)
        return query.execute().data or []

    def delete_by_symbol(self, symbol: str) -> bool:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return False
        if self.get_by_symbol(normalized) is None:
            return False
        (
            self.client.table(self.table)
            .delete()
            .eq("symbol", normalized)
            .execute()
        )
        return True
