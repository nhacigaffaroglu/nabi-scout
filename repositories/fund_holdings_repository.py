from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional


class FundHoldingsRepository:
    SNAPSHOTS = "fund_holdings_snapshots"
    HOLDINGS = "fund_holdings"

    def __init__(self, client) -> None:
        self.client = client

    def get_latest_snapshot(self, fund_symbol: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.SNAPSHOTS)
            .select("*")
            .eq("fund_symbol", fund_symbol.strip().upper())
            .order("as_of", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def list_holdings(self, snapshot_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.HOLDINGS)
            .select("*")
            .eq("snapshot_id", snapshot_id)
            .order("weight_pct", desc=True)
            .execute()
        )
        return response.data or []

    def upsert_snapshot(
        self,
        *,
        fund_symbol: str,
        fund_type: str,
        as_of: date,
        source: str,
        coverage_pct: Optional[float],
        underlying_count: Optional[int],
    ) -> Dict[str, Any]:
        payload = {
            "fund_symbol": fund_symbol.strip().upper(),
            "fund_type": fund_type,
            "as_of": as_of.isoformat(),
            "source": source,
            "coverage_pct": coverage_pct,
            "underlying_count": underlying_count,
        }
        response = (
            self.client.table(self.SNAPSHOTS)
            .upsert(payload, on_conflict="fund_symbol,as_of,source")
            .execute()
        )
        rows = response.data or []
        if rows:
            return rows[0]
        existing = self.get_snapshot_for_date(
            fund_symbol=fund_symbol,
            as_of=as_of,
            source=source,
        )
        if existing is None:
            raise RuntimeError("Fund holdings snapshot upsert failed.")
        return existing

    def get_snapshot_for_date(
        self,
        *,
        fund_symbol: str,
        as_of: date,
        source: str,
    ) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.SNAPSHOTS)
            .select("*")
            .eq("fund_symbol", fund_symbol.strip().upper())
            .eq("as_of", as_of.isoformat())
            .eq("source", source)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def replace_holdings(
        self,
        snapshot_id: str,
        holdings: List[Dict[str, Any]],
    ) -> int:
        self.client.table(self.HOLDINGS).delete().eq("snapshot_id", snapshot_id).execute()
        if not holdings:
            return 0
        response = self.client.table(self.HOLDINGS).insert(holdings).execute()
        return len(response.data or [])
