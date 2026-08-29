"""Deterministic U.S. listing identity and instrument-type filters.

Identity is symbol-only after punctuation normalization (BRK.B → BRK-B).
Filters are mechanical (name/symbol patterns), never sector or expected
halal outcome. Ordinary common stock remains eligible regardless of sector.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from config.universe_expansion_sources import ETF_SYMBOLS

_EXCLUDED_SYMBOL_CHARS = re.compile(r"[/^+$]")
_EXCLUDED_SUFFIX = re.compile(
    r"-(W|WS|WTS|WT|U|UN|R|RT|RTS|P|PR|PRA|PRB|PRC|PRD|PRE)$"
)
_ETF_NAME = re.compile(r"\betfs?\b", re.IGNORECASE)
_ETN_NAME = re.compile(
    r"\b(?:etns?|exchange[\s-]+traded\s+notes?)\b",
    re.IGNORECASE,
)
_CLOSED_END_FUND_NAME = re.compile(
    r"\bclosed[\s-]+end(?:\s+fund|\s+investment\s+company)\b",
    re.IGNORECASE,
)
_PREFERRED_NAME = re.compile(
    r"\bpreference\s+shares?\b|\bpreferred(?:\s+(?:stock|shares?))?\b",
    re.IGNORECASE,
)
_LISTED_NOTE_NAME = re.compile(
    r"""
    \bnotes?\s+due\b
    | \b(?:perpetual\s+)?(?:junior\s+|senior\s+)?subordinated\s+notes?\b
    | \bsenior\s+notes?\b
    | \bjunior\s+notes?\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_EXCLUDED_NAME = re.compile(
    r"""
    \b(
        warrants? |
        units? |
        rights? |
        depositary\ shares? |
        bonds? |
        debentures? |
        acquisition\ corp(?:oration)? |
        acquisition\ company |
        blank\ check |
        special\ purpose\ acquisition |
        spac |
        leveraged |
        inverse |
        ultra\ short |
        ultra\ pro |
        [234]x
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

EXCHANGE_PRIORITY = {
    "NYSE": 80,
    "NASDAQ": 90,
    "AMEX": 100,
}
DEFAULT_LISTING_PRIORITY = 110
EXTERNAL_SIGNAL_PRIORITY = 120
STRATEGIC_LAYER_DISCOVERY_PRIORITY = 115
US_EQUITY_DISCOVERY_SOURCE = "us_exchange_listed"
EXTERNAL_SIGNAL_SOURCE = "external_signal"
STRATEGIC_LAYER_DISCOVERY_SOURCE = "strategic_layer_discovery"


def listing_identity(symbol: Any) -> str:
    """Canonical queue identity: uppercase, class-share dot → hyphen."""
    text = str(symbol or "").strip().upper()
    if not text:
        return ""
    return text.replace(".", "-")


def normalize_us_exchange(value: Any) -> str:
    text = str(value or "").strip().upper()
    mapping = {
        "NASDAQ": "NASDAQ",
        "NYSE": "NYSE",
        "NEW YORK STOCK EXCHANGE": "NYSE",
        "NYSE AMERICAN": "AMEX",
        "NYSE MKT": "AMEX",
        "AMEX": "AMEX",
        "NYSE ARCA": "ARCA",
        "ARCA": "ARCA",
        "CBOE BZX": "BZX",
        "IEX": "IEX",
    }
    return mapping.get(text, text)


def listing_priority(exchange: Any) -> int:
    """Transparent operational order: major U.S. exchanges first, then symbol.

    Not an investment ranking. Does not use NABI Score, momentum, or
    expected participation outcome.
    """
    return EXCHANGE_PRIORITY.get(normalize_us_exchange(exchange), DEFAULT_LISTING_PRIORITY)


def instrument_name_exclusion_reason(name: Any) -> Optional[str]:
    """Word-boundary instrument terms in a listing or issuer name.

    Substring matches inside ordinary words (United, Aerospace, Bright,
    Wright) are not exclusions. Fetch and final eligibility share this helper.
    """
    text = str(name or "").strip()
    if not text:
        return None
    if _ETF_NAME.search(text):
        return "etf"
    if _ETN_NAME.search(text):
        return "etn"
    if _CLOSED_END_FUND_NAME.search(text):
        return "closed_end_fund"
    if _PREFERRED_NAME.search(text):
        return "preferred"
    if _LISTED_NOTE_NAME.search(text):
        return "listed_note"
    if _EXCLUDED_NAME.search(text):
        return "excluded_name"
    return None


def excluded_security_name(name: Any) -> bool:
    """True when a name is a non-ordinary instrument on word-boundary rules."""
    return instrument_name_exclusion_reason(name) is not None


def excluded_instrument_reason(
    *,
    symbol: Any,
    company_name: Any = "",
    exchange_security_name: Any = "",
    is_etf: Any = False,
) -> Optional[str]:
    identity = listing_identity(symbol)
    if not identity:
        return "empty_symbol"
    if identity in ETF_SYMBOLS:
        return "catalog_etf"
    names = _names_for_instrument_filter(
        company_name=company_name,
        exchange_security_name=exchange_security_name,
    )
    if is_etf or any(
        instrument_name_exclusion_reason(item) == "etf" for item in names
    ):
        return "etf"
    if _EXCLUDED_SYMBOL_CHARS.search(identity):
        return "non_common_symbol"
    if _EXCLUDED_SUFFIX.search(identity):
        return "non_common_suffix"
    for item in names:
        reason = instrument_name_exclusion_reason(item)
        if reason:
            return reason
    return None


def is_ordinary_equity_listing(row: Mapping[str, Any]) -> bool:
    return excluded_instrument_reason(
        symbol=row.get("symbol"),
        company_name=row.get("company_name") or row.get("name") or "",
        exchange_security_name=row.get("exchange_security_name") or "",
        is_etf=row.get("is_etf"),
    ) is None


def _names_for_instrument_filter(
    *,
    company_name: Any,
    exchange_security_name: Any,
) -> tuple[str, ...]:
    names: list[str] = []
    for value in (exchange_security_name, company_name):
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text)
    return tuple(names)
