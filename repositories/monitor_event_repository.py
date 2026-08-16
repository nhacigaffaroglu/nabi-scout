from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class MonitorEventRepository:
    TABLE = "monitor_events"

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def upsert_draft(self, row: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        try:
            response = self.client.table(self.TABLE).insert(row).execute()
            data = response.data or []
            return (data[0] if data else row), True
        except Exception as exc:
            message = str(exc).lower()
            if "duplicate" not in message and "unique" not in message and "23505" not in message:
                raise
            existing = self.get_by_dedupe_key(str(row.get("dedupe_key") or ""))
            if existing is None:
                raise
            return existing, False

    def get_by_dedupe_key(self, dedupe_key: str) -> Optional[Dict[str, Any]]:
        key = str(dedupe_key or "").strip()
        if not key:
            return None
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("dedupe_key", key)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def list_recent(
        self,
        *,
        user_id: Optional[str] = None,
        portfolio_id: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = self.client.table(self.TABLE).select("*").order("detected_at", desc=True)
        if user_id:
            query = query.or_(f"user_id.is.null,user_id.eq.{user_id}")
        if portfolio_id:
            query = query.or_(f"portfolio_id.is.null,portfolio_id.eq.{portfolio_id}")
        if symbols:
            normalized = [str(sym).upper() for sym in symbols if sym]
            if normalized:
                query = query.in_("symbol", normalized)
        response = query.limit(max(1, min(limit, 250))).execute()
        return response.data or []

    def list_for_symbol(self, symbol: str, *, limit: int = 20) -> List[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return []
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .order("detected_at", desc=True)
            .limit(max(1, min(limit, 50)))
            .execute()
        )
        return response.data or []
