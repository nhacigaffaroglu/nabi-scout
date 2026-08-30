"""Parse official SP Funds standardized performance and SEC yield.

NAV and market-price rows stay separate. Annualized values are never converted
into cumulative returns. Third-party price history is never substituted.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from services.fund_product_contract import (
    PERFORMANCE_BASIS_MARKET_PRICE,
    PERFORMANCE_BASIS_NAV,
    PILOT_FUND_SYMBOLS,
    PROVIDER_SP_FUNDS_OFFICIAL,
    OfficialFundPerformance,
    OfficialFundYield,
    TRACKING_CONCEPT_DIFFERENCE,
    YIELD_BASIS_SEC_30D,
)

PRODUCT_URL_TEMPLATE = "https://www.sp-funds.com/{symbol}/"

_SECONDARY_BENCHMARK_TICKERS = frozenset({"SPTR2", "SPX", "-"})
_SECONDARY_BENCHMARK_NAMES = (
    "s&p 500 tr",
    "s&p 500 total return",
    "bloomberg global aggregate",
)

_OFFICIAL_BENCHMARK_TICKERS = {
    "SPUS": frozenset({"SPSIEUT"}),
    "SPSK": frozenset({"DJSUKTX", "DJSUKTXR"}),
    "SPRE": frozenset({"SPERSCUT", "SPERSCIJT"}),
    "SPWO": frozenset({"SPDUESUT"}),
}

_TRACKING_HORIZONS = (
    ("return_1y", "1Y"),
    ("return_3m", "3M"),
    ("return_6m", "6M"),
    ("return_ytd", "YTD"),
)

_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

_YIELD = re.compile(
    r"30\s*Day\s*SEC\s*Yield[^\n|]*As of\s*(\d{2}/\d{2}/\d{4})\s*\|\s*([0-9.+-]+)\s*%",
    flags=re.I,
)


def official_product_url(symbol: str) -> str:
    return PRODUCT_URL_TEMPLATE.format(symbol=str(symbol or "").strip().lower())


def _norm_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _parse_return(raw: str) -> Optional[float]:
    text = str(raw or "").strip().replace(",", "")
    if not text or text in {"-", "—", "N/A", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _iso_date(raw: str) -> Optional[str]:
    text = str(raw or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _row_kind(ticker: str) -> tuple[Optional[str], Optional[str]]:
    token = re.sub(r"\s+", " ", str(ticker or "")).strip().upper()
    if token.endswith(" NAV"):
        return token[:-4].strip(), PERFORMANCE_BASIS_NAV
    if token.endswith(" MKT"):
        return token[:-4].strip(), PERFORMANCE_BASIS_MARKET_PRICE
    return None, None


def _is_secondary_benchmark(name: str, ticker: str) -> bool:
    if _norm_symbol(ticker) in _SECONDARY_BENCHMARK_TICKERS:
        return True
    blob = str(name or "").strip().lower()
    return any(token in blob for token in _SECONDARY_BENCHMARK_NAMES)


def _official_benchmark(symbol: str, name: str, ticker: str) -> bool:
    fund = _norm_symbol(symbol)
    tick = _norm_symbol(ticker)
    if tick in _OFFICIAL_BENCHMARK_TICKERS.get(fund, frozenset()):
        return True
    blob = f"{name} {ticker}".lower()
    needles = {
        "SPUS": ("sharia industry exclusions", "shariah industry exclusions"),
        "SPSK": ("dow jones sukuk",),
        "SPRE": ("global all equity reit shariah", "global reit shariah"),
        "SPWO": ("dm ex-u.s", "ex-us", "world"),
    }
    return any(token in blob for token in needles.get(fund, ()))


def parse_official_performance_html(
    html: str,
    *,
    symbol: str,
    source_url: str = "",
) -> dict[str, OfficialFundPerformance]:
    """Return latest NAV and MARKET_PRICE rows for the requested ticker only."""
    fund = _norm_symbol(symbol)
    if fund not in PILOT_FUND_SYMBOLS:
        raise ValueError(f"unsupported official fund product: {symbol}")
    rows: list[dict[str, object]] = []
    for raw_line in (html or "").splitlines():
        cells = [part.strip() for part in raw_line.split("|")]
        cells = [part for part in cells if part != ""]
        if len(cells) < 13:
            continue
        name, ticker = cells[0], cells[1]
        as_of_raw = cells[12]
        if name.lower() == "fund name" or ticker.lower() == "fund ticker":
            continue
        if not _DATE.match(as_of_raw):
            continue
        as_of = _iso_date(as_of_raw)
        payload = {
            "name": re.sub(r"\s+", " ", name).strip(),
            "ticker": re.sub(r"\s+", " ", ticker).strip(),
            "as_of": as_of,
            "return_1m": _parse_return(cells[2]),
            "return_3m": _parse_return(cells[3]),
            "return_6m": _parse_return(cells[4]),
            "return_ytd": _parse_return(cells[5]),
            "since_inception_cumulative": _parse_return(cells[6]),
            "return_1y": _parse_return(cells[7]),
            "return_3y": _parse_return(cells[8]),
            "return_5y": _parse_return(cells[9]),
            "since_inception_annualized": _parse_return(cells[11]),
        }
        rows.append(payload)

    selected: dict[str, dict[str, object]] = {}
    for row in rows:
        row_symbol, basis = _row_kind(str(row["ticker"]))
        if row_symbol != fund or basis is None or row["as_of"] is None:
            continue
        current = selected.get(basis)
        if current is None or str(row["as_of"]) > str(current["as_of"]):
            selected[basis] = row

    out: dict[str, OfficialFundPerformance] = {}
    url = source_url or official_product_url(fund)
    for basis, row in selected.items():
        bench = _match_benchmark(fund, rows, as_of=str(row["as_of"]))
        tracking_value, tracking_horizon = _tracking_difference(row, bench)
        limitations: list[str] = []
        if bench is None:
            limitations.append("OFFICIAL_BENCHMARK_UNMATCHED")
        out[basis] = OfficialFundPerformance(
            symbol=fund,
            fund_symbol=fund,
            as_of=str(row["as_of"]),
            basis=basis,
            return_1m=row["return_1m"],  # type: ignore[arg-type]
            return_3m=row["return_3m"],  # type: ignore[arg-type]
            return_6m=row["return_6m"],  # type: ignore[arg-type]
            return_ytd=row["return_ytd"],  # type: ignore[arg-type]
            return_1y=row["return_1y"],  # type: ignore[arg-type]
            return_3y=row["return_3y"],  # type: ignore[arg-type]
            return_5y=row["return_5y"],  # type: ignore[arg-type]
            since_inception_cumulative=row["since_inception_cumulative"],  # type: ignore[arg-type]
            since_inception_annualized=row["since_inception_annualized"],  # type: ignore[arg-type]
            benchmark_name=None if bench is None else str(bench["name"]),
            benchmark_ticker=None if bench is None else str(bench["ticker"]),
            benchmark_return_1m=None if bench is None else bench["return_1m"],  # type: ignore[arg-type]
            benchmark_return_3m=None if bench is None else bench["return_3m"],  # type: ignore[arg-type]
            benchmark_return_6m=None if bench is None else bench["return_6m"],  # type: ignore[arg-type]
            benchmark_return_ytd=None if bench is None else bench["return_ytd"],  # type: ignore[arg-type]
            benchmark_return_1y=None if bench is None else bench["return_1y"],  # type: ignore[arg-type]
            benchmark_return_3y=None if bench is None else bench["return_3y"],  # type: ignore[arg-type]
            benchmark_return_5y=None if bench is None else bench["return_5y"],  # type: ignore[arg-type]
            tracking_difference=tracking_value,
            tracking_horizon=tracking_horizon,
            tracking_concept=TRACKING_CONCEPT_DIFFERENCE,
            source=PROVIDER_SP_FUNDS_OFFICIAL,
            source_url=url,
            provenance=(PROVIDER_SP_FUNDS_OFFICIAL, "standardized_performance_table"),
            limitations=tuple(limitations),
        )
    return out


def _match_benchmark(
    symbol: str,
    rows: list[dict[str, object]],
    *,
    as_of: str,
) -> Optional[dict[str, object]]:
    candidates = []
    for row in rows:
        ticker = str(row["ticker"])
        name = str(row["name"])
        if str(row["as_of"]) != as_of:
            continue
        if _row_kind(ticker)[0] is not None:
            continue
        if _is_secondary_benchmark(name, ticker):
            continue
        if _official_benchmark(symbol, name, ticker):
            candidates.append(row)
    if not candidates:
        return None
    return candidates[0]


def _tracking_difference(
    fund_row: dict[str, object],
    bench: Optional[dict[str, object]],
) -> tuple[Optional[float], Optional[str]]:
    if bench is None:
        return None, None
    for field, horizon in _TRACKING_HORIZONS:
        fund_value = fund_row.get(field)
        bench_value = bench.get(field)
        if fund_value is None or bench_value is None:
            continue
        return round(float(fund_value) - float(bench_value), 4), horizon
    return None, None


def parse_official_sec_yield_html(
    html: str,
    *,
    symbol: str,
    source_url: str = "",
) -> Optional[OfficialFundYield]:
    fund = _norm_symbol(symbol)
    match = _YIELD.search(html or "")
    if match is None:
        return None
    return OfficialFundYield(
        symbol=fund,
        sec_yield_30d=_parse_return(match.group(2)),
        as_of=_iso_date(match.group(1)),
        source=PROVIDER_SP_FUNDS_OFFICIAL,
        source_url=source_url or official_product_url(fund),
        basis=YIELD_BASIS_SEC_30D,
    )


def select_nav_performance(rows: dict[str, OfficialFundPerformance]) -> Optional[OfficialFundPerformance]:
    return rows.get(PERFORMANCE_BASIS_NAV)


def select_market_performance(rows: dict[str, OfficialFundPerformance]) -> Optional[OfficialFundPerformance]:
    return rows.get(PERFORMANCE_BASIS_MARKET_PRICE)
