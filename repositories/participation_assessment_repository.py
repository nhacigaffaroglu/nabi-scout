from __future__ import annotations

from typing import Any, Dict, List, Optional


class ParticipationAssessmentRepository:
    TABLE = "participation_assessment_snapshots"

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
            .order("assessed_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def list_latest_by_symbol(self) -> Dict[str, Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .order("assessed_at", desc=True)
            .execute()
        )
        latest: Dict[str, Dict[str, Any]] = {}
        for row in response.data or []:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol and symbol not in latest:
                latest[symbol] = row
        return latest

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
            .order("assessed_at", desc=True)
            .limit(max(1, int(limit)))
            .execute()
        )
        return response.data or []
