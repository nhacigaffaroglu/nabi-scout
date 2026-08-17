from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from repositories.candidate_repository import CandidateRepository
from services.asset_capability_contract import capability_for_asset_class
from services.candidate_identity import (
    MARKET_ALIASES,
    numeric_current_price,
    select_persisted_price_candidate,
)
from services.portfolio_intelligence_contract import PriceQuote
from services.wealth_price_service import is_cash_asset, normalize_currency

__all__ = (
    "MARKET_ALIASES",
    "CandidatePriceService",
    "numeric_current_price",
    "select_persisted_price_candidate",
)


class CandidatePriceService:
    """Read-only prices from persisted candidate snapshots — no provider calls."""

    PROVIDER_NAME = "candidate_snapshot"

    def __init__(self, client) -> None:
        self._client = client
        self._repo = CandidateRepository(client)
        self._cache: Dict[str, PriceQuote] = {}
        self._fetch_count = 0

    @property
    def fetch_count(self) -> int:
        return self._fetch_count

    def prefetch_assets(
        self,
        assets: Iterable[Tuple[str, str, str]],
    ) -> None:
        seen: set[str] = set()
        for symbol, asset_class, currency in assets:
            if is_cash_asset(symbol, asset_class):
                continue
            sym = str(symbol or "").strip().upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            self.get_quote_for_asset(symbol, asset_class, currency)

    def get_quote_for_asset(
        self,
        symbol: str,
        asset_class: str,
        currency: str,
        *,
        market: Optional[str] = None,
    ) -> PriceQuote:
        if is_cash_asset(symbol, asset_class):
            asset_currency = normalize_currency(currency)
            return PriceQuote(
                price=1.0,
                currency=asset_currency,
                available=True,
                source="nominal_cash",
            )

        profile = capability_for_asset_class(asset_class)
        if profile.pricing_method in {"manual", "unsupported"}:
            return PriceQuote(
                price=None,
                currency=normalize_currency(currency),
                available=False,
                source=self.PROVIDER_NAME,
                error="unsupported_pricing",
            )

        sym = str(symbol or "").strip().upper()
        if sym in self._cache:
            return self._cache[sym]

        self._fetch_count += 1
        listed = (
            self._repo.list_by_symbol(sym)
            if hasattr(self._repo, "list_by_symbol")
            else None
        )
        rows = listed if isinstance(listed, list) else []
        if not rows:
            legacy = self._repo.get_by_symbol(sym)
            rows = [legacy] if isinstance(legacy, dict) else []
        candidate = select_persisted_price_candidate(
            rows,
            preferred_market=market,
        )
        price_raw = numeric_current_price(candidate)
        asset_currency = normalize_currency(
            (candidate or {}).get("currency") or currency
        )
        if price_raw is None:
            quote = PriceQuote(
                price=None,
                currency=asset_currency,
                available=False,
                source=self.PROVIDER_NAME,
                error="missing_price",
            )
        else:
            quote = PriceQuote(
                price=price_raw,
                currency=asset_currency,
                available=True,
                source=self.PROVIDER_NAME,
            )
        self._cache[sym] = quote
        return quote
