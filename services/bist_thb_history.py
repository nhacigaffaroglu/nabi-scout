"""Official Borsa THB daily history cache. No default live fetch.

One zip per trade_date contains the whole equity universe, so broader BIST
coverage has the same download cost as the pilots.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from services.bist_eod_bulletin import (
    BistEodQuote,
    BistThbBulletin,
    BistThbDownloadError,
    official_equity_series,
    parse_thb_csv,
    thb_download_url,
    thb_member_name,
    unzip_thb_csv,
    download_thb_zip,
    is_weekend,
)
from services.bist_official_market_facts import market_data_is_stale
from services.bist_symbol_mapping import normalize_bist_symbol
from services.wealth_contract import normalize_symbol


SOURCE_THB_HISTORY = "borsa_istanbul_thb"
ADJUST_RAW = "RAW_UNADJUSTED"
CACHE_INDEX = "index.json"
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_NOT_FOUND = "http_404"

DEFAULT_CACHE_DIR = Path(".cache/bist_thb_history")


@dataclass(frozen=True)
class BistHistoricalPrice:
    symbol: str
    trade_date: date
    close: float
    currency: str
    series: str
    market: str
    source: str
    source_url: str
    source_file: str
    observed_at: str
    adjustment_status: str
    previous_close: Optional[float] = None
    reference_price: Optional[float] = None
    corporate_action_flag: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "trade_date": self.trade_date.isoformat(),
            "close": self.close,
            "currency": self.currency,
            "series": self.series,
            "market": self.market,
            "source": self.source,
            "source_url": self.source_url,
            "source_file": self.source_file,
            "observed_at": self.observed_at,
            "adjustment_status": self.adjustment_status,
            "previous_close": self.previous_close,
            "reference_price": self.reference_price,
            "corporate_action_flag": self.corporate_action_flag,
        }


@dataclass
class ThbHistoryCache:
    root: Path
    known_dates: dict[str, str] = field(default_factory=dict)

    @property
    def index_path(self) -> Path:
        return self.root / CACHE_INDEX

    def csv_path(self, trading_date: date) -> Path:
        return self.root / thb_member_name(trading_date)


def _today_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(symbol: str) -> str:
    return normalize_bist_symbol(symbol) or normalize_symbol(symbol)


def quote_to_historical_price(
    quote: BistEodQuote,
    *,
    observed_at: Optional[str] = None,
    adjustment_status: str = ADJUST_RAW,
) -> BistHistoricalPrice:
    return BistHistoricalPrice(
        symbol=quote.canonical_symbol,
        trade_date=quote.trading_date,
        close=quote.closing_price,
        currency=quote.currency,
        series=quote.instrument_series,
        market="",
        source=SOURCE_THB_HISTORY,
        source_url=quote.source_url,
        source_file=quote.source_file,
        observed_at=observed_at or _today_iso(),
        adjustment_status=adjustment_status,
        previous_close=quote.previous_close,
        reference_price=quote.reference_price,
        corporate_action_flag=quote.corporate_action,
    )


def load_history_cache(root: Path = DEFAULT_CACHE_DIR) -> ThbHistoryCache:
    cache = ThbHistoryCache(root=root)
    if cache.index_path.is_file():
        raw = json.loads(cache.index_path.read_text(encoding="utf-8"))
        known = raw.get("known_dates") if isinstance(raw, dict) else None
        if isinstance(known, dict):
            cache.known_dates = {str(key): str(value) for key, value in known.items()}
    return cache


def save_history_cache(cache: ThbHistoryCache) -> None:
    cache.root.mkdir(parents=True, exist_ok=True)
    cache.index_path.write_text(
        json.dumps({"known_dates": cache.known_dates}, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def store_bulletin(cache: ThbHistoryCache, bulletin: BistThbBulletin, text: str) -> None:
    cache.root.mkdir(parents=True, exist_ok=True)
    key = bulletin.trading_date.isoformat()
    cache.csv_path(bulletin.trading_date).write_text(text, encoding="utf-8")
    cache.known_dates[key] = STATUS_OK
    save_history_cache(cache)


def mark_known_date(cache: ThbHistoryCache, trading_date: date, status: str) -> None:
    cache.root.mkdir(parents=True, exist_ok=True)
    cache.known_dates[trading_date.isoformat()] = status
    save_history_cache(cache)


def date_is_cached(cache: ThbHistoryCache, trading_date: date) -> bool:
    return trading_date.isoformat() in cache.known_dates


def last_cached_ok_date(cache: ThbHistoryCache) -> Optional[date]:
    ok = [
        date.fromisoformat(key)
        for key, status in cache.known_dates.items()
        if status == STATUS_OK
    ]
    return max(ok) if ok else None


def missing_weekday_dates(
    cache: ThbHistoryCache,
    *,
    as_of: date,
    lookback_days: int = 14,
) -> tuple[date, ...]:
    """Weekdays after the last OK cache date that have no index entry.

    Weekends are excluded. Holidays remain until fetch marks http_404.
    Does not download.
    """
    last = last_cached_ok_date(cache)
    start = last + timedelta(days=1) if last else as_of - timedelta(days=lookback_days)
    missing: list[date] = []
    cursor = start
    step = timedelta(days=1)
    while cursor <= as_of:
        if not is_weekend(cursor) and not date_is_cached(cache, cursor):
            missing.append(cursor)
        cursor += step
    return tuple(missing)


def load_cached_bulletin(cache: ThbHistoryCache, trading_date: date) -> Optional[BistThbBulletin]:
    if cache.known_dates.get(trading_date.isoformat()) != STATUS_OK:
        return None
    path = cache.csv_path(trading_date)
    if not path.is_file():
        return None
    return parse_thb_csv(
        path.read_text(encoding="utf-8"),
        source_file=thb_member_name(trading_date),
        source_url=thb_download_url(trading_date),
    )


def ingest_thb_text(
    text: str,
    *,
    source_file: str,
    source_url: str,
    cache: Optional[ThbHistoryCache] = None,
) -> BistThbBulletin:
    bulletin = parse_thb_csv(text, source_file=source_file, source_url=source_url)
    if cache is not None:
        store_bulletin(cache, bulletin, text)
    return bulletin


def fetch_thb_trading_date(
    trading_date: date,
    *,
    cache: ThbHistoryCache,
    opener: Callable[..., object],
    timeout: int = 30,
    invalidate: bool = False,
) -> Optional[BistThbBulletin]:
    """Fetch one official zip. Cached trade_date/series keys are not refetched."""
    if is_weekend(trading_date):
        mark_known_date(cache, trading_date, STATUS_EMPTY)
        return None
    if date_is_cached(cache, trading_date) and not invalidate:
        return load_cached_bulletin(cache, trading_date)
    try:
        payload = download_thb_zip(trading_date, opener=opener, timeout=timeout)
        text = unzip_thb_csv(payload, trading_date)
        bulletin = ingest_thb_text(
            text,
            source_file=thb_member_name(trading_date),
            source_url=thb_download_url(trading_date),
            cache=cache,
        )
        return bulletin
    except BistThbDownloadError as exc:
        if exc.status_code == 404:
            mark_known_date(cache, trading_date, STATUS_NOT_FOUND)
            return None
        raise


def series_from_bulletins(
    bulletins: Iterable[BistThbBulletin],
    symbol: str,
    *,
    observed_at: Optional[str] = None,
) -> tuple[BistHistoricalPrice, ...]:
    ticker = _canonical(symbol)
    expected_series = official_equity_series(ticker)
    rows: list[BistHistoricalPrice] = []
    for bulletin in bulletins:
        quote = bulletin.quotes.get(ticker)
        if quote is None:
            continue
        if quote.instrument_series != expected_series:
            continue
        if quote.currency != "TRY":
            continue
        rows.append(quote_to_historical_price(quote, observed_at=observed_at))
    rows.sort(key=lambda item: item.trade_date)
    return tuple(rows)


def load_cached_series(cache: ThbHistoryCache, symbol: str) -> tuple[BistHistoricalPrice, ...]:
    bulletins: list[BistThbBulletin] = []
    for key, status in sorted(cache.known_dates.items()):
        if status != STATUS_OK:
            continue
        bulletin = load_cached_bulletin(cache, date.fromisoformat(key))
        if bulletin is not None:
            bulletins.append(bulletin)
    return series_from_bulletins(bulletins, symbol)


def history_quality(
    series: Sequence[BistHistoricalPrice],
    *,
    as_of: Optional[date] = None,
) -> dict[str, object]:
    dates = [item.trade_date for item in series]
    duplicates = len(dates) - len(set(dates))
    stale = False
    if series:
        stale = market_data_is_stale(series[-1].trade_date, as_of=as_of)
    return {
        "observations": len(series),
        "earliest": dates[0].isoformat() if dates else None,
        "latest": dates[-1].isoformat() if dates else None,
        "duplicate_rows": duplicates,
        "stale": stale,
        "missing_trading_days": None,
    }
