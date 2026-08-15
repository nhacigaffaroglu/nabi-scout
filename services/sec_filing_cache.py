from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

Clock = Callable[[], float]

DEFAULT_FILING_HTML_TTL_SECONDS = 86_400
DEFAULT_ATTRIBUTION_TTL_SECONDS = 86_400


@dataclass(frozen=True)
class FilingCacheKey:
    cik: str
    accession: str
    primary_document: str

    @classmethod
    def build(cls, *, cik: str, accession: str, primary_document: str) -> "FilingCacheKey":
        return cls(
            cik=str(cik or "").strip().lstrip("0") or "0",
            accession=str(accession or "").strip(),
            primary_document=str(primary_document or "").strip(),
        )


@dataclass(frozen=True)
class AttributionCacheKey:
    cik: str
    accession: str
    methodology_version: str

    @classmethod
    def build(
        cls,
        *,
        cik: str,
        accession: str,
        methodology_version: str,
    ) -> "AttributionCacheKey":
        return cls(
            cik=str(cik or "").strip().lstrip("0") or "0",
            accession=str(accession or "").strip(),
            methodology_version=str(methodology_version or "").strip(),
        )


@dataclass
class _CacheEntry:
    payload: Any
    expires_at: float


class SECFilingCache:
    """Process-local cache for SEC filing HTML and parsed attribution results."""

    def __init__(
        self,
        *,
        clock: Optional[Clock] = None,
        filing_html_ttl_seconds: float = DEFAULT_FILING_HTML_TTL_SECONDS,
        attribution_ttl_seconds: float = DEFAULT_ATTRIBUTION_TTL_SECONDS,
    ) -> None:
        self._clock = clock or time.monotonic
        self._filing_html_ttl_seconds = filing_html_ttl_seconds
        self._attribution_ttl_seconds = attribution_ttl_seconds
        self._filing_html: Dict[FilingCacheKey, _CacheEntry] = {}
        self._attribution: Dict[AttributionCacheKey, _CacheEntry] = {}

    def get_filing_html(self, key: FilingCacheKey) -> Optional[bytes]:
        entry = self._filing_html.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._filing_html.pop(key, None)
            return None
        return entry.payload

    def set_filing_html(self, key: FilingCacheKey, content: bytes) -> None:
        self._filing_html[key] = _CacheEntry(
            payload=content,
            expires_at=self._clock() + self._filing_html_ttl_seconds,
        )

    def get_attribution(self, key: AttributionCacheKey) -> Optional[Any]:
        entry = self._attribution.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._attribution.pop(key, None)
            return None
        return entry.payload

    def set_attribution(self, key: AttributionCacheKey, payload: Any) -> None:
        self._attribution[key] = _CacheEntry(
            payload=payload,
            expires_at=self._clock() + self._attribution_ttl_seconds,
        )


_GLOBAL_FILING_CACHE: Optional[SECFilingCache] = None


def get_sec_filing_cache() -> SECFilingCache:
    global _GLOBAL_FILING_CACHE
    if _GLOBAL_FILING_CACHE is None:
        _GLOBAL_FILING_CACHE = SECFilingCache()
    return _GLOBAL_FILING_CACHE
