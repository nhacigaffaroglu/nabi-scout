from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from services.wealth_contract import normalize_symbol
from services.wealth_price_service import normalize_currency


ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
BIST_THB_HOST = "https://borsaistanbul.com"
BIST_THB_SESSION_SUFFIX = "1"
BIST_EQUITY_SERIES_SUFFIX = ".E"
BIST_EQUITY_INSTRUMENT_GROUP = "EQT"
OFFICIAL_EOD_FIELD = "CLOSING PRICE"
OFFICIAL_EOD_FIELD_TR = "KAPANIS FIYATI"
SOURCE_DATASET = "thb"
SOURCE_IDENTITY = "BORSA_ISTANBUL"
BIST_EQUITY_CURRENCY = "TRY"
DEFAULT_LOOKBACK_TRADING_DAYS = 10
_USER_AGENT = "nabi-scout-borsa-istanbul-eod/1.0"

_EN_ALIASES = {
    "TRADE DATE": "trade_date",
    "INSTRUMENT SERIES CODE": "series",
    "INSTRUMENT GROUP": "group",
    "CLOSING PRICE": "close",
    "PREVIOUS LAST PRICE": "previous_close",
    "TOTAL TRADED VOLUME": "volume",
    "VWAP": "vwap",
    "CLOSING SESSION PRICE": "closing_session_price",
    "MARKET": "market",
    "CORPORATE ACTION": "corporate_action",
    "REFERENCE PRICE": "reference_price",
}
_TR_ALIASES = {
    "TARIH": "trade_date",
    "ISLEM KODU": "series",
    "ENSTRUMAN GRUBU": "group",
    "KAPANIS FIYATI": "close",
    "ONCEKI KAPANIS FIYATI": "previous_close",
    "TOPLAM ISLEM ADEDI": "volume",
    "A.O.F": "vwap",
    "KAPANIS SEANSI FIYATI": "closing_session_price",
    "YAPISAL BAZDA PIYASA ALT BOLUMU": "market",
    "OZSERMAYE HALI": "corporate_action",
    "REFERANS FIYAT": "reference_price",
}


@dataclass(frozen=True)
class BistEodQuote:
    canonical_symbol: str
    instrument_series: str
    trading_date: date
    closing_price: float
    currency: str
    official_field: str
    source_file: str
    source_url: str
    previous_close: Optional[float] = None
    volume: Optional[float] = None
    vwap: Optional[float] = None
    corporate_action: str = ""
    reference_price: Optional[float] = None


@dataclass(frozen=True)
class BistThbBulletin:
    trading_date: date
    source_file: str
    source_url: str
    quotes: Dict[str, BistEodQuote]
    rejected: Dict[str, str]


class BistThbDownloadError(Exception):
    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def istanbul_today(now: Optional[datetime] = None) -> date:
    current = now or datetime.now(ISTANBUL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ISTANBUL_TZ)
    return current.astimezone(ISTANBUL_TZ).date()


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def candidate_trading_dates(
    as_of: date,
    *,
    max_trading_days: int = DEFAULT_LOOKBACK_TRADING_DAYS,
) -> List[date]:
    days: List[date] = []
    cursor = as_of
    while len(days) < max_trading_days:
        if not is_weekend(cursor):
            days.append(cursor)
        cursor -= timedelta(days=1)
    return days


def thb_download_url(trading_date: date) -> str:
    stamp = trading_date.strftime("%Y%m%d")
    return (
        f"{BIST_THB_HOST}/data/thb/{trading_date:%Y}/{trading_date:%m}/"
        f"thb{stamp}{BIST_THB_SESSION_SUFFIX}.zip"
    )


def thb_member_name(trading_date: date) -> str:
    return f"thb{trading_date.strftime('%Y%m%d')}{BIST_THB_SESSION_SUFFIX}.csv"


def official_equity_series(canonical_symbol: str) -> str:
    return f"{normalize_symbol(canonical_symbol)}{BIST_EQUITY_SERIES_SUFFIX}"


