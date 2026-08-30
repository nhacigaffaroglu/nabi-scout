from __future__ import annotations

from typing import Dict, Optional, Tuple

from services.bist_symbol_mapping import BIST_PORTFOLIO_SYMBOLS, normalize_bist_symbol
from services.wealth_contract import (
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    ASSET_CLASS_ETF,
    ASSET_CLASS_FUND,
    ASSET_CLASS_OTHER,
)

KNOWN_ETF_SYMBOLS = frozenset({"SPUS", "SPSK", "HLAL", "SPRE", "SPWO"})
KNOWN_EQUITY_US = frozenset({"UPS", "AVGO", "CRM", "TSLA", "AAPL", "MRVL", "VISN"})
KNOWN_EQUITY_TR = BIST_PORTFOLIO_SYMBOLS
CASH_SYMBOL = "CASH"
TF_PARTICIPATION_SYMBOL = "TF_KATILIM"


def resolve_asset_metadata(symbol: str, *, currency: str) -> Tuple[str, str, str, str]:
    """Return asset_class, market, instrument_kind, asset_class_status."""
    sym = normalize_bist_symbol(symbol) or str(symbol or "").strip().upper()
    ccy = str(currency or "").strip().upper()

    if sym == CASH_SYMBOL:
        return ASSET_CLASS_CASH, "US" if ccy == "USD" else ccy, "cash", "RESOLVED"

    if sym == TF_PARTICIPATION_SYMBOL:
        return ASSET_CLASS_OTHER, "TR", "deposit", "REQUIRES_CONFIRMATION"

    if sym in KNOWN_ETF_SYMBOLS:
        return ASSET_CLASS_ETF, "US", "etf", "RESOLVED"

    if sym in KNOWN_EQUITY_US:
        return ASSET_CLASS_EQUITY, "US", "equity", "RESOLVED"

    if sym in KNOWN_EQUITY_TR:
        return ASSET_CLASS_EQUITY, "TR", "equity", "RESOLVED"

    return ASSET_CLASS_OTHER, "US", "other", "REQUIRES_CONFIRMATION"


def display_name_for(symbol: str) -> Optional[str]:
    sym = str(symbol or "").strip().upper()
    if sym == TF_PARTICIPATION_SYMBOL:
        return "Türkiye Finans Katılım Hesabı"
    return None
