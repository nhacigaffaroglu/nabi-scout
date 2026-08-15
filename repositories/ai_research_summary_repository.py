from __future__ import annotations

from typing import Any, Dict, List, Optional


class AIResearchSummaryRepository:
    TABLE = "ai_research_summary_snapshots"

    def __init__(self, client) -> None:
        self.client = client

    def get_exact(
        self,
        symbol: str,
        semantic_identity: str,
    ) -> Optional[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        identity = str(semantic_identity or "").strip()
        if not normalized or not identity:
            return None
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .eq("semantic_identity", identity)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def save_if_absent(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        """Insert snapshot. Returns (row, inserted). On unique conflict reloads existing row."""
        try:
            response = self.client.table(self.TABLE).insert(payload).execute()
            row = response.data[0] if response.data else payload
            return row, True
        except Exception as exc:
            message = str(exc).lower()
            if "duplicate" not in message and "unique" not in message and "23505" not in message:
                raise
            existing = self.get_exact(
                str(payload.get("symbol") or ""),
                str(payload.get("semantic_identity") or ""),
            )
            if existing is None:
                raise
            return existing, False

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
            .order("generated_at", desc=True)
            .limit(max(1, min(int(limit), 25)))
            .execute()
        )
        return response.data or []

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return None
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None
