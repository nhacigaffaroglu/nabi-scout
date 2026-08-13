from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.wealth_contract import normalize_market, normalize_symbol


class WealthAssetRepository:
    def __init__(self, client):
        self.client = client
        self.table = "wealth_assets"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .order("symbol")
            .execute()
        )
        return response.data or []

    def get_by_id(self, user_id: str, asset_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", asset_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def find_by_identity(
        self,
        user_id: str,
        *,
        symbol: str,
        market: str,
        asset_class: str,
    ) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("symbol", normalize_symbol(symbol))
            .eq("market", normalize_market(market))
            .eq("asset_class", asset_class.strip().lower())
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def create(
        self,
        *,
        user_id: str,
        symbol: str,
        market: str,
        asset_class: str,
        currency: str = "USD",
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "symbol": normalize_symbol(symbol),
            "market": normalize_market(market),
            "asset_class": asset_class.strip().lower(),
            "currency": currency.strip().upper(),
            "name": name.strip() if name else None,
            "updated_at": self._now_iso(),
        }
        response = self.client.table(self.table).insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise RuntimeError("Varlık oluşturulamadı.")
        return rows[0]
