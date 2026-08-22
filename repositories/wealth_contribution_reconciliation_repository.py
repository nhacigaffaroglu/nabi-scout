from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional


class WealthContributionReconciliationRepository:
    TABLE = "wealth_contribution_reconciliations"

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_for_portfolio(self, user_id: str, portfolio_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        return response.data or []

    @staticmethod
    def _parse_through(value: Any) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return date.fromisoformat(str(value)[:10])

    def upsert(
        self,
        *,
        user_id: str,
        portfolio_id: str,
        reconciled_through: date,
        provenance: str = "USER_DEFINED",
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        provenance_value = "USER_DEFINED"
        notes_value = notes.strip() if notes else None
        through = reconciled_through
        existing = self.get_for_portfolio(user_id, portfolio_id)
        if existing is not None:
            existing_through = self._parse_through(existing.get("reconciled_through"))
            if existing_through > through:
                through = existing_through
            if notes_value is None:
                notes_value = existing.get("notes")
            payload = {
                "reconciled_through": through.isoformat(),
                "provenance": provenance_value,
                "notes": notes_value,
                "updated_at": self._now_iso(),
            }
            response = (
                self.client.table(self.TABLE)
                .update(payload)
                .eq("user_id", user_id)
                .eq("portfolio_id", portfolio_id)
                .execute()
            )
        else:
            payload = {
                "user_id": user_id,
                "portfolio_id": portfolio_id,
                "reconciled_through": through.isoformat(),
                "provenance": provenance_value,
                "notes": notes_value,
                "updated_at": self._now_iso(),
                "created_at": self._now_iso(),
            }
            response = self.client.table(self.TABLE).insert(payload).execute()
        rows = response.data or []
        if rows:
            return rows[0]
        saved = self.get_for_portfolio(user_id, portfolio_id)
        if saved is None:
            raise RuntimeError("Contribution reconciliation upsert failed.")
        return saved
