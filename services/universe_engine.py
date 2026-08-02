from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.free_universe_client import (
    FreeUniverseClient,
    UniverseSourceError,
)


class UniverseEngine:
    def __init__(self, client: FreeUniverseClient) -> None:
        self.client = client

    def discover(
        self,
        *,
        exchanges: List[str],
        include_etfs: bool,
        include_common_stocks: bool,
        limit: int,
        name_contains: str = "",
    ) -> Dict[str, Any]:
        errors: List[str] = []

        try:
            nasdaq_rows = self.client.get_nasdaq_listed()
        except UniverseSourceError as exc:
            nasdaq_rows = []
            errors.append(f"Nasdaq listed: {exc}")

        try:
            other_rows = self.client.get_other_listed()
        except UniverseSourceError as exc:
            other_rows = []
            errors.append(f"Other listed: {exc}")

        try:
            sec_rows = self.client.get_sec_companies()
        except UniverseSourceError as exc:
            sec_rows = []
            errors.append(f"SEC: {exc}")

        sec_map = {
            row["symbol"]: row
            for row in sec_rows
        }
        allowed = {
            self._normalize_exchange(value)
            for value in exchanges
        }
        search_text = name_contains.strip().lower()
        unique: Dict[str, Dict[str, Any]] = {}

        for row in nasdaq_rows + other_rows:
            symbol = row["symbol"]
            exchange = self._normalize_exchange(
                row.get("exchange")
            )
            is_etf = bool(row.get("is_etf"))
            sec = sec_map.get(symbol)

            if allowed and exchange not in allowed:
                continue
            if is_etf and not include_etfs:
                continue
            if not is_etf and not include_common_stocks:
                continue

            # Hisse evreninde SEC CIK kaydı bulunmayan ürünü alma.
            if not is_etf and not sec:
                continue

            company_name = (
                sec.get("company_name")
                if sec else row.get("company_name")
            ) or symbol

            if search_text:
                if search_text not in (
                    f"{symbol} {company_name}".lower()
                ):
                    continue

            unique[symbol] = {
                "symbol": symbol,
                "company_name": company_name,
                "exchange": exchange,
                "country": "US",
                "sector": None,
                "industry": None,
                "market_cap": None,
                "price": None,
                "volume": None,
                "beta": None,
                "is_etf": is_etf,
                "is_actively_trading": True,
                "cik": sec.get("cik") if sec else None,
                "universe_source": (
                    "Nasdaq Trader + SEC"
                    if sec else "Nasdaq Trader"
                ),
                "discovered_at": (
                    datetime.now(timezone.utc).isoformat()
                ),
            }

            if len(unique) >= limit:
                break

        return {
            "source": "Nasdaq Trader + SEC",
            "rows": list(unique.values()),
            "errors": errors,
        }

    @staticmethod
    def _normalize_exchange(value: Optional[str]) -> str:
        text = str(value or "").strip().upper()
        mapping = {
            "NASDAQ": "NASDAQ",
            "NYSE": "NYSE",
            "NEW YORK STOCK EXCHANGE": "NYSE",
            "NYSE AMERICAN": "AMEX",
            "NYSE MKT": "AMEX",
            "AMEX": "AMEX",
            "NYSE ARCA": "ARCA",
            "ARCA": "ARCA",
            "CBOE BZX": "BZX",
            "IEX": "IEX",
        }
        return mapping.get(text, text)
