"""Official SP Funds / TidalFG holdings client.

Parses issuer CSV facts only. Does not classify instrument type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from urllib.request import Request, urlopen

from services.universe_listing_identity import listing_identity

SOURCE_SP_FUNDS_OFFICIAL = "sp_funds_official"
SUPPORTED_OFFICIAL_FUNDS = ("SPUS", "SPSK", "SPRE", "SPWO")
HOLDINGS_URL_TEMPLATE = (
    "https://www.sp-funds.com/wp-content/uploads/data/TidalFG_Holdings_{symbol}.csv"
)
REQUIRED_COLUMNS = (
    "Date",
    "Account",
    "StockTicker",
    "CUSIP",
    "SecurityName",
    "Weightings",
)
MATERIAL_WEIGHT_MAX_PCT = 100.50
MATERIAL_WEIGHT_MIN_PCT = 95.0


class OfficialHoldingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class OfficialHolding:
    fund_symbol: str
    as_of: date
    ticker: str
    cusip_raw: str
    security_name: str
    weight_pct: float
    shares: Optional[float] = None
    price: Optional[float] = None
    market_value: Optional[float] = None
    net_assets: Optional[float] = None
    shares_outstanding: Optional[float] = None
    source: str = SOURCE_SP_FUNDS_OFFICIAL
    source_reference: str = ""
    asset_type: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def holding_identifier(self) -> str:
        listed = listing_identity(self.ticker)
        if listed:
            return listed
        cusip = str(self.cusip_raw or "").strip().upper()
        if cusip:
            return cusip
        return str(self.ticker or "").strip().upper()


@dataclass(frozen=True)
class OfficialHoldingsFile:
    fund_symbol: str
    as_of: date
    source: str
    source_reference: str
    http_status: int
    holdings: tuple[OfficialHolding, ...]
    parse_failures: int
    raw_columns: tuple[str, ...]


def official_holdings_url(symbol: str) -> str:
    return HOLDINGS_URL_TEMPLATE.format(symbol=str(symbol or "").strip().upper())


def parse_weight_pct(raw: Any) -> Optional[float]:
    text = str(raw or "").strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_optional_number(raw: Any) -> Optional[float]:
    text = str(raw or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_issuer_date(raw: Any) -> Optional[date]:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_official_holdings_csv(
    text: str,
    *,
    fund_symbol: str,
    source_reference: str = "",
    http_status: int = 200,
) -> OfficialHoldingsFile:
    import csv
    import io

    symbol = str(fund_symbol or "").strip().upper()
    if symbol not in SUPPORTED_OFFICIAL_FUNDS:
        raise OfficialHoldingsError(f"unsupported official fund: {fund_symbol}")
    sample = (text or "")[:2048]
    if not sample.strip():
        raise OfficialHoldingsError("empty official holdings file")
    reader = csv.DictReader(io.StringIO(text))
    columns = tuple(reader.fieldnames or ())
    missing = [col for col in REQUIRED_COLUMNS if col not in columns]
    if missing:
        raise OfficialHoldingsError(f"official holdings schema changed; missing {missing}")

    holdings: list[OfficialHolding] = []
    failures = 0
    as_of: Optional[date] = None
    for row in reader:
        account = str(row.get("Account") or "").strip().upper()
        if account and account != symbol:
            raise OfficialHoldingsError(
                f"official holdings account {account} does not match {symbol}"
            )
        row_date = parse_issuer_date(row.get("Date"))
        if row_date is None:
            failures += 1
            continue
        if as_of is None:
            as_of = row_date
        elif row_date != as_of:
            raise OfficialHoldingsError("official holdings file has mixed as-of dates")
        ticker = str(row.get("StockTicker") or "").strip()
        cusip = str(row.get("CUSIP") or "").strip()
        name = str(row.get("SecurityName") or "").strip()
        weight = parse_weight_pct(row.get("Weightings"))
        if (not ticker and not cusip) or weight is None:
            failures += 1
            continue
        holdings.append(
            OfficialHolding(
                fund_symbol=symbol,
                as_of=row_date,
                ticker=ticker,
                cusip_raw=cusip,
                security_name=name,
                weight_pct=weight,
                shares=parse_optional_number(row.get("Shares")),
                price=parse_optional_number(row.get("Price")),
                market_value=parse_optional_number(row.get("MarketValue")),
                net_assets=parse_optional_number(row.get("NetAssets")),
                shares_outstanding=parse_optional_number(row.get("SharesOutstanding")),
                source_reference=source_reference or official_holdings_url(symbol),
                metadata={"issuer_columns": {key: row.get(key) for key in columns}},
            )
        )
    if as_of is None or not holdings:
        raise OfficialHoldingsError("official holdings file produced no usable rows")
    return OfficialHoldingsFile(
        fund_symbol=symbol,
        as_of=as_of,
        source=SOURCE_SP_FUNDS_OFFICIAL,
        source_reference=source_reference or official_holdings_url(symbol),
        http_status=http_status,
        holdings=tuple(holdings),
        parse_failures=failures,
        raw_columns=columns,
    )


class OfficialFundHoldingsClient:
    def __init__(self, *, timeout: int = 30, user_agent: str = "") -> None:
        self.timeout = timeout
        self.user_agent = user_agent or (
            "NABI Scout investment research app official-holdings/1.0"
        )

    def fetch(self, symbol: str) -> OfficialHoldingsFile:
        fund = str(symbol or "").strip().upper()
        if fund not in SUPPORTED_OFFICIAL_FUNDS:
            raise OfficialHoldingsError(f"unsupported official fund: {symbol}")
        url = official_holdings_url(fund)
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            raw = response.read()
        if status != 200:
            raise OfficialHoldingsError(f"official holdings HTTP {status} for {fund}")
        text = raw.decode("utf-8-sig")
        return parse_official_holdings_csv(
            text,
            fund_symbol=fund,
            source_reference=url,
            http_status=status,
        )
