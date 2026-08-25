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
_EXCLUDED_NAME = re.compile(
    r"""
    \b(
        warrants? |
        units? |
        rights? |
        preferred |
        depositary\ shares? |
        notes?\ due |
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
US_EQUITY_DISCOVERY_SOURCE = "us_exchange_listed"
EXTERNAL_SIGNAL_SOURCE = "external_signal"


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


def excluded_instrument_reason(
    *,
    symbol: Any,
    company_name: Any = "",
    is_etf: Any = False,
) -> Optional[str]:
    identity = listing_identity(symbol)
    if not identity:
        return "empty_symbol"
    if identity in ETF_SYMBOLS:
        return "catalog_etf"
    if is_etf or _name_says_etf(company_name):
        return "etf"
    if _EXCLUDED_SYMBOL_CHARS.search(identity):
        return "non_common_symbol"
    if _EXCLUDED_SUFFIX.search(identity):
        return "non_common_suffix"
    if _EXCLUDED_NAME.search(str(company_name or "")):
        return "excluded_name"
    return None


def is_ordinary_equity_listing(row: Mapping[str, Any]) -> bool:
    return excluded_instrument_reason(
        symbol=row.get("symbol"),
        company_name=row.get("company_name") or row.get("name") or "",
        is_etf=row.get("is_etf"),
    ) is None


def _name_says_etf(name: Any) -> bool:
    lowered = str(name or "").strip().lower()
    if not lowered:
        return False
    return bool(re.search(r"\betf\b", lowered))
