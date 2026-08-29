from __future__ import annotations

from typing import Any, Dict, List, Optional


class SecurityIntelligenceSnapshotRepository:
    TABLE = "security_intelligence_snapshots"

    def __init__(self, client) -> None:
        self.client = client

    def upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = (
            self.client.table(self.TABLE)
            .upsert(
                payload,
                on_conflict="symbol,as_of_key,facts_version,engine_version",
            )
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else payload

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return None
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .order("as_of", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def get_by_identity(
        self,
        symbol: str,
        *,
        as_of_key: str,
        facts_version: str,
        engine_version: str,
    ) -> Optional[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .eq("as_of_key", as_of_key)
            .eq("facts_version", facts_version)
            .eq("engine_version", engine_version)
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
            .order("as_of", desc=True)
            .limit(max(1, min(int(limit), 25)))
            .execute()
        )
        return response.data or []
