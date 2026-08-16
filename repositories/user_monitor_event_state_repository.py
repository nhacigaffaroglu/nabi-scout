from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class UserMonitorEventStateRepository:
    TABLE = "user_monitor_event_state"

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_state(self, user_id: str, monitor_event_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("monitor_event_id", monitor_event_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def list_for_user(self, user_id: str, *, limit: int = 500) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(max(1, min(limit, 1000)))
            .execute()
        )
        return response.data or []

    def upsert_state(
        self,
        *,
        user_id: str,
        monitor_event_id: str,
        status: str,
        portfolio_impact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        existing = self.get_state(user_id, monitor_event_id)
        payload = {
            "user_id": user_id,
            "monitor_event_id": monitor_event_id,
            "status": status,
            "updated_at": self._now_iso(),
        }
        if portfolio_impact is not None:
            payload["portfolio_impact"] = portfolio_impact
        if status == "reviewed":
            payload["reviewed_at"] = self._now_iso()
        if existing is None:
            payload["created_at"] = self._now_iso()
            response = self.client.table(self.TABLE).insert(payload).execute()
            rows = response.data or []
            return rows[0] if rows else payload
        response = (
            self.client.table(self.TABLE)
            .update(payload)
            .eq("user_id", user_id)
            .eq("monitor_event_id", monitor_event_id)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else {**existing, **payload}
