"""Public KAP KAFİF adapter. No paid API. No auth bypass."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from services.kap_kafif_contract import (
    KAFIF_FORM_TITLE,
    LIMITATION_HTTP,
    LIMITATION_NETWORK,
    LIMITATION_NOT_FOUND,
    LIMITATION_STRUCTURE,
    SOURCE_UNAVAILABLE,
    KapKafifDiscovery,
    KapKafifDocument,
    KapKafifSourceError,
    kafif_bildirim_url,
)
from services.kap_kafif_parser import (
    latest_kafif_discovery,
    parse_kafif_disclosure_index,
    parse_public_kafif_html,
)
from services.kap_public_contract import KAP_PUBLIC_HOST


DEFAULT_CACHE_DIR = Path(".cache/kap_kafif")
USER_AGENT = "NABI-Scout/BIST-1G (public KAP KAFIF research; polite read-only)"
DEFAULT_TIMEOUT_SEC = 30


def _cache_path(cache_dir: Path, name: str) -> Path:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_"})
    return cache_dir / f"{safe}.html"


def _fetch(url: str, *, timeout: int) -> str:
    if not url.startswith(KAP_PUBLIC_HOST + "/tr/"):
        raise KapKafifSourceError(LIMITATION_STRUCTURE)
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status == 404:
                raise KapKafifSourceError(LIMITATION_NOT_FOUND)
            if status >= 400:
                raise KapKafifSourceError(f"{LIMITATION_HTTP}:{status}")
            raw = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            raise KapKafifSourceError(LIMITATION_NOT_FOUND) from exc
        raise KapKafifSourceError(f"{LIMITATION_HTTP}:{exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise KapKafifSourceError(LIMITATION_NETWORK) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


class KapKafifSource:
    """Locate/read a public KAP KAFİF Bildirim. Latest notification only."""

    def __init__(
        self,
        *,
        cache_dir: Optional[Path] = None,
        allow_live: bool = False,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.cache_dir = Path(cache_dir or os.environ.get("NABI_KAP_KAFIF_CACHE", DEFAULT_CACHE_DIR))
        self.allow_live = allow_live
        self.timeout_sec = timeout_sec

    def discover_from_member_html(self, html: str) -> Optional[KapKafifDiscovery]:
        return latest_kafif_discovery(parse_kafif_disclosure_index(html))

    def fetch_form(
        self,
        disclosure_id: str,
        *,
        symbol: str,
        html: Optional[str] = None,
    ) -> KapKafifDocument:
        if html is not None:
            return parse_public_kafif_html(
                html,
                symbol=symbol,
                disclosure_id=disclosure_id,
                source_url=kafif_bildirim_url(disclosure_id),
            )
        cache_path = _cache_path(self.cache_dir, disclosure_id)
        if cache_path.is_file():
            return parse_public_kafif_html(
                cache_path.read_text(encoding="utf-8"),
                symbol=symbol,
                disclosure_id=disclosure_id,
                source_url=kafif_bildirim_url(disclosure_id),
            )
        if not self.allow_live:
            raise KapKafifSourceError(SOURCE_UNAVAILABLE)
        url = kafif_bildirim_url(disclosure_id)
        fetched = _fetch(url, timeout=self.timeout_sec)
        if KAFIF_FORM_TITLE not in fetched and "tbl_KFIF-General-Info-Form" not in fetched:
            raise KapKafifSourceError(LIMITATION_STRUCTURE)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(fetched, encoding="utf-8")
        return parse_public_kafif_html(
            fetched,
            symbol=symbol,
            disclosure_id=disclosure_id,
            source_url=url,
        )
