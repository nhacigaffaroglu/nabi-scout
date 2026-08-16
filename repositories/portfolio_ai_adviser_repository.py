from __future__ import annotations

from typing import Any, Dict, List, Optional


class PortfolioAIAdviserRepository:
    TABLE = "portfolio_ai_adviser_snapshots"

    def __init__(self, client) -> None:
        self.client = client

    def get_exact(
        self,
        user_id: str,
        portfolio_id: str,
        semantic_identity: str,
    ) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .eq("semantic_identity", semantic_identity)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def save_if_absent(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        try:
            response = self.client.table(self.TABLE).insert(payload).execute()
            row = response.data[0] if response.data else payload
            return row, True
        except Exception as exc:
            message = str(exc).lower()
            if "duplicate" not in message and "unique" not in message and "23505" not in message:
                raise
            existing = self.get_exact(
                str(payload.get("user_id") or ""),
                str(payload.get("portfolio_id") or ""),
                str(payload.get("semantic_identity") or ""),
            )
            if existing is None:
                raise
            return existing, False

    def get_latest(self, user_id: str, portfolio_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None
