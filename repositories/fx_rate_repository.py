from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional


class FxRateRepository:
    TABLE = "fx_rates"

    def __init__(self, client) -> None:
        self.client = client

    def get_rate(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        on_or_before: Optional[date] = None,
    ) -> Optional[Dict[str, Any]]:
        base = str(base_currency or "").strip().upper()
        quote = str(quote_currency or "").strip().upper()
        if base == quote:
            return {
                "base_currency": base,
                "quote_currency": quote,
                "rate": 1.0,
                "rate_date": (on_or_before or date.today()).isoformat(),
                "source": "identity",
                "data_quality": "good",
            }
        query = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("base_currency", base)
            .eq("quote_currency", quote)
            .order("rate_date", desc=True)
            .limit(1)
        )
        if on_or_before is not None:
            query = query.lte("rate_date", on_or_before.isoformat())
        response = query.execute()
        rows = getattr(response, "data", None)
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        return row if isinstance(row, dict) else None

    def upsert_rate(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        rate: float,
        rate_date: date,
        source: str,
        data_quality: str = "good",
    ) -> Dict[str, Any]:
        payload = {
            "base_currency": base_currency.strip().upper(),
            "quote_currency": quote_currency.strip().upper(),
            "rate": rate,
            "rate_date": rate_date.isoformat(),
            "source": source,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "data_quality": data_quality,
        }
        response = (
            self.client.table(self.TABLE)
            .upsert(payload, on_conflict="base_currency,quote_currency,rate_date")
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else payload

    def list_latest(self, *, base_currency: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("base_currency", base_currency.strip().upper())
            .order("rate_date", desc=True)
            .limit(100)
            .execute()
        )
        return response.data or []
