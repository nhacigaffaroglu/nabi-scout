from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from services.alpha_vantage_client import (
    STATUS_AUTH,
    STATUS_MALFORMED,
    STATUS_NETWORK,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_PREMIUM_REQUIRED,
    STATUS_RATE_LIMIT,
)

Clock = Callable[[], float]

SUCCESS_ETF_PROFILE_TTL_SECONDS = 3600
SUCCESS_TIME_SERIES_TTL_SECONDS = 900
NEGATIVE_CACHE_TTL_SECONDS = 60

NEGATIVE_CACHE_STATUSES = frozenset({
    STATUS_RATE_LIMIT,
    STATUS_PREMIUM_REQUIRED,
    STATUS_AUTH,
    STATUS_NETWORK,
    STATUS_MALFORMED,
    STATUS_NOT_FOUND,
})


@dataclass(frozen=True)
class AlphaCacheKey:
    symbol: str
    endpoint: str
    params: Tuple[Tuple[str, str], ...]

    @classmethod
    def build(cls, endpoint: str, symbol: str, **params: str) -> "AlphaCacheKey":
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_params = tuple(
            sorted((str(key), str(value)) for key, value in params.items())
        )
        return cls(
            symbol=normalized_symbol,
            endpoint=endpoint,
            params=normalized_params,
        )


@dataclass(frozen=True)
class AlphaCacheEntry:
    payload: Dict[str, Any]
    status: str
    expires_at: float


class AlphaVantageFundCache:
    """Process-local cache for ETF fund Alpha Vantage provider responses."""

    def __init__(
        self,
        *,
        clock: Optional[Clock] = None,
        profile_ttl_seconds: float = SUCCESS_ETF_PROFILE_TTL_SECONDS,
        history_ttl_seconds: float = SUCCESS_TIME_SERIES_TTL_SECONDS,
        negative_ttl_seconds: float = NEGATIVE_CACHE_TTL_SECONDS,
    ) -> None:
        self._clock = clock or time.monotonic
        self._profile_ttl_seconds = profile_ttl_seconds
        self._history_ttl_seconds = history_ttl_seconds
        self._negative_ttl_seconds = negative_ttl_seconds
        self._entries: Dict[AlphaCacheKey, AlphaCacheEntry] = {}

    def get(
        self,
        endpoint: str,
        symbol: str,
        **params: str,
    ) -> Optional[AlphaCacheEntry]:
        key = AlphaCacheKey.build(endpoint, symbol, **params)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            del self._entries[key]
            return None
        return entry

    def set(
        self,
        endpoint: str,
        symbol: str,
        payload: Dict[str, Any],
        status: str,
        **params: str,
    ) -> None:
        ttl = self._ttl_for(endpoint, status)
        if ttl is None:
            return
        key = AlphaCacheKey.build(endpoint, symbol, **params)
        self._entries[key] = AlphaCacheEntry(
            payload=dict(payload),
            status=status,
            expires_at=self._clock() + ttl,
        )

    def clear(self) -> None:
        self._entries.clear()

    def _ttl_for(self, endpoint: str, status: str) -> Optional[float]:
        if status == STATUS_OK:
            if endpoint == "etf_profile":
                return self._profile_ttl_seconds
            if endpoint == "time_series_daily":
                return self._history_ttl_seconds
            return self._profile_ttl_seconds
        if status in NEGATIVE_CACHE_STATUSES:
            return self._negative_ttl_seconds
        return None


_default_cache: Optional[AlphaVantageFundCache] = None


def get_fund_cache() -> AlphaVantageFundCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = AlphaVantageFundCache()
    return _default_cache


def reset_fund_cache() -> None:
    global _default_cache
    if _default_cache is not None:
        _default_cache.clear()
    _default_cache = None