def canonical_from_equity_series(series: str) -> Optional[str]:
    code = str(series or "").strip().upper()
    if not code.endswith(BIST_EQUITY_SERIES_SUFFIX):
        return None
    base = code[: -len(BIST_EQUITY_SERIES_SUFFIX)]
    if not base or "." in base:
        return None
    return normalize_symbol(base)


def parse_thb_csv(
    text: str,
    *,
    source_file: str,
    source_url: str,
) -> BistThbBulletin:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty_bist_thb_csv")
    header_idx, field_index = _select_header(lines)
    quotes: Dict[str, BistEodQuote] = {}
    rejected: Dict[str, str] = {}
    trading_date: Optional[date] = None
    for line in lines[header_idx + 1 :]:
        if _is_header_line(line):
            continue
        row = _parse_data_row(line, field_index)
        if row is None:
            continue
        series = str(row.get("series") or "").strip().upper()
        group = str(row.get("group") or "").strip().upper()
        canonical = canonical_from_equity_series(series)
        parsed_date = _parse_trade_date(row.get("trade_date") or "")
        if parsed_date is not None:
            trading_date = parsed_date
        if group != BIST_EQUITY_INSTRUMENT_GROUP or canonical is None:
            continue
        quote = _quote_from_row(row, source_file=source_file, source_url=source_url)
        if quote is None:
            rejected[canonical] = "invalid_or_missing_closing_price"
            continue
        quotes[quote.canonical_symbol] = quote
    if trading_date is None:
        raise ValueError("bist_thb_csv_has_no_equity_rows")
    return BistThbBulletin(
        trading_date=trading_date,
        source_file=source_file,
        source_url=source_url,
        quotes=quotes,
        rejected=rejected,
    )


def lookup_equity_close(bulletin: BistThbBulletin, canonical_symbol: str) -> Optional[BistEodQuote]:
    return bulletin.quotes.get(normalize_symbol(canonical_symbol))


def download_thb_zip(
    trading_date: date,
    *,
    opener: Callable[..., object] = urlopen,
    timeout: int = 30,
) -> bytes:
    url = thb_download_url(trading_date)
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as exc:
        raise BistThbDownloadError(
            f"bist_thb_http_{exc.code}",
            status_code=int(exc.code),
        ) from exc
    except URLError as exc:
        raise BistThbDownloadError("bist_thb_network_error") from exc
    if not payload:
        raise BistThbDownloadError("bist_thb_empty_download")
    return payload


