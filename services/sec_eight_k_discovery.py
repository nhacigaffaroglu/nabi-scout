"""Discover recent SEC 8-K filings from existing submissions JSON.

Reuses SECFinancialClient.company_submissions and filing URL helpers.
Does not download filing HTML. Does not infer items from headlines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

from services.sec_eight_k_taxonomy import COMPANION_ITEMS
from services.sec_primary_filing_resolver import build_filing_url


_EIGHT_K_FORMS = frozenset({"8-K", "8-K/A"})
_ITEM_RE = re.compile(r"^\d+\.\d{2}$")


@dataclass(frozen=True)
class SecEightKFiling:
    symbol: str
    cik: str
    form: str
    accession: str
    filing_date: str
    acceptance_at: Optional[str]
    primary_document: str
    filing_url: str
    items: tuple[str, ...]
    items_raw: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "cik": self.cik,
            "form": self.form,
            "accession": self.accession,
            "filing_date": self.filing_date,
            "acceptance_at": self.acceptance_at,
            "primary_document": self.primary_document,
            "filing_url": self.filing_url,
            "items": list(self.items),
            "items_raw": self.items_raw,
        }


def parse_sec_8k_items(raw: Optional[str]) -> tuple[str, ...]:
    """Accept only well-formed SEC item numbers from the submissions items field."""
    text = str(raw or "").strip()
    if not text:
        return ()
    found: list[str] = []
    for part in text.replace(";", ",").split(","):
        token = part.strip()
        lowered = token.lower()
        if lowered.startswith("item "):
            token = token[5:].strip()
        if _ITEM_RE.match(token) and token not in found:
            found.append(token)
    return tuple(found)


def logical_items(items: Sequence[str]) -> tuple[str, ...]:
    return tuple(item for item in items if item not in COMPANION_ITEMS)


def _iter_recent_rows(submissions: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    recent = submissions.get("filings", {}).get("recent") or {}
    forms = recent.get("form") or []
    if not forms:
        return ()
    keys = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "primaryDocument",
        "form",
        "items",
    )
    rows = []
    for index in range(len(forms)):
        rows.append({key: (recent.get(key) or [None] * len(forms))[index] for key in keys})
    return tuple(rows)


def _parse_filing_date(value: Optional[str]) -> Optional[date]:
    text = str(value or "").strip()[:10]
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def discover_recent_8k_filings(
    submissions: Mapping[str, Any],
    *,
    symbol: str,
    cik: str,
    lookback_days: int = 90,
    max_filings: int = 20,
    as_of: Optional[date] = None,
) -> tuple[SecEightKFiling, ...]:
    today = as_of or datetime.now(timezone.utc).date()
    start = today - timedelta(days=max(1, int(lookback_days)))
    out: list[SecEightKFiling] = []
    for row in _iter_recent_rows(submissions):
        form = str(row.get("form") or "").strip()
        if form not in _EIGHT_K_FORMS:
            continue
        accession = str(row.get("accessionNumber") or "").strip()
        filing_date = str(row.get("filingDate") or "").strip()
        primary = str(row.get("primaryDocument") or "").strip()
        parsed = _parse_filing_date(filing_date)
        if not accession or not filing_date or parsed is None:
            continue
        if parsed < start or parsed > today:
            continue
        items_raw = str(row.get("items") or "").strip() or None
        acceptance = str(row.get("acceptanceDateTime") or "").strip() or None
        out.append(
            SecEightKFiling(
                symbol=str(symbol or "").strip().upper(),
                cik=str(cik).strip().lstrip("0") or "0",
                form=form,
                accession=accession,
                filing_date=filing_date,
                acceptance_at=acceptance,
                primary_document=primary,
                filing_url=build_filing_url(
                    cik=cik,
                    accession=accession,
                    primary_document=primary,
                )
                if primary
                else f"https://www.sec.gov/Archives/edgar/data/{str(cik).strip().lstrip('0') or '0'}/{accession.replace('-', '')}/",
                items=parse_sec_8k_items(items_raw),
                items_raw=items_raw,
            )
        )
    out.sort(key=lambda item: item.filing_date, reverse=True)
    return tuple(out[: max(1, int(max_filings))])
