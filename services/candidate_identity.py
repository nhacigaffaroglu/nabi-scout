from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

MARKET_ALIASES = {
    "US": frozenset({"US", "USA", "ABD"}),
    "USA": frozenset({"US", "USA", "ABD"}),
    "ABD": frozenset({"US", "USA", "ABD"}),
    "TR": frozenset({"TR", "BIST", "IST", "TURKEY"}),
    "BIST": frozenset({"TR", "BIST", "IST", "TURKEY"}),
    "IST": frozenset({"TR", "BIST", "IST", "TURKEY"}),
    "TURKEY": frozenset({"TR", "BIST", "IST", "TURKEY"}),
}

EXPANSION_DATA_SOURCE = "universe_expansion"


def numeric_current_price(row) -> Optional[float]:
    if not row:
        return None
    raw = row.get("current_price")
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value != value:
        return None
    return value


def _market_aliases(market: Optional[str]) -> frozenset:
    key = str(market or "").strip().upper()
    return MARKET_ALIASES.get(key, frozenset({key}) if key else frozenset())


def is_placeholder_company_name(name: Any, symbol: Any) -> bool:
    cleaned = str(name or "").strip()
    if not cleaned:
        return True
    return cleaned.upper() == str(symbol or "").strip().upper()


def is_stub_candidate(row: Optional[Dict[str, Any]]) -> bool:
    if not row:
        return True
    symbol = row.get("symbol")
    return (
        numeric_current_price(row) is None
        and is_placeholder_company_name(row.get("company_name"), symbol)
        and not row.get("decision")
        and str(row.get("data_source") or "") in {"", EXPANSION_DATA_SOURCE}
    )


def select_canonical_candidate(
    rows: Sequence[Dict[str, Any]],
    *,
    preferred_market: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Deterministic canonical row for a symbol.

    Prefers priced/enriched scanner rows over universe-expansion stubs.
    Scanner uses market=ABD; expansion historically inserted market=US.
    """
    candidates = [row for row in rows if row]
    if not candidates:
        return None
    aliases = _market_aliases(preferred_market)

    def sort_key(row: Dict[str, Any]) -> tuple:
        priced = numeric_current_price(row) is not None
        real_name = not is_placeholder_company_name(
            row.get("company_name"),
            row.get("symbol"),
        )
        has_decision = bool(row.get("decision"))
        source = str(row.get("data_source") or "")
        scanner = bool(source and source != EXPANSION_DATA_SOURCE)
        market = str(row.get("market") or "").strip().upper()
        market_match = bool(aliases) and market in aliases
        created = str(row.get("created_at") or "")
        return (
            not priced,
            not real_name,
            not has_decision,
            not scanner,
            not market_match,
            created,
        )

    return sorted(candidates, key=sort_key)[0]


def select_persisted_price_candidate(
    rows: Sequence[Dict[str, Any]],
    *,
    preferred_market: Optional[str] = None,
):
    return select_canonical_candidate(rows, preferred_market=preferred_market)


def merge_preserving_enriched(
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
) -> Dict[str, Any]:
    """Build an update patch that never clobbers richer existing fields."""
    symbol = incoming.get("symbol") or existing.get("symbol")
    patch: Dict[str, Any] = {}
    for key, new_val in incoming.items():
        if key in {"id", "created_at"}:
            continue
        if new_val is None or new_val == "":
            continue
        if key == "company_name" and is_placeholder_company_name(new_val, symbol):
            continue
        if key == "data_source" and str(new_val) == EXPANSION_DATA_SOURCE:
            existing_source = str(existing.get("data_source") or "")
            if existing_source and existing_source != EXPANSION_DATA_SOURCE:
                continue
        if key in {"market", "asset_type"} and existing.get(key) not in (None, ""):
            continue
        old_val = existing.get(key)
        if old_val is not None and old_val != "":
            continue
        patch[key] = new_val
    return patch
