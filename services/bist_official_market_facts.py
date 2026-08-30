"""Official Borsa Istanbul market facts for existing SecurityFacts.

Public unauthenticated Borsa files only. No paid DataStore. No invented
share counts. No issued-capital-as-shares assumption.

Company-level market cap is not present in the public consolidated files
audited in BIST-1K. Official THB EOD exposes per-security close price.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from services.bist_eod_bulletin import (
    BIST_EQUITY_CURRENCY,
    DEFAULT_LOOKBACK_TRADING_DAYS,
    OFFICIAL_EOD_FIELD,
    BistEodQuote,
    BistThbBulletin,
    candidate_trading_dates,
    lookup_equity_close,
    official_equity_series,
)
from services.bist_symbol_mapping import normalize_bist_symbol


SOURCE_IDENTITY = "BORSA_ISTANBUL"
SOURCE_THB = "borsa_istanbul_thb"
SOURCE_DATASET_THB = "thb"
CURRENCY_TRY = BIST_EQUITY_CURRENCY

CLASS_DIRECT_OFFICIAL = "DIRECT_OFFICIAL"
CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS = "DERIVED_FROM_OFFICIAL_COMPONENTS"
CLASS_OFFICIAL_SOURCE_AVAILABLE_NOT_INGESTED = "OFFICIAL_SOURCE_AVAILABLE_NOT_INGESTED"
CLASS_NOT_AVAILABLE = "NOT_AVAILABLE"
CLASS_METHODOLOGY_UNRESOLVED = "METHODOLOGY_UNRESOLVED"
CLASS_INDEX_OR_MARKET_TOTAL = "INDEX_OR_MARKET_TOTAL"
SHARE_COUNT_METHODOLOGY_UNRESOLVED = "SHARE_COUNT_METHODOLOGY_UNRESOLVED"

SHARE_COUNT_DECISION_DIRECT_MARKET_CAP = "A"
SHARE_COUNT_DECISION_OFFICIAL_SHARES = "B"
SHARE_COUNT_DECISION_NOT_NEEDED = "C"
SHARE_COUNT_DECISION_BLOCKED = "D"

# Official public catalog: https://www.borsaistanbul.com/files/DataFilePaths.zip
# File inside: VerilerDosyaIsimleri.xlsx
OFFICIAL_PUBLIC_PRICE_FILE = {
    "name": "Bülten Verileri / Bulletin Data",
    "directory": "/data/thb/{YYYY}/{MM}/",
    "file": "thb{YYYYMMDD}1.zip",
    "url_template": "https://borsaistanbul.com/data/thb/{year}/{month}/thb{stamp}1.zip",
    "per_security_columns": (
        "INSTRUMENT SERIES CODE / ISLEM KODU",
        "CLOSING PRICE / KAPANIS FIYATI",
        "TRADE DATE / TARIH",
        "TOTAL TRADED VALUE / TOPLAM ISLEM HACMI",
        "TOTAL TRADED VOLUME / TOPLAM ISLEM ADEDI",
    ),
    "market_cap_column": None,
    "share_count_column": None,
    "public": True,
    "authentication": False,
}

OFFICIAL_PUBLIC_MARKET_CAP_TOTALS = {
    "name": "Piyasa Değerleri / Market Capitalization",
    "directory": "/datum/",
    "file": "toppiydeg.zip",
    "url": "https://www.borsaistanbul.com/datum/toppiydeg.zip",
    "inner_file": "hisse_piyasa_degeri_tur.csv",
    "columns": (
        "Tarih",
        "Ulusal Pazar (Milyon TL)",
        "Ulusal Pazar (Milyon ABD$)",
        "Toplam (Milyon TL)",
        "Toplam (Milyon ABD$)",
        "Fiyat Kazanç Oranı (TL)",
        "Temettü Verimi Oranı (%)",
    ),
    "per_security": False,
    "public": True,
    "authentication": False,
}

OFFICIAL_PUBLIC_SEGMENT_MARKET_CAP = {
    "name": "Pay Piyasası Piyasa Değerleri",
    "directory": "/datum/",
    "file": "TR_PP_PiyasaDegeri.zip",
    "url": "https://www.borsaistanbul.com/datum/TR_PP_PiyasaDegeri.zip",
    "note": "Month-end totals by market segment (Yıldız/Ana/Toplam). Not per security.",
    "per_security": False,
    "public": True,
    "authentication": False,
}

PAID_OR_CREDENTIALED = {
    "datastore": "https://datastore.borsaistanbul.com/",
    "vendor_pay_bulten": "PAY_BULTEN_YYYYMMDD.csv (contracted data distributors)",
}

THB_NON_MARKET_CAP_FIELDS = frozenset(
    {
        "TOTAL TRADED VALUE",
        "TOPLAM ISLEM HACMI",
        "TOTAL TRADED VOLUME",
        "TOPLAM ISLEM ADEDI",
        "VWAP",
        "A.O.F",
    }
)


@dataclass(frozen=True)
class BistOfficialMarketFacts:
    symbol: str
    price: Optional[float] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    currency: str = CURRENCY_TRY
    market_date: Optional[date] = None
    source: str = SOURCE_IDENTITY
    source_dataset: str = ""
    source_url: str = ""
    source_file: str = ""
    observed_at: Optional[str] = None
    calculation_basis: str = ""
    price_classification: str = CLASS_NOT_AVAILABLE
    market_cap_classification: str = CLASS_NOT_AVAILABLE
    share_count_classification: str = SHARE_COUNT_METHODOLOGY_UNRESOLVED
    stale: bool = False
    official_field: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "market_cap": self.market_cap,
            "shares_outstanding": self.shares_outstanding,
            "currency": self.currency,
            "market_date": self.market_date.isoformat() if self.market_date else None,
            "source": self.source,
            "source_dataset": self.source_dataset,
            "source_url": self.source_url,
            "source_file": self.source_file,
            "observed_at": self.observed_at,
            "calculation_basis": self.calculation_basis,
            "price_classification": self.price_classification,
            "market_cap_classification": self.market_cap_classification,
            "share_count_classification": self.share_count_classification,
            "stale": self.stale,
            "official_field": self.official_field,
            "notes": list(self.notes),
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def require_bist_symbol(symbol: str) -> str:
    canonical = normalize_bist_symbol(symbol)
    if not canonical:
        raise ValueError(f"bist_official_market_facts_us_or_unknown_symbol:{symbol}")
    return canonical


def thb_headers_include_market_cap(headers: Iterable[str]) -> bool:
    normalized = {" ".join(str(item or "").strip().upper().split()) for item in headers}
    blocked = {
        "MARKET CAP",
        "MARKET CAPITALIZATION",
        "PIYASA DEGERI",
        "PİYASA DEĞERİ",
        "SHARES OUTSTANDING",
        "PAY ADEDI",
        "PAY ADEDİ",
        "LISTED SHARES",
        "FREE FLOAT",
        "FIILI DOLASIM",
        "FİİLİ DOLAŞIM",
    }
    return bool(normalized & blocked)


def classify_official_table(
    *,
    headers: Iterable[str],
    has_symbol_column: bool,
    title: str = "",
) -> str:
    """Distinguish per-security facts from index/market totals."""
    header_text = " ".join(str(item or "") for item in headers).upper()
    title_text = str(title or "").upper()
    total_markers = (
        "TOPLAM (MİLYON",
        "TOPLAM (MILYON",
        "TOPLAM PIYASA",
        "YILDIZ PAZAR PIYASA",
        "ANA PAZAR PIYASA",
        "ULUSAL PAZAR (MILYON",
        "ULUSAL PAZAR (MİLYON",
        "TOPLAM PIYASA DEGERI",
    )
    if any(marker in header_text or marker in title_text for marker in total_markers):
        return CLASS_INDEX_OR_MARKET_TOTAL
    if has_symbol_column and thb_headers_include_market_cap(headers):
        return CLASS_DIRECT_OFFICIAL
    if has_symbol_column:
        return CLASS_NOT_AVAILABLE
    return CLASS_INDEX_OR_MARKET_TOTAL


def parse_official_total_market_cap_csv(text: str) -> dict[str, object]:
    """Parse Borsa toppiydeg / Pay Piyasası Piyasa Değeri totals file."""
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    title = lines[0].strip() if lines else ""
    header_line = ""
    for line in lines[:4]:
        if "Tarih" in line or "TARIH" in line.upper():
            header_line = line
            break
    headers = [cell.strip() for cell in header_line.split(";")] if header_line else []
    symbol_headers = {"ISLEM KODU", "INSTRUMENT SERIES CODE", "PAY KODU", "SEMBOL"}
    has_symbol = any(cell.upper() in symbol_headers for cell in headers)
    classification = classify_official_table(
        headers=headers,
        has_symbol_column=has_symbol,
        title=title,
    )
    return {
        "title": title,
        "headers": headers,
        "per_security": False,
        "has_symbol_column": has_symbol,
        "classification": classification,
        "source_file": OFFICIAL_PUBLIC_MARKET_CAP_TOTALS["inner_file"],
        "source_url": OFFICIAL_PUBLIC_MARKET_CAP_TOTALS["url"],
    }


def classify_share_count_evidence(
    *,
    share_quantity: Optional[float] = None,
    share_quantity_source: str = "",
    issued_capital_money: Optional[float] = None,
    issued_capital_source: str = "",
    nominal_value_per_share: Optional[float] = None,
    nominal_value_source: str = "",
    assume_one_try_nominal: bool = False,
) -> dict[str, object]:
    """Derive shares only from explicit official quantity or capital+nominal."""
    del assume_one_try_nominal  # never used; 1 TRY nominal is not assumed
    if share_quantity is not None and share_quantity > 0 and share_quantity_source:
        return {
            "shares_outstanding": float(share_quantity),
            "classification": CLASS_DIRECT_OFFICIAL,
            "basis": "official_share_quantity",
        }
    if (
        issued_capital_money is not None
        and issued_capital_money > 0
        and issued_capital_source
        and nominal_value_per_share is not None
        and nominal_value_per_share > 0
        and nominal_value_source
    ):
        try:
            capital = Decimal(str(issued_capital_money))
            nominal = Decimal(str(nominal_value_per_share))
            shares = capital / nominal
        except (InvalidOperation, ZeroDivisionError):
            return {
                "shares_outstanding": None,
                "classification": SHARE_COUNT_METHODOLOGY_UNRESOLVED,
                "basis": "",
            }
        if shares <= 0 or shares != shares.to_integral_value():
            return {
                "shares_outstanding": None,
                "classification": SHARE_COUNT_METHODOLOGY_UNRESOLVED,
                "basis": "",
            }
        return {
            "shares_outstanding": float(shares),
            "classification": CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS,
            "basis": "official_issued_capital_divided_by_official_nominal",
        }
    return {
        "shares_outstanding": None,
        "classification": SHARE_COUNT_METHODOLOGY_UNRESOLVED,
        "basis": "",
    }


def derive_market_cap_from_official_components(
    *,
    official_price: Optional[float],
    official_shares: Optional[float],
    price_source: str,
    shares_source: str,
    share_classification: str,
) -> dict[str, object]:
    """price × shares only after both components are official and explicit."""
    allowed = {CLASS_DIRECT_OFFICIAL, CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS}
    if share_classification not in allowed:
        return {
            "market_cap": None,
            "classification": CLASS_NOT_AVAILABLE,
            "calculation_basis": "",
        }
    if (
        official_price is None
        or official_shares is None
        or official_price <= 0
        or official_shares <= 0
        or not price_source
        or not shares_source
    ):
        return {
            "market_cap": None,
            "classification": CLASS_NOT_AVAILABLE,
            "calculation_basis": "",
        }
    return {
        "market_cap": float(official_price) * float(official_shares),
        "classification": CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS,
        "calculation_basis": "official_close_price * official_share_count",
    }


def market_data_is_stale(
    market_date: Optional[date],
    *,
    as_of: Optional[date] = None,
    max_trading_days: int = DEFAULT_LOOKBACK_TRADING_DAYS,
) -> bool:
    if market_date is None or as_of is None:
        return False
    if market_date > as_of:
        return True
    accepted = set(candidate_trading_dates(as_of, max_trading_days=max_trading_days))
    return market_date not in accepted


def market_facts_from_thb_quote(
    quote: BistEodQuote,
    *,
    as_of: Optional[date] = None,
    observed_at: Optional[str] = None,
) -> BistOfficialMarketFacts:
    symbol = require_bist_symbol(quote.canonical_symbol)
    notes = (
        "THB has official close price only. TOTAL TRADED VALUE/VOLUME are not market cap or shares.",
        "Public Borsa consolidated market-cap files are market/segment totals, not per security.",
    )
    return BistOfficialMarketFacts(
        symbol=symbol,
        price=float(quote.closing_price),
        market_cap=None,
        shares_outstanding=None,
        currency=quote.currency or CURRENCY_TRY,
        market_date=quote.trading_date,
        source=SOURCE_IDENTITY,
        source_dataset=SOURCE_DATASET_THB,
        source_url=quote.source_url,
        source_file=quote.source_file,
        observed_at=observed_at or _utc_now_iso(),
        calculation_basis="",
        price_classification=CLASS_DIRECT_OFFICIAL,
        market_cap_classification=CLASS_NOT_AVAILABLE,
        share_count_classification=SHARE_COUNT_METHODOLOGY_UNRESOLVED,
        stale=market_data_is_stale(quote.trading_date, as_of=as_of),
        official_field=quote.official_field or OFFICIAL_EOD_FIELD,
        notes=notes,
    )


def market_facts_from_thb_bulletin(
    bulletin: BistThbBulletin,
    symbol: str,
    *,
    as_of: Optional[date] = None,
    observed_at: Optional[str] = None,
) -> BistOfficialMarketFacts:
    canonical = require_bist_symbol(symbol)
    quote = lookup_equity_close(bulletin, canonical)
    if quote is None:
        return BistOfficialMarketFacts(
            symbol=canonical,
            currency=CURRENCY_TRY,
            market_date=bulletin.trading_date,
            source=SOURCE_IDENTITY,
            source_dataset=SOURCE_DATASET_THB,
            source_url=bulletin.source_url,
            source_file=bulletin.source_file,
            observed_at=observed_at or _utc_now_iso(),
            price_classification=CLASS_NOT_AVAILABLE,
            market_cap_classification=CLASS_NOT_AVAILABLE,
            share_count_classification=SHARE_COUNT_METHODOLOGY_UNRESOLVED,
            stale=market_data_is_stale(bulletin.trading_date, as_of=as_of),
            notes=("symbol_not_in_official_thb_equity_series",),
        )
    return market_facts_from_thb_quote(quote, as_of=as_of, observed_at=observed_at)


def share_count_decision(*, market_cap_classification: str, share_count_classification: str) -> str:
    if market_cap_classification == CLASS_DIRECT_OFFICIAL:
        return SHARE_COUNT_DECISION_DIRECT_MARKET_CAP
    if share_count_classification in {
        CLASS_DIRECT_OFFICIAL,
        CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS,
    }:
        return SHARE_COUNT_DECISION_OFFICIAL_SHARES
    if market_cap_classification == CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS:
        return SHARE_COUNT_DECISION_OFFICIAL_SHARES
    return SHARE_COUNT_DECISION_BLOCKED


def official_eod_series(symbol: str) -> str:
    return official_equity_series(require_bist_symbol(symbol))


def canonical_multiple_readiness(
    *,
    price: Optional[float],
    market_cap: Optional[float],
    eps: Optional[float],
    revenue: Optional[float],
    equity: Optional[float],
) -> dict[str, dict[str, object]]:
    """Existing SecurityFacts formulas. No BIST-only family."""
    pe_ready = price is not None and eps not in (None, 0)
    ps_ready = market_cap is not None and revenue not in (None, 0)
    pb_ready = market_cap is not None and equity not in (None, 0)
    return {
        "pe": {
            "status": "READY" if pe_ready else "BLOCKED",
            "formula": "PRICE_OVER_FY_EPS",
            "numerator": price,
            "denominator": eps,
        },
        "price_to_sales": {
            "status": "READY" if ps_ready else "BLOCKED",
            "formula": "MCAP_OVER_FY_REVENUE",
            "numerator": market_cap,
            "denominator": revenue,
        },
        "price_to_book": {
            "status": "READY" if pb_ready else "BLOCKED",
            "formula": "MCAP_OVER_FY_EQUITY",
            "numerator": market_cap,
            "denominator": equity,
        },
    }

