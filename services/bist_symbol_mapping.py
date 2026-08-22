from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.wealth_contract import normalize_symbol
from services.wealth_price_service import normalize_currency


BIST_PORTFOLIO_SYMBOLS = frozenset({"BIMAS", "ASELS", "TUPRS"})
BIST_EXCHANGES = frozenset({"IST", "BIST", "ISTANBUL"})
US_MARKETS = frozenset({"US", "USA", "ABD", "NASDAQ", "NYSE", "AMEX"})

# Proven Prompt 8 mappings. Onboarding quotes these tickers; it does not search.
CANONICAL_BIST_PROVIDER_MAPPINGS = {
    "TUPRS": {
        "portfolio_symbol": "TUPRS",
        "provider_symbol": "TUPRS.IS",
        "company_name": "Türkiye Petrol Rafinerileri A.S.",
        "currency": "TRY",
        "exchange": "IST",
        "market": "TR",
    },
    "ASELS": {
        "portfolio_symbol": "ASELS",
        "provider_symbol": "ASELS.IS",
        "company_name": "Aselsan Elektronik Sanayi ve Ticaret A.S. Class B",
        "currency": "TRY",
        "exchange": "IST",
        "market": "TR",
    },
    "BIMAS": {
        "portfolio_symbol": "BIMAS",
        "provider_symbol": "BIMAS.IS",
        "company_name": "BIM Birlesik Magazalar A.S.",
        "currency": "TRY",
        "exchange": "IST",
        "market": "TR",
    },
}

# Adapter-local Alpha Vantage Istanbul tickers. Canonical assets stay TUPRS/ASELS/BIMAS.
ALPHA_VANTAGE_BIST_PROVIDER_SYMBOLS = {
    "TUPRS": "TUPRS.IS",
    "ASELS": "ASELS.IS",
    "BIMAS": "BIMAS.IS",
}

# Prompt 10 live capability: Alpha Vantage GLOBAL_QUOTE does not cover these BIST names.
ALPHA_VANTAGE_BIST_CAPABLE = False

# Adapter-local Twelve Data Borsa Istanbul identity. Canonical assets stay TUPRS/ASELS/BIMAS.
TWELVE_DATA_BIST_MIC = "XIST"
TWELVE_DATA_BIST_EXCHANGES = frozenset({"XIST", "BIST", "IST", "ISTANBUL"})
TWELVE_DATA_BIST_PROVIDER_REQUESTS = {
    "TUPRS": {"symbol": "TUPRS", "mic_code": TWELVE_DATA_BIST_MIC},
    "ASELS": {"symbol": "ASELS", "mic_code": TWELVE_DATA_BIST_MIC},
    "BIMAS": {"symbol": "BIMAS", "mic_code": TWELVE_DATA_BIST_MIC},
}

# Official Borsa İstanbul daily bulletin instrument series. Canonical assets stay TUPRS/ASELS/BIMAS.
BORSA_ISTANBUL_EOD_SERIES_SUFFIX = ".E"
BORSA_ISTANBUL_EOD_PROVIDER_SERIES = {
    "TUPRS": "TUPRS.E",
    "ASELS": "ASELS.E",
    "BIMAS": "BIMAS.E",
}


def canonical_bist_provider_mapping(portfolio_symbol: str) -> Optional[Dict[str, str]]:
    wanted = normalize_symbol(portfolio_symbol)
    row = CANONICAL_BIST_PROVIDER_MAPPINGS.get(wanted)
    return dict(row) if row else None


def alpha_vantage_bist_provider_symbol(portfolio_symbol: str) -> Optional[str]:
    wanted = normalize_symbol(portfolio_symbol)
    return ALPHA_VANTAGE_BIST_PROVIDER_SYMBOLS.get(wanted)


def twelve_data_bist_request(portfolio_symbol: str) -> Optional[Dict[str, str]]:
    wanted = normalize_symbol(portfolio_symbol)
    row = TWELVE_DATA_BIST_PROVIDER_REQUESTS.get(wanted)
    return dict(row) if row else None


def borsa_istanbul_eod_series(portfolio_symbol: str) -> Optional[str]:
    wanted = normalize_symbol(portfolio_symbol)
    if not wanted:
        return None
    known = BORSA_ISTANBUL_EOD_PROVIDER_SERIES.get(wanted)
    if known:
        return known
    if wanted.isalnum():
        return f"{wanted}{BORSA_ISTANBUL_EOD_SERIES_SUFFIX}"
    return None


def fmp_search_hits(fmp_client, query: str) -> List[Dict[str, Any]]:
    search = getattr(fmp_client, "search_symbol", None)
    if not callable(search):
        return []
    rows = search(query)
    return rows if isinstance(rows, list) else []


def select_bist_provider_mapping(
    portfolio_symbol: str,
    search_rows: List[Dict[str, Any]],
) -> Optional[Dict[str, str]]:
    """Pick the Istanbul / TRY FMP ticker for a portfolio symbol.

    Never accepts a USD/US hit (e.g. BIMT) as a BIST mapping.
    """
    wanted = normalize_symbol(portfolio_symbol)
    matches: List[Dict[str, Any]] = []
    for row in search_rows:
        provider_symbol = str(row.get("symbol") or "").strip().upper()
        if not provider_symbol:
            continue
        currency = normalize_currency(row.get("currency"))
        exchange = str(
            row.get("exchange") or row.get("exchangeShortName") or ""
        ).strip().upper()
        country = str(row.get("country") or "").strip().upper()
        base = provider_symbol.split(".", 1)[0]
        if base != wanted:
            continue
        if currency != "TRY":
            continue
        if exchange and exchange in US_MARKETS:
            continue
        if exchange and exchange not in BIST_EXCHANGES and country not in {"TR", "TURKEY", "TUR"}:
            continue
        if exchange not in BIST_EXCHANGES and not exchange and country not in {"TR", "TURKEY", "TUR"}:
            continue
        matches.append(row)

    if not matches:
        return None

    def sort_key(row: Dict[str, Any]) -> tuple:
        provider_symbol = str(row.get("symbol") or "").strip().upper()
        is_is_suffix = provider_symbol.endswith(".IS")
        return (not is_is_suffix, provider_symbol)

    chosen = sorted(matches, key=sort_key)[0]
    provider_symbol = str(chosen.get("symbol") or "").strip().upper()
    return {
        "portfolio_symbol": wanted,
        "provider_symbol": provider_symbol,
        "company_name": str(chosen.get("name") or chosen.get("companyName") or wanted),
        "currency": normalize_currency(chosen.get("currency") or "TRY"),
        "exchange": str(chosen.get("exchange") or "IST").strip().upper(),
        "market": "TR",
    }


def resolve_bist_provider_symbol(fmp_client, portfolio_symbol: str) -> Optional[Dict[str, str]]:
    wanted = normalize_symbol(portfolio_symbol)
    if wanted not in BIST_PORTFOLIO_SYMBOLS:
        return None
    return select_bist_provider_mapping(wanted, fmp_search_hits(fmp_client, wanted))
