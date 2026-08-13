from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.wealth_contract import ACCOUNT_TYPE_BROKERAGE


class WealthAccountRepository:
    def __init__(self, client):
        self.client = client
        self.table = "wealth_accounts"

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

    def get_by_id(self, user_id: str, account_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", account_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def create(
        self,
        *,
        user_id: str,
        portfolio_id: str,
        name: str,
        account_type: str = ACCOUNT_TYPE_BROKERAGE,
        currency: str = "USD",
        institution: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "portfolio_id": portfolio_id,
            "name": name.strip(),
            "account_type": account_type.strip().lower(),
            "currency": currency.strip().upper(),
            "institution": institution.strip() if institution else None,
            "is_active": True,
            "updated_at": self._now_iso(),
        }
        response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Hesap oluşturulamadı.")
        return rows[0]
