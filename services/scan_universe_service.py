from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from config.scan_universe import SCAN_UNIVERSES

DAILY_UNIVERSE_KEYS = ("Teknoloji 10", "Katılım ETF 3")
SCHEDULED_UNIVERSE_PREFIX = "SCHEDULED · Daily · "


def scheduled_universe_name(run_date: Optional[date] = None) -> str:
    target = run_date or date.today()
    return f"{SCHEDULED_UNIVERSE_PREFIX}{target.isoformat()}"


def build_fixed_universe_rows(
    universe_name: str,
    sec_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    sec_lookup = sec_lookup or {}
    etf_symbols = set(SCAN_UNIVERSES.get("Katılım ETF 3", []))
    rows: List[Dict[str, Any]] = []

    for symbol in SCAN_UNIVERSES[universe_name]:
        normalized_symbol = symbol.strip().upper()
        is_etf = normalized_symbol in etf_symbols
        sec_row = sec_lookup.get(normalized_symbol, {})

        rows.append({
            "symbol": normalized_symbol,
            "cik": None if is_etf else sec_row.get("cik"),
            "company_name": sec_row.get("company_name") or normalized_symbol,
            "exchange": sec_row.get("exchange"),
            "is_etf": is_etf,
        })

    return rows


def build_daily_universe_rows(
    *,
    sec_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    watchlist_entries: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    sec_lookup = sec_lookup or {}
    watchlist_entries = watchlist_entries or []
    merged: Dict[str, Dict[str, Any]] = {}

    for universe_key in DAILY_UNIVERSE_KEYS:
        for row in build_fixed_universe_rows(universe_key, sec_lookup):
            merged[row["symbol"]] = row

    for entry in watchlist_entries:
        candidate = entry.get("candidate") or {}
        symbol = str(candidate.get("symbol") or "").strip().upper()
        if not symbol or symbol in merged:
            continue
        merged[symbol] = {
            "symbol": symbol,
            "cik": candidate.get("cik"),
            "company_name": candidate.get("company_name") or symbol,
            "exchange": candidate.get("exchange"),
            "is_etf": bool(candidate.get("is_etf", False)),
        }

    return [merged[symbol] for symbol in sorted(merged)]
