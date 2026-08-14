from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class WealthAdviserGoalRepository:
    def __init__(self, client) -> None:
        self.client = client
        self.table = "wealth_adviser_goals"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_active_for_user(
        self,
        user_id: str,
        *,
        portfolio_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("active", True)
            .order("priority")
            .order("created_at")
        )
        if portfolio_id:
            query = query.or_(f"portfolio_id.is.null,portfolio_id.eq.{portfolio_id}")
        response = query.execute()
        return response.data or []

    def create(
        self,
        *,
        user_id: str,
        portfolio_id: Optional[str],
        goal_type: str,
        title: str,
        target_date: Optional[str] = None,
        target_amount: Optional[float] = None,
        currency: Optional[str] = None,
        priority: int = 1,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "portfolio_id": portfolio_id,
            "goal_type": goal_type.strip().upper(),
            "title": title.strip(),
            "target_date": target_date,
            "target_amount": target_amount,
            "currency": currency.strip().upper() if currency else None,
            "priority": priority,
            "notes": notes,
            "active": True,
            "updated_at": self._now_iso(),
        }
        response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Hedef oluşturulamadı.")
        return rows[0]

    def update(
        self,
        *,
        user_id: str,
        goal_id: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = dict(updates)
        payload["updated_at"] = self._now_iso()
        response = (
            self.client.table(self.table)
            .update(payload)
            .eq("user_id", user_id)
            .eq("id", goal_id)
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise RuntimeError("Hedef güncellenemedi.")
        return rows[0]

    def archive(self, *, user_id: str, goal_id: str) -> Dict[str, Any]:
        return self.update(user_id=user_id, goal_id=goal_id, updates={"active": False})

    def get_for_user(self, *, user_id: str, goal_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", goal_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None
