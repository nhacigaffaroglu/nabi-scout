from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class WealthLiabilityRepository:
    def __init__(self, client):
        self.client = client
        self.table = "wealth_liabilities"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .order("name")
            .execute()
        )
        return response.data or []

    def create(
        self,
        *,
        user_id: str,
        name: str,
        liability_type: str,
        currency: str = "USD",
        principal: float = 0.0,
        portfolio_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "portfolio_id": portfolio_id,
            "name": name.strip(),
            "liability_type": liability_type.strip().lower(),
            "currency": currency.strip().upper(),
            "principal": principal,
            "notes": notes.strip() if notes else None,
            "is_active": True,
            "updated_at": self._now_iso(),
        }
        response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Borç kaydı oluşturulamadı.")
        return rows[0]
