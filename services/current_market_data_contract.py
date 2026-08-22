from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


PROVIDER_FMP = "FMP"
PROVIDER_ALPHA_VANTAGE = "ALPHA_VANTAGE"
PROVIDER_TWELVE_DATA = "TWELVE_DATA"
PROVIDER_BORSA_ISTANBUL_EOD = "BORSA_ISTANBUL_EOD"


class ProviderFailureClass(str, Enum):
    PLAN_RESTRICTED = "plan_restricted"
    UNSUPPORTED_SYMBOL = "unsupported_symbol"
    ENDPOINT_UNAVAILABLE = "endpoint_unavailable"
    PROVIDER_ACCESS_FAILURE = "provider_access_failure"
    MALFORMED_PRICE = "malformed_price"
    CURRENCY_MISMATCH = "currency_mismatch"
    INVALID_SYMBOL_MAPPING = "invalid_symbol_mapping"


FALLBACK_ELIGIBLE = frozenset(
    {
        ProviderFailureClass.PLAN_RESTRICTED,
        ProviderFailureClass.UNSUPPORTED_SYMBOL,
        ProviderFailureClass.ENDPOINT_UNAVAILABLE,
        ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
    }
)

INTEGRITY_FAILURES = frozenset(
    {
        ProviderFailureClass.MALFORMED_PRICE,
        ProviderFailureClass.CURRENCY_MISMATCH,
        ProviderFailureClass.INVALID_SYMBOL_MAPPING,
    }
)


def is_fallback_eligible(failure: Optional[ProviderFailureClass]) -> bool:
    return failure in FALLBACK_ELIGIBLE


@dataclass(frozen=True)
class EquityQuoteResult:
    ok: bool
    canonical_symbol: str
    provider: str
    provider_symbol: str
    price: Optional[float]
    currency: Optional[str]
    as_of: Optional[str]
    retrieved_at: str
    exchange: Optional[str] = None
    failure_class: Optional[ProviderFailureClass] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class FxRateResult:
    ok: bool
    base_currency: str
    quote_currency: str
    rate: Optional[float]
    provider: str
    as_of: Optional[str]
    retrieved_at: str
    inverted: bool = False
    failure_class: Optional[ProviderFailureClass] = None
    error: Optional[str] = None


def persistence_source(provider: str) -> str:
    if provider == PROVIDER_FMP:
        return "fmp_quote"
    if provider == PROVIDER_ALPHA_VANTAGE:
        return "alpha_vantage"
    if provider == PROVIDER_TWELVE_DATA:
        return "TWELVE_DATA"
    if provider == PROVIDER_BORSA_ISTANBUL_EOD:
        return "BORSA_ISTANBUL_EOD"
    return str(provider or "unknown").strip().lower() or "unknown"
