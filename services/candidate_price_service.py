from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from repositories.candidate_repository import CandidateRepository
from services.asset_capability_contract import capability_for_asset_class
from services.bist_symbol_mapping import normalize_bist_symbol
from services.candidate_identity import (
    MARKET_ALIASES,
    numeric_current_price,
    select_persisted_price_candidate,
)
from services.portfolio_intelligence_contract import PriceQuote
from services.turkiye_fund_price_reader import (
    is_turkiye_fund_holding_identity,
    quote_turkiye_fund_unit_price,
)
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
            if is_cash_asset(symbol, asset_class) and not is_turkiye_fund_holding_identity(
                symbol, instrument=asset_class, market=None
            ):
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
        turkish = quote_turkiye_fund_unit_price(
            symbol,
            client=self._client,
            currency=currency,
            instrument=asset_class,
            market=market,
        )
        if turkish is not None:
            canonical = str(symbol or "").strip().upper()
            self._cache[canonical] = turkish
            return turkish

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

        canonical = normalize_bist_symbol(symbol)
        sym = canonical or str(symbol or "").strip().upper()
        preferred_market = market or ("TR" if canonical else market)
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
            preferred_market=preferred_market,
        )
        price_raw = numeric_current_price(candidate)
        asset_currency = normalize_currency(
            (candidate or {}).get("currency") or currency
        )
        as_of = str((candidate or {}).get("source_updated_at") or "").strip() or None
        if price_raw is None:
            quote = PriceQuote(
                price=None,
                currency=asset_currency,
                available=False,
                source=self.PROVIDER_NAME,
                error="missing_price",
                as_of=as_of,
            )
        else:
            quote = PriceQuote(
                price=price_raw,
                currency=asset_currency,
                available=True,
                source=self.PROVIDER_NAME,
                as_of=as_of,
            )
        self._cache[sym] = quote
        return quote
