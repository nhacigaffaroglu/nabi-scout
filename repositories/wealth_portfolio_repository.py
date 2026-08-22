from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from services.wealth_contract import normalize_market, normalize_symbol


class WealthPortfolioRepository:
    def __init__(self, client):
        self.client = client
        self.table = "wealth_portfolios"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return response.data or []

    def get_default_for_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("is_default", True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def create(
        self,
        *,
        user_id: str,
        name: str,
        base_currency: str = "USD",
        is_default: bool = False,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "name": name.strip(),
            "base_currency": base_currency.strip().upper(),
            "is_default": is_default,
            "updated_at": self._now_iso(),
        }
        response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Portföy oluşturulamadı.")
        return rows[0]

    def set_contribution_tracking_start_date(
        self,
        user_id: str,
        portfolio_id: str,
        tracking_start: date,
    ) -> Dict[str, Any]:
        payload = {
            "contribution_tracking_start_date": tracking_start.isoformat(),
            "updated_at": self._now_iso(),
        }
        response = (
            self.client.table(self.table)
            .update(payload)
            .eq("user_id", user_id)
            .eq("id", portfolio_id)
            .execute()
        )
        rows = response.data or []
        if rows:
            return rows[0]
        existing = [
            row
            for row in self.list_for_user(user_id)
            if str(row.get("id") or "") == str(portfolio_id)
        ]
        if not existing:
            raise RuntimeError("Katkı takibi başlangıç tarihi kaydedilemedi.")
        return existing[0]
