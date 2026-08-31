"""Canonical Turkish fund unit-price reads.

Production valuation reads the latest accepted FI snapshot only.
Does not call TEFAS, KAP, FMP, or invent a price.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from services.fund_product_contract import PILOT_TEFAS_FUND_CODES
from services.portfolio_intelligence_contract import PriceQuote
from services.turkiye_fund_snapshot_reader import (
    REASON_FI_MISSING,
    REASON_INCOMPATIBLE_FI_VERSION,
    REASON_STALE_FI,
    SnapshotReadError,
    read_fund_intelligence_snapshot,
)
from services.wealth_contract import normalize_symbol
from services.wealth_price_service import normalize_currency

REASON_MISSING_PRICE = "MISSING_CANONICAL_UNIT_PRICE"
PRICE_SOURCE = "canonical_snapshot"
UNIT_PRICE_CURRENCY = "TRY"

FROZEN_CAPTURED_UNIT_PRICES = {
    "AIS": 0.108262,
    "ZPE": 36.063247,
    "IAT": 0.197873,
}


def is_turkiye_fund_holding_identity(symbol: str) -> bool:
    return normalize_symbol(symbol) in PILOT_TEFAS_FUND_CODES


def canonical_unit_price(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price != price or price <= 0:
        return None
    return price


def extract_unit_price_from_fi_row(row: Mapping[str, Any]) -> tuple[Optional[float], Optional[str]]:
    quality = row.get("data_quality")
    if isinstance(quality, str):
        quality = {}
    quality = dict(quality or {})
    payload = dict(row.get("payload") or {}) if isinstance(row.get("payload"), Mapping) else {}
    candidates = (
        quality.get("unit_price"),
        quality.get("nav"),
        quality.get("sonFiyat"),
        payload.get("unit_price"),
        payload.get("nav"),
        row.get("unit_price"),
    )
    price = None
    for raw in candidates:
        price = canonical_unit_price(raw)
        if price is not None:
            break
    as_of = (
        str(quality.get("unit_price_as_of") or "").strip()
        or str((quality.get("source_as_of") or {}).get("tefas_price") or "").strip()
        or str(row.get("as_of_key") or "").strip()
        or None
    )
    return price, as_of


@dataclass(frozen=True)
class TurkiyeFundUnitPrice:
    fund_code: str
    price: Optional[float]
    currency: str = UNIT_PRICE_CURRENCY
    as_of: Optional[str] = None
    source: str = PRICE_SOURCE
    available: bool = False
    error: Optional[str] = None

    def to_quote(self) -> PriceQuote:
        return PriceQuote(
            price=self.price if self.available else None,
            currency=self.currency,
            available=self.available,
            source=self.source,
            error=self.error,
            as_of=self.as_of,
        )


def read_turkiye_fund_unit_price(snapshot_repo: Any, fund_code: str) -> TurkiyeFundUnitPrice:
    code = normalize_symbol(fund_code)
    if code not in PILOT_TEFAS_FUND_CODES:
        return TurkiyeFundUnitPrice(
            fund_code=code,
            price=None,
            available=False,
            error=REASON_MISSING_PRICE,
        )
    try:
        fi = read_fund_intelligence_snapshot(snapshot_repo, code)
    except SnapshotReadError as exc:
        return TurkiyeFundUnitPrice(
            fund_code=code,
            price=None,
            available=False,
            error=exc.reason,
        )
    price, as_of = extract_unit_price_from_fi_row(fi.raw_row)
    if price is None:
        return TurkiyeFundUnitPrice(
            fund_code=code,
            price=None,
            as_of=as_of,
            available=False,
            error=REASON_MISSING_PRICE,
        )
    return TurkiyeFundUnitPrice(
        fund_code=code,
        price=price,
        currency=UNIT_PRICE_CURRENCY,
        as_of=as_of,
        available=True,
    )


def market_value_try(quantity: Any, unit_price: Any) -> Optional[float]:
    qty = canonical_unit_price(quantity)
    price = canonical_unit_price(unit_price)
    if qty is None or price is None:
        return None
    return qty * price


def quote_turkiye_fund_unit_price(
    symbol: str,
    *,
    snapshot_repo: Any = None,
    client: Any = None,
    currency: str = UNIT_PRICE_CURRENCY,
) -> Optional[PriceQuote]:
    """Return a snapshot quote for AIS/ZPE/IAT. None means not a Turkish fund identity."""
    code = normalize_symbol(symbol)
    if code not in PILOT_TEFAS_FUND_CODES:
        return None
    repo = snapshot_repo
    if repo is None and client is not None:
        from repositories.security_intelligence_snapshot_repository import (
            SecurityIntelligenceSnapshotRepository,
        )
        from services.turkiye_fund_snapshot_reader import ReadOnlyRepository

        repo = ReadOnlyRepository(SecurityIntelligenceSnapshotRepository(client))
    if repo is None:
        return TurkiyeFundUnitPrice(
            fund_code=code,
            price=None,
            currency=normalize_currency(currency) or UNIT_PRICE_CURRENCY,
            available=False,
            error=REASON_FI_MISSING,
        ).to_quote()
    return read_turkiye_fund_unit_price(repo, code).to_quote()


__all__ = (
    "FROZEN_CAPTURED_UNIT_PRICES",
    "PRICE_SOURCE",
    "REASON_MISSING_PRICE",
    "REASON_FI_MISSING",
    "REASON_STALE_FI",
    "REASON_INCOMPATIBLE_FI_VERSION",
    "TurkiyeFundUnitPrice",
    "canonical_unit_price",
    "extract_unit_price_from_fi_row",
    "is_turkiye_fund_holding_identity",
    "market_value_try",
    "quote_turkiye_fund_unit_price",
    "read_turkiye_fund_unit_price",
)
