from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


JOURNAL_ACTION_CONTEXTS = (
    "considering",
    "added",
    "increased",
    "reduced",
    "exited",
    "reviewed",
)


class WealthDecisionJournalRepository:
    def __init__(self, client) -> None:
        self.client = client
        self.table = "wealth_decision_journal"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_for_user(
        self,
        user_id: str,
        *,
        symbol: Optional[str] = None,
        portfolio_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if symbol:
            query = query.eq("symbol", symbol.strip().upper())
        if portfolio_id:
            query = query.eq("portfolio_id", portfolio_id)
        response = query.execute()
        return response.data or []

    def get_by_id(self, user_id: str, entry_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", entry_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("updated_at", self._now_iso())
        response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Karar günlüğü kaydı oluşturulamadı.")
        return rows[0]

    def update(self, user_id: str, entry_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(updates)
        payload["updated_at"] = self._now_iso()
        response = (
            self.client.table(self.table)
            .update(payload)
            .eq("user_id", user_id)
            .eq("id", entry_id)
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise RuntimeError("Karar günlüğü kaydı güncellenemedi.")
        return rows[0]
