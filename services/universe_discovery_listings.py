"""General U.S. equity discovery candidates from injected listing rows.

Preferred source shape matches Nasdaq Trader + SEC (FreeUniverseClient /
UniverseEngine). This module never fetches. Typical filtered size is several
thousand ordinary listed commons — not the static ~116 seed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from services.universe_listing_identity import (
    US_EQUITY_DISCOVERY_SOURCE,
    excluded_instrument_reason,
    listing_identity,
    listing_priority,
    normalize_us_exchange,
)


@dataclass(frozen=True)
class DiscoveryCandidate:
    symbol: str
    source_universe: str
    priority: int
    exchange: str
    company_name: str
    cik: Optional[str] = None
    exchange_security_name: str = ""


def merge_exchange_and_sec_listings(
    nasdaq_rows: Sequence[Mapping[str, Any]] | None = None,
    other_rows: Sequence[Mapping[str, Any]] | None = None,
    sec_rows: Sequence[Mapping[str, Any]] | None = None,
) -> List[dict[str, Any]]:
    """Merge listing feeds the same way UniverseEngine does, without HTTP."""
    sec_map = {}
    for row in sec_rows or ():
        identity = listing_identity(row.get("symbol") or row.get("ticker"))
        if identity and identity not in sec_map:
            sec_map[identity] = row

    merged: dict[str, dict[str, Any]] = {}
    for row in list(nasdaq_rows or ()) + list(other_rows or ()):
        identity = listing_identity(row.get("symbol"))
        if not identity or identity in merged:
            continue
        sec = sec_map.get(identity)
        exchange = normalize_us_exchange(row.get("exchange"))
        is_etf = bool(row.get("is_etf"))
        exchange_security_name = str(
            row.get("exchange_security_name") or row.get("company_name") or ""
        ).strip()
        company_name = str(
            (sec.get("company_name") if sec else None)
            or exchange_security_name
            or identity
        ).strip()
        merged[identity] = {
            "symbol": identity,
            "company_name": company_name,
            "exchange_security_name": exchange_security_name,
            "exchange": exchange,
            "is_etf": is_etf,
            "cik": (sec.get("cik") if sec else row.get("cik")),
            "sector": row.get("sector"),
            "source_symbol": row.get("symbol"),
        }
    return list(merged.values())


def select_us_equity_discovery_candidates(
    listings: Iterable[Mapping[str, Any]],
    *,
    source_universe: str = US_EQUITY_DISCOVERY_SOURCE,
) -> List[DiscoveryCandidate]:
    """Ordinary U.S. listed commons for the Participation queue.

    Dedupes by listing identity. Does not exclude by sector. Requires a CIK
    so the row is a real SEC-registered equity, matching UniverseEngine.
    """
    unique: dict[str, DiscoveryCandidate] = {}
    for row in listings:
        identity = listing_identity(row.get("symbol") or row.get("ticker"))
        exchange_security_name = str(
            row.get("exchange_security_name") or ""
        ).strip()
        company_name = str(row.get("company_name") or row.get("name") or "").strip()
        reason = excluded_instrument_reason(
            symbol=identity,
            company_name=company_name,
            exchange_security_name=exchange_security_name,
            is_etf=row.get("is_etf"),
        )
        if reason or not identity:
            continue
        cik = str(row.get("cik") or "").strip()
        if not cik:
            continue
        if identity in unique:
            continue
        exchange = normalize_us_exchange(row.get("exchange"))
        unique[identity] = DiscoveryCandidate(
            symbol=identity,
            source_universe=source_universe,
            priority=listing_priority(exchange),
            exchange=exchange,
            company_name=company_name or identity,
            cik=cik,
            exchange_security_name=exchange_security_name,
        )
    return sorted(unique.values(), key=lambda item: (item.priority, item.symbol))
