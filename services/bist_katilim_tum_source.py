"""Public Borsa Istanbul Katılım Tüm membership adapter. No paid API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from services.bist_katilim_tum_contract import (
    BORSA_ISTANBUL_HOST,
    LIMITATION_HTTP,
    LIMITATION_NETWORK,
    LIMITATION_STRUCTURE,
    MEMBERSHIP_SOURCE_UNAVAILABLE,
    BistKatilimMembership,
    BistKatilimTumSnapshot,
    BistKatilimTumSourceError,
    borsa_katilim_csv_url,
)
from services.bist_katilim_tum_parser import membership_for_symbol, parse_bist_katilim_csv


DEFAULT_CACHE_DIR = Path(".cache/bist_katilim")
USER_AGENT = "NABI-Scout/BIST-1G (public Borsa research; polite read-only)"
DEFAULT_TIMEOUT_SEC = 30
_CACHE_NAME = "hisse_endeks_katilim_ds.csv"


def _fetch(url: str, *, timeout: int) -> str:
    if not url.startswith(BORSA_ISTANBUL_HOST + "/"):
        raise BistKatilimTumSourceError(LIMITATION_STRUCTURE)
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,*/*"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise BistKatilimTumSourceError(f"{LIMITATION_HTTP}:{status}")
            raw = response.read()
    except HTTPError as exc:
        raise BistKatilimTumSourceError(f"{LIMITATION_HTTP}:{exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise BistKatilimTumSourceError(LIMITATION_NETWORK) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


class BistKatilimTumSource:
    """Locate the official public Katılım Tüm constituent CSV."""

    def __init__(
        self,
        *,
        cache_dir: Optional[Path] = None,
        allow_live: bool = False,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.cache_dir = Path(cache_dir or os.environ.get("NABI_BIST_KATILIM_CACHE", DEFAULT_CACHE_DIR))
        self.allow_live = allow_live
        self.timeout_sec = timeout_sec

    def _cache_path(self) -> Path:
        return self.cache_dir / _CACHE_NAME

    def fetch_snapshot(self, *, csv_text: Optional[str] = None) -> BistKatilimTumSnapshot:
        if csv_text is not None:
            return parse_bist_katilim_csv(csv_text, source_url=borsa_katilim_csv_url())
        cache_path = self._cache_path()
        if cache_path.is_file():
            return parse_bist_katilim_csv(
                cache_path.read_text(encoding="utf-8"),
                source_url=borsa_katilim_csv_url(),
            )
        if not self.allow_live:
            raise BistKatilimTumSourceError(MEMBERSHIP_SOURCE_UNAVAILABLE)
        fetched = _fetch(borsa_katilim_csv_url(), timeout=self.timeout_sec)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(fetched, encoding="utf-8")
        return parse_bist_katilim_csv(fetched, source_url=borsa_katilim_csv_url())

    def membership_for(
        self,
        symbol: str,
        *,
        csv_text: Optional[str] = None,
    ) -> BistKatilimMembership:
        try:
            snapshot = self.fetch_snapshot(csv_text=csv_text)
        except BistKatilimTumSourceError:
            return membership_for_symbol(None, symbol, source_unavailable=True)
        return membership_for_symbol(snapshot, symbol)
