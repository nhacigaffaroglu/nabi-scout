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
        rows = response.data if isinstance(response.data, list) else []
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
        rows = response.data if isinstance(response.data, list) else []
        return rows[0] if rows else None

    def get_previous(
        self,
        symbol: str,
        *,
        before_as_of: Optional[str] = None,
        exclude_id: Optional[str] = None,
        facts_version: Optional[str] = None,
        engine_version: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Latest persisted snapshot strictly older than the current evaluation."""
        rows = self.get_recent_history(symbol, limit=25)
        before = str(before_as_of or "").strip()
        for row in rows:
            if exclude_id and str(row.get("id") or "") == str(exclude_id):
                continue
            if facts_version and str(row.get("facts_version") or "") != facts_version:
                continue
            if engine_version and str(row.get("engine_version") or "") != engine_version:
                continue
            as_of = str(row.get("as_of") or "")
            if before and as_of and as_of >= before:
                continue
            if before and not as_of:
                continue
            return row
        return None

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
        return response.data if isinstance(response.data, list) else []
