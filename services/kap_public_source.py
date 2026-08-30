"""Read a public KAP financial-report page. No paid API. No auth bypass.

Fetches only publicly reachable /tr/Bildirim/{id} pages and caches raw HTML
locally. Does not normalize facts or produce Participation verdicts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from services.kap_public_contract import (
    KAP_PUBLIC_HOST,
    LIMITATION_HTTP,
    LIMITATION_NETWORK,
    LIMITATION_NOT_FOUND,
    LIMITATION_STRUCTURE,
    PUBLIC_DOWNLOAD_AVAILABLE,
    PUBLIC_PAGE_AVAILABLE,
    PUBLIC_STRUCTURED_DATA_AVAILABLE,
    SOURCE_PUBLIC_KAP,
    SOURCE_UNAVAILABLE,
    KapPublicAccessStatus,
    KapPublicFinancialDocument,
    KapPublicSourceError,
    public_bildirim_url,
)
from services.kap_public_parser import parse_public_kap_html


DEFAULT_CACHE_DIR = Path(".cache/kap_public")
USER_AGENT = "NABI-Scout/BIST-1E (public KAP research; polite read-only)"
DEFAULT_TIMEOUT_SEC = 30


def resolve_public_kap_access() -> KapPublicAccessStatus:
    return KapPublicAccessStatus(
        page_access=PUBLIC_PAGE_AVAILABLE,
        download_access=PUBLIC_DOWNLOAD_AVAILABLE,
        structured_taxonomy=PUBLIC_STRUCTURED_DATA_AVAILABLE,
        authentication_required=False,
        paid_service_used=False,
        limitation=(
            "Public KAP Bildirim pages expose ifrs-full_* / kap-fr_* taxonomy. "
            "On-page Excel/Word/PDF export is public but Excel is label-only. "
            "Paid KAP Veri Yayın Servisi is not used."
        ),
    )


def _cache_path(disclosure_id: str, cache_dir: Path) -> Path:
    safe = "".join(ch for ch in str(disclosure_id) if ch.isalnum() or ch in {"-", "_"})
    return cache_dir / f"{safe}.html"


def _read_cache(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _write_cache(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _fetch(url: str, *, timeout: int = DEFAULT_TIMEOUT_SEC) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status == 404:
                raise KapPublicSourceError(LIMITATION_NOT_FOUND)
            if status >= 400:
                raise KapPublicSourceError(f"{LIMITATION_HTTP}:{status}")
            raw = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            raise KapPublicSourceError(LIMITATION_NOT_FOUND) from exc
        raise KapPublicSourceError(f"{LIMITATION_HTTP}:{exc.code}") from exc
    except URLError as exc:
        raise KapPublicSourceError(LIMITATION_NETWORK) from exc
    except TimeoutError as exc:
        raise KapPublicSourceError(LIMITATION_NETWORK) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


class KapPublicFinancialSource:
    """Locate/read a public KAP financial report. No normalization."""

    def __init__(
        self,
        *,
        cache_dir: Optional[Path] = None,
        allow_live: bool = False,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.cache_dir = Path(cache_dir or os.environ.get("NABI_KAP_PUBLIC_CACHE", DEFAULT_CACHE_DIR))
        self.allow_live = allow_live
        self.timeout_sec = timeout_sec

    def fetch_report(
        self,
        disclosure_id: str,
        *,
        symbol: str,
        html: Optional[str] = None,
        include_comparative: bool = False,
    ) -> KapPublicFinancialDocument:
        if html is not None:
            return parse_public_kap_html(
                html,
                symbol=symbol,
                disclosure_id=disclosure_id,
                source_url=public_bildirim_url(disclosure_id),
                cached=False,
                include_comparative=include_comparative,
            )
        cache_path = _cache_path(disclosure_id, self.cache_dir)
        cached = _read_cache(cache_path)
        if cached:
            return parse_public_kap_html(
                cached,
                symbol=symbol,
                disclosure_id=disclosure_id,
                source_url=public_bildirim_url(disclosure_id),
                cached=True,
                include_comparative=include_comparative,
            )
        if not self.allow_live:
            raise KapPublicSourceError(SOURCE_UNAVAILABLE)
        url = public_bildirim_url(disclosure_id)
        if not url.startswith(KAP_PUBLIC_HOST + "/tr/Bildirim/"):
            raise KapPublicSourceError(LIMITATION_STRUCTURE)
        fetched = _fetch(url, timeout=self.timeout_sec)
        if "taxonomy-field-name" not in fetched and "ifrs-full_" not in fetched:
            raise KapPublicSourceError(LIMITATION_STRUCTURE)
        _write_cache(cache_path, fetched)
        return parse_public_kap_html(
            fetched,
            symbol=symbol,
            disclosure_id=disclosure_id,
            source_url=url,
            cached=False,
            include_comparative=include_comparative,
        )

    def discover_from_search_html(
        self,
        html: str,
        *,
        annual_only: bool = True,
    ):
        from services.kap_public_fr_discovery import (
            annual_fr_discoveries,
            parse_fr_disclosure_index,
        )

        rows = parse_fr_disclosure_index(html)
        return annual_fr_discoveries(rows) if annual_only else rows