def unzip_thb_csv(payload: bytes, trading_date: date) -> str:
    expected = thb_member_name(trading_date)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        chosen = expected if expected in names else next(
            (name for name in names if name.lower().endswith(".csv")),
            None,
        )
        if chosen is None:
            raise BistThbDownloadError("bist_thb_zip_missing_csv")
        raw = archive.read(chosen)
    for encoding in ("utf-8-sig", "utf-8", "cp1254", "iso-8859-9", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def load_thb_bulletin(
    trading_date: date,
    *,
    opener: Callable[..., object] = urlopen,
    timeout: int = 30,
) -> BistThbBulletin:
    payload = download_thb_zip(trading_date, opener=opener, timeout=timeout)
    text = unzip_thb_csv(payload, trading_date)
    return parse_thb_csv(
        text,
        source_file=thb_member_name(trading_date),
        source_url=thb_download_url(trading_date),
    )


def resolve_latest_thb_bulletin(
    *,
    as_of: Optional[date] = None,
    opener: Callable[..., object] = urlopen,
    timeout: int = 30,
    max_trading_days: int = DEFAULT_LOOKBACK_TRADING_DAYS,
) -> BistThbBulletin:
    last_error: Optional[Exception] = None
    for trading_date in candidate_trading_dates(
        as_of or istanbul_today(),
        max_trading_days=max_trading_days,
    ):
        try:
            return load_thb_bulletin(
                trading_date,
                opener=opener,
                timeout=timeout,
            )
        except BistThbDownloadError as exc:
            last_error = exc
            if exc.status_code == 404:
                continue
            raise
    raise BistThbDownloadError(
        "bist_thb_bulletin_not_found",
        status_code=getattr(last_error, "status_code", None),
    )


class BorsaIstanbulThbClient:
    def __init__(
        self,
        *,
        opener: Callable[..., object] = urlopen,
        timeout: int = 30,
        as_of: Optional[date] = None,
    ) -> None:
        self._opener = opener
        self._timeout = timeout
        self._as_of = as_of
        self._bulletin: Optional[BistThbBulletin] = None
        self.downloads = 0

    def load(self) -> BistThbBulletin:
        if self._bulletin is None:
            self.downloads += 1
            self._bulletin = resolve_latest_thb_bulletin(
                as_of=self._as_of,
                opener=self._opener,
                timeout=self._timeout,
            )
        return self._bulletin


def _norm_header(name: str) -> str:
    return " ".join(str(name or "").strip().upper().split())


def _is_header_line(line: str) -> bool:
    first = _norm_header(line.split(";", 1)[0])
    return first in {"TARIH", "TRADE DATE"}


def _header_aliases(cells: Iterable[str]) -> Dict[str, int]:
    aliases: Dict[str, int] = {}
    for idx, raw in enumerate(cells):
        key = _norm_header(raw)
        mapped = _EN_ALIASES.get(key) or _TR_ALIASES.get(key)
        if mapped and mapped not in aliases:
            aliases[mapped] = idx
    return aliases


def _select_header(lines: List[str]) -> tuple[int, Dict[str, int]]:
    scored: List[tuple[int, int, Dict[str, int]]] = []
    for idx, line in enumerate(lines[:4]):
        aliases = _header_aliases(line.split(";"))
        if "close" in aliases and "series" in aliases:
            prefer_en = 1 if "CLOSING PRICE" in _norm_header(line) else 0
            scored.append((prefer_en, idx, aliases))
    if not scored:
        raise ValueError("bist_thb_closing_price_header_missing")
    scored.sort(reverse=True)
    _, header_idx, aliases = scored[0]
    return header_idx, aliases


def _parse_data_row(line: str, field_index: Dict[str, int]) -> Optional[Dict[str, str]]:
    cells = line.split(";")
    required = ("trade_date", "series", "group", "close")
    if any(field_index.get(name, -1) >= len(cells) for name in required):
        return None
    row = {}
    for name, idx in field_index.items():
        row[name] = cells[idx].strip() if idx < len(cells) else ""
    return row


def _optional_float(raw: Optional[str]) -> Optional[float]:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value:
        return None
    return value


def _required_close(raw: Optional[str]) -> Optional[float]:
    value = _optional_float(raw)
    if value is None or value <= 0:
        return None
    return value


def _parse_trade_date(raw: str) -> Optional[date]:
    text = str(raw or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _quote_from_row(
    row: Dict[str, str],
    *,
    source_file: str,
    source_url: str,
) -> Optional[BistEodQuote]:
    series = str(row.get("series") or "").strip().upper()
    group = str(row.get("group") or "").strip().upper()
    if group != BIST_EQUITY_INSTRUMENT_GROUP:
        return None
    canonical = canonical_from_equity_series(series)
    if canonical is None:
        return None
    trading_date = _parse_trade_date(row.get("trade_date") or "")
    closing_price = _required_close(row.get("close"))
    if trading_date is None or closing_price is None:
        return None
    return BistEodQuote(
        canonical_symbol=canonical,
        instrument_series=series,
        trading_date=trading_date,
        closing_price=closing_price,
        currency=normalize_currency(BIST_EQUITY_CURRENCY),
        official_field=OFFICIAL_EOD_FIELD,
        source_file=source_file,
        source_url=source_url,
        previous_close=_optional_float(row.get("previous_close")),
        volume=_optional_float(row.get("volume")),
        vwap=_optional_float(row.get("vwap")),
        corporate_action=str(row.get("corporate_action") or "").strip(),
        reference_price=_optional_float(row.get("reference_price")),
    )
