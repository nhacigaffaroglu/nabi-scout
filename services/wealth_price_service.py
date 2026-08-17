from __future__ import annotations

from typing import Dict, Iterable, Tuple

from services.fmp_client import FMPError
from services.portfolio_intelligence_contract import PriceQuote
from services.wealth_contract import ASSET_CLASS_CASH, CASH_SYMBOL, normalize_symbol


def is_cash_asset(symbol: str, asset_class: str) -> bool:
    return (
        str(asset_class or "").strip().lower() == ASSET_CLASS_CASH
        or normalize_symbol(symbol) == CASH_SYMBOL
    )


# Domain storage/FX code is ISO TRY. Live Wealth rows may still say TL.
CURRENCY_ALIASES = {"TL": "TRY"}


def normalize_currency(code: str | None) -> str:
    raw = str(code or "USD").strip().upper()
    return CURRENCY_ALIASES.get(raw, raw)


class WealthPriceService:
    """Read-only market price boundary for Wealth valuation.

    Cash assets use nominal 1.0 in their own currency. Missing prices are
    explicitly unavailable — never coerced to zero.
    """

    PROVIDER_NAME = "fmp"

    def __init__(self, fmp_client=None) -> None:
        self._fmp = fmp_client
        self._cache: Dict[str, PriceQuote] = {}
        self._fetch_count = 0

    @property
    def fetch_count(self) -> int:
        return self._fetch_count

    def prefetch_assets(
        self,
        assets: Iterable[Tuple[str, str, str]],
    ) -> None:
        """Warm cache for unique non-cash symbols: (symbol, asset_class, currency)."""
        seen: set[str] = set()
        for symbol, asset_class, currency in assets:
            if is_cash_asset(symbol, asset_class):
                continue
            sym = normalize_symbol(symbol)
            if not sym or sym in seen:
                continue
            seen.add(sym)
            self.get_quote_for_asset(symbol, asset_class, currency)

    def get_quote_for_asset(
        self,
        symbol: str,
        asset_class: str,
        currency: str,
    ) -> PriceQuote:
        if is_cash_asset(symbol, asset_class):
            asset_currency = normalize_currency(currency)
            return PriceQuote(
                price=1.0,
                currency=asset_currency,
                available=True,
                source="nominal_cash",
            )

        sym = normalize_symbol(symbol)
        if sym in self._cache:
            return self._cache[sym]

        if self._fmp is None:
            quote = PriceQuote(
                price=None,
                currency=None,
                available=False,
                source="none",
                error="price_provider_unavailable",
            )
            self._cache[sym] = quote
            return quote

        self._fetch_count += 1
        try:
            row = self._fmp.quote(sym)
            price_raw = row.get("price") if row else None
            if price_raw is None:
                quote = PriceQuote(
                    price=None,
                    currency=None,
                    available=False,
                    source=self.PROVIDER_NAME,
                    error="missing_price",
                )
            else:
                quote = PriceQuote(
                    price=float(price_raw),
                    currency=normalize_currency(row.get("currency") or currency),
                    available=True,
                    source=self.PROVIDER_NAME,
                )
        except FMPError as exc:
            quote = PriceQuote(
                price=None,
                currency=None,
                available=False,
                source=self.PROVIDER_NAME,
                error=str(exc),
            )

        self._cache[sym] = quote
        return quote
