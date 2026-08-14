from __future__ import annotations

from typing import Any, Dict, List, Optional


class InvestmentThesisRepository:
    TABLE = "investment_thesis_snapshots"

    def __init__(self, client) -> None:
        self.client = client

    def append_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.client.table(self.TABLE).insert(payload).execute()
        return response.data[0] if response.data else payload

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return None
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .order("captured_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def get_recent_history(
        self,
        symbol: str,
        *,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return []
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .order("captured_at", desc=True)
            .limit(max(1, min(int(limit), 25)))
            .execute()
        )
        return response.data or []
