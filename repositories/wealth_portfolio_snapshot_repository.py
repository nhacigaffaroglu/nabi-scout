from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional


class WealthPortfolioSnapshotRepository:
    def __init__(self, client):
        self.client = client
        self.table = "wealth_portfolio_snapshots"

    @staticmethod
    def utc_date_from_captured_at(captured_at: str) -> date:
        normalized = str(captured_at or "").strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date()

    def find_for_portfolio_on_date(
        self,
        user_id: str,
        portfolio_id: str,
        snapshot_date: date,
    ) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .eq("snapshot_date", snapshot_date.isoformat())
            .order("captured_at", desc=True)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if rows:
            return rows[0]
        # Pre-migration fallback: derive UTC date from captured_at when snapshot_date unset.
        for row in self.list_for_portfolio(user_id, portfolio_id, limit=100):
            captured = str(row.get("captured_at") or "")
            if not captured:
                continue
            if self.utc_date_from_captured_at(captured) == snapshot_date:
                return row
        return None

    def upsert_for_portfolio_date(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        response = (
            self.client.table(self.table)
            .upsert(payload, on_conflict="portfolio_id,snapshot_date")
            .execute()
        )
        rows = response.data or []
        if rows:
            return rows[0]
        portfolio_id = str(payload.get("portfolio_id") or "")
        snapshot_date = payload.get("snapshot_date")
        if portfolio_id and snapshot_date:
            existing = (
                self.client.table(self.table)
                .select("*")
                .eq("portfolio_id", portfolio_id)
                .eq("snapshot_date", snapshot_date)
                .limit(1)
                .execute()
            )
            rows = existing.data or []
            if rows:
                return rows[0]
        raise RuntimeError("Portföy görüntüsü kaydedilemedi.")

    def insert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Portföy görüntüsü kaydedilemedi.")
        return rows[0]

    def list_for_portfolio(
        self,
        user_id: str,
        portfolio_id: str,
        *,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .order("captured_at", desc=True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or []
