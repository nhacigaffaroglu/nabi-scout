from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.wealth_adviser_profile_contract import InvestorProfile


class WealthInvestorProfileRepository:
    def __init__(self, client) -> None:
        self.client = client
        self.table = "wealth_investor_profiles"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_for_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def upsert_for_user(
        self,
        *,
        user_id: str,
        profile: InvestorProfile,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "profile_version": profile.profile_version,
            "investment_horizon": profile.investment_horizon,
            "risk_preference": profile.risk_preference,
            "liquidity_need": profile.liquidity_need,
            "cash_preference": profile.cash_preference,
            "concentration_preference": profile.concentration_preference,
            "income_need": profile.income_need,
            "experience_level": profile.experience_level,
            "notes": profile.notes,
            "updated_at": self._now_iso(),
        }
        existing = self.get_for_user(user_id)
        if existing:
            response = (
                self.client.table(self.table)
                .update(payload)
                .eq("user_id", user_id)
                .execute()
            )
        else:
            payload["created_at"] = self._now_iso()
            response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Yatırım profili kaydedilemedi.")
        return rows[0]
