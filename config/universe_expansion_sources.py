from __future__ import annotations

from typing import Dict, List, Tuple

from config.scan_universe import SCAN_UNIVERSES

# ETFs excluded from equity participation onboarding.
ETF_SYMBOLS = frozenset({"SPUS", "HLAL", "SPSK"})

# Pilot equity symbols (no ETFs) — highest priority batch.
PILOT_EQUITY_SYMBOLS: Tuple[str, ...] = tuple(
    symbol
    for symbol in SCAN_UNIVERSES.get("Pilot 15", [])
    if symbol not in ETF_SYMBOLS
)

# Bounded S&P 500 / large-cap core batch (static, versioned config — no scraping).
SP500_CORE_SYMBOLS: Tuple[str, ...] = (
    "ABBV", "ABT", "ACN", "ADBE", "AMD", "AMGN", "BA", "BAC", "BKNG", "BLK",
    "BRK-B", "CAT", "COST", "CSCO", "CVX", "DE", "DHR", "DIS", "GE", "GILD",
    "GS", "HD", "HON", "IBM", "INTC", "INTU", "ISRG", "JPM", "KO", "LIN",
    "LLY", "LOW", "MA", "MCD", "MDT", "MRK", "MS", "NEE", "NFLX", "NKE",
    "ORCL", "PEP", "PFE", "PG", "PM", "QCOM", "RTX", "SBUX", "SCHW", "T",
    "TMO", "TMUS", "TXN", "UNH", "UNP", "UPS", "V", "VZ", "WFC", "WMT",
)

# Nasdaq-100 style supplement (deduped against prior batches at runtime).
NASDAQ100_CORE_SYMBOLS: Tuple[str, ...] = (
    "ADP", "ADSK", "AMAT", "ANSS", "BIIB", "CDNS", "CHTR", "CMCSA", "CSX",
    "DXCM", "EA", "EXC", "FISV", "FTNT", "GILD", "IDXX", "ILMN", "INTU",
    "KDP", "KLAC", "LRCX", "LULU", "MAR", "MCHP", "MDLZ", "MNST", "MRNA",
    "MRVL", "MU", "NXPI", "ODFL", "ON", "PANW", "PAYX", "PCAR", "PYPL",
    "REGN", "ROST", "SNPS", "TEAM", "VRSK", "VRTX", "WBD", "WDAY", "XEL",
    "ZS",
)

UNIVERSE_EXPANSION_SOURCES: Tuple[Dict[str, object], ...] = (
    {"key": "pilot_equity", "priority": 10, "symbols": PILOT_EQUITY_SYMBOLS},
    {"key": "sp500_core", "priority": 20, "symbols": SP500_CORE_SYMBOLS},
    {"key": "nasdaq100_core", "priority": 30, "symbols": NASDAQ100_CORE_SYMBOLS},
)


def dedupe_expansion_symbols() -> List[Tuple[str, str, int]]:
    """Return (symbol, source_universe, priority) rows with global dedupe."""
    seen: set[str] = set()
    rows: List[Tuple[str, str, int]] = []
    for source in UNIVERSE_EXPANSION_SOURCES:
        key = str(source["key"])
        priority = int(source["priority"])
        for symbol in source["symbols"]:
            normalized = str(symbol or "").strip().upper()
            if not normalized or normalized in ETF_SYMBOLS or normalized in seen:
                continue
            seen.add(normalized)
            rows.append((normalized, key, priority))
    return rows
