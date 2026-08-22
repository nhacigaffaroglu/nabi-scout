from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence


class WealthPlanningFxRepository:
    TABLE = "wealth_planning_fx_assumptions"

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_for_portfolio(self, user_id: str, portfolio_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .order("year")
            .execute()
        )
        return response.data or []

    def replace_schedule(
        self,
        *,
        user_id: str,
        portfolio_id: str,
        rows: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        now = self._now_iso()
        (
            self.client.table(self.TABLE)
            .delete()
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .execute()
        )
        if not rows:
            return []
        payload = [
            {
                "user_id": user_id,
                "portfolio_id": portfolio_id,
                "year": int(row["year"]),
                "usdtry": str(row["usdtry"]),
                "provenance": str(row.get("provenance") or "USER_DEFINED"),
                "created_at": now,
                "updated_at": now,
            }
            for row in rows
        ]
        response = self.client.table(self.TABLE).insert(payload).execute()
        return response.data or []

    def insert_absent_years(
        self,
        *,
        user_id: str,
        portfolio_id: str,
        rows: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Insert only years that are not already stored. Never updates or deletes."""
        existing = self.list_for_portfolio(user_id, portfolio_id)
        present = {int(row["year"]) for row in existing if row.get("year") is not None}
        absent = [row for row in rows if int(row["year"]) not in present]
        if not absent:
            return []
        now = self._now_iso()
        payload = [
            {
                "user_id": user_id,
                "portfolio_id": portfolio_id,
                "year": int(row["year"]),
                "usdtry": str(row["usdtry"]),
                "provenance": str(row.get("provenance") or "USER_DEFINED"),
                "created_at": now,
                "updated_at": now,
            }
            for row in absent
        ]
        response = self.client.table(self.TABLE).insert(payload).execute()
        return response.data or []
