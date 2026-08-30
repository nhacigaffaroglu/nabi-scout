"""Public KAP business-evidence adapter. No Participation. No SI.

Acquires public Bildirim pages / official file metadata and hands official
note text to the extractor. Does not classify Uygun / prohibited.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from services.kap_public_business_contract import (
    PILOT_PUBLIC_BUSINESS_SOURCES,
    SOURCE_TYPE_ACTIVITY_REPORT,
    SOURCE_TYPE_FINANCIAL_REPORT,
    KapPublicBusinessDocument,
)
from services.kap_public_business_parser import (
    observed_segment_taxonomy,
    parse_official_business_notes,
)
from services.kap_public_contract import (
    SOURCE_UNAVAILABLE,
    KapPublicSourceError,
    public_bildirim_url,
)
from services.kap_public_source import DEFAULT_CACHE_DIR


USER_AGENT = "NABI-Scout/BIST-1F (public KAP research; polite read-only)"
DEFAULT_TIMEOUT_SEC = 30


def public_file_download_url(file_id: str) -> str:
    return f"{KAP_PUBLIC_HOST}/tr/api/file/download/{file_id}"


def public_business_source_url(symbol: str) -> dict[str, str]:
    meta = PILOT_PUBLIC_BUSINESS_SOURCES[symbol.upper()]
    return {
        "financial_report": public_bildirim_url(meta["financial_report_id"]),
        "activity_report": public_bildirim_url(meta["activity_report_id"]),
        "official_pdf": public_file_download_url(meta["official_pdf_file_id"]),
        "financial_report_type": SOURCE_TYPE_FINANCIAL_REPORT,
        "activity_report_type": SOURCE_TYPE_ACTIVITY_REPORT,
    }


class KapPublicBusinessSource:
    """Locate public KAP business evidence. Does not evaluate Participation."""

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

    def _note_cache_path(self, disclosure_id: str) -> Path:
        safe = "".join(ch for ch in str(disclosure_id) if ch.isalnum() or ch in {"-", "_"})
        return self.cache_dir / f"{safe}.notes.txt"

    def inspect_financial_html(self, html: str) -> tuple[str, ...]:
        return observed_segment_taxonomy(html)

    def extract_from_official_notes(
        self,
        notes: str,
        *,
        symbol: str,
        disclosure_id: str,
        html: str = "",
        source_url: str = "",
        cached: bool = False,
        period: str = "YTD",
        period_end: Optional[str] = None,
        period_start: Optional[str] = None,
    ) -> KapPublicBusinessDocument:
        return parse_official_business_notes(
            notes,
            symbol=symbol,
            disclosure_id=disclosure_id,
            source_url=source_url or public_bildirim_url(disclosure_id),
            html=html,
            cached=cached,
            period=period,
            period_end=period_end,
            period_start=period_start,
        )

    def fetch_official_notes(
        self,
        disclosure_id: str,
        *,
        symbol: str,
        notes: Optional[str] = None,
        html: str = "",
        period: str = "YTD",
        period_end: Optional[str] = None,
        period_start: Optional[str] = None,
    ) -> KapPublicBusinessDocument:
        if notes is not None:
            return self.extract_from_official_notes(
                notes,
                symbol=symbol,
                disclosure_id=disclosure_id,
                html=html,
                cached=False,
                period=period,
                period_end=period_end,
                period_start=period_start,
            )
        cache_path = self._note_cache_path(disclosure_id)
        if cache_path.is_file():
            return self.extract_from_official_notes(
                cache_path.read_text(encoding="utf-8"),
                symbol=symbol,
                disclosure_id=disclosure_id,
                html=html,
                cached=True,
                period=period,
                period_end=period_end,
                period_start=period_start,
            )
        raise KapPublicSourceError(SOURCE_UNAVAILABLE)
