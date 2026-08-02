from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.fmp_client import FMPError


class UniverseEngine:
    def __init__(self, fmp_client) -> None:
        self.client = fmp_client

    def _raw_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None):
        return self.client._get(endpoint, params or {})

    def discover_with_screener(
        self,
        *,
        exchanges: List[str],
        country: str,
        min_market_cap: float,
        min_price: float,
        min_volume: float,
        limit: int,
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []

        for exchange in exchanges:
            params = {
                "exchange": exchange,
                "country": country,
                "marketCapMoreThan": int(min_market_cap),
                "priceMoreThan": float(min_price),
                "volumeMoreThan": int(min_volume),
                "isActivelyTrading": "true",
                "isEtf": "false",
                "limit": int(limit),
            }
            batch = self._raw_get("company-screener", params)
            if batch:
                rows.extend(batch)

        return self._normalize_and_dedupe(rows)

    def discover_with_stock_list(
        self,
        *,
        exchanges: List[str],
        min_price: float,
        limit: int,
    ) -> List[Dict[str, Any]]:
        rows = self._raw_get("stock-list")
        allowed = {item.upper() for item in exchanges}
        filtered: List[Dict[str, Any]] = []

        for row in rows:
            exchange = str(
                row.get("exchangeShortName")
                or row.get("exchange")
                or ""
            ).upper()
            symbol = str(row.get("symbol") or "").strip().upper()
            price = self._number(row.get("price"))

            if not symbol:
                continue
            if allowed and exchange not in allowed:
                continue
            if price is not None and price < min_price:
                continue

            filtered.append(row)
            if len(filtered) >= limit:
                break

        return self._normalize_and_dedupe(filtered)

    def discover(
        self,
        *,
        exchanges: List[str],
        country: str = "US",
        min_market_cap: float = 2_000_000_000,
        min_price: float = 5,
        min_volume: float = 500_000,
        limit: int = 100,
    ) -> Dict[str, Any]:
        errors: List[str] = []
        source = "company-screener"

        try:
            rows = self.discover_with_screener(
                exchanges=exchanges,
                country=country,
                min_market_cap=min_market_cap,
                min_price=min_price,
                min_volume=min_volume,
                limit=limit,
            )
        except Exception as exc:
            errors.append(f"company-screener: {exc}")
            rows = []

        if not rows:
            source = "stock-list"
            try:
                rows = self.discover_with_stock_list(
                    exchanges=exchanges,
                    min_price=min_price,
                    limit=limit,
                )
            except Exception as exc:
                errors.append(f"stock-list: {exc}")
                rows = []

        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            row["universe_source"] = source
            row["discovered_at"] = now

        return {
            "source": source,
            "rows": rows,
            "errors": errors,
        }

    def _normalize_and_dedupe(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        unique: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue

            exchange = (
                row.get("exchangeShortName")
                or row.get("exchange")
            )

            unique[symbol] = {
                "symbol": symbol,
                "company_name": (
                    row.get("companyName")
                    or row.get("name")
                    or symbol
                ),
                "exchange": exchange,
                "country": row.get("country"),
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "market_cap": self._number(
                    row.get("marketCap")
                    or row.get("marketCapitalization")
                ),
                "price": self._number(row.get("price")),
                "volume": self._number(
                    row.get("volume")
                    or row.get("avgVolume")
                ),
                "beta": self._number(row.get("beta")),
                "is_etf": bool(row.get("isEtf", False)),
                "is_actively_trading": row.get(
                    "isActivelyTrading", True
                ),
            }

        return list(unique.values())

    @staticmethod
    def _number(value):
        try:
            return None if value in (None, "") else float(value)
        except (TypeError, ValueError):
            return None
