"""Official public KAP capital-structure parse. No pilot hardcoding.

Public company-general pages embed the
"Sermayeyi Temsil Eden Paylara İlişkin Bilgi" table in the unauthenticated
HTML body (Next.js RSC JSON + table cells). Ticker-slug URLs are empty shells;
OID URLs from /tr/bist-sirketler are parseable without auth or paid APIs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from services.bist_symbol_mapping import normalize_bist_symbol


KAP_PUBLIC_HOST = "https://kap.org.tr"
KAP_BIST_COMPANIES_PATH = "/tr/bist-sirketler"
KAP_COMPANY_GENERAL_PATH = "/tr/sirket-bilgileri/genel/{oid}"
KAP_COMPANY_SUMMARY_PATH = "/tr/sirket-bilgileri/ozet/{oid}"

SOURCE_KAP_CAPITAL = "kap_company_general"
TABLE_TITLE = "Sermayeyi Temsil Eden Paylara İlişkin Bilgi"
ISSUED_CAPITAL_ITEM_KEY = "kpy41_acc5_odenmis_sermaye"

ACCESS_PUBLIC_STATIC = "PUBLIC_STATIC"
ACCESS_PUBLIC_RENDERED_BUT_PARSEABLE = "PUBLIC_RENDERED_BUT_PARSEABLE"
ACCESS_NOT_PROGRAMMATICALLY_AVAILABLE = "NOT_PROGRAMMATICALLY_AVAILABLE"

EXCHANGE_TRADED = "exchange_traded"
EXCHANGE_NOT_TRADED = "not_exchange_traded"

_CLASS_RE = re.compile(
    r'"shareGroup"\s*:\s*"(?P<share_class>[^"]*)"'
    r".{0,160}?"
    r'"nominalValuePerShare"\s*:\s*"(?P<nominal_per_share>[^"]+)"'
    r".{0,80}?"
    r'"key"\s*:\s*"(?P<per_share_ccy>[A-Z]{3})"'
    r".{0,80}?"
    r'"nominalValueOfShares"\s*:\s*"(?P<class_total>[^"]+)"'
    r".{0,80}?"
    r'"key"\s*:\s*"(?P<class_ccy>[A-Z]{3})"'
    r".{0,40}?"
    r'"ratioToTotalCapital"\s*:\s*"(?P<pct>[^"]+)"'
    r".{0,240}?"
    r'"exchangeTradedOrNot"\s*:\s*\{\s*"key"\s*:\s*"(?P<traded_key>[^"]+)"'
    r'\s*,\s*"text"\s*:\s*"(?P<traded_text>[^"]+)"',
    re.S,
)
_ISSUED_RE = re.compile(
    r'"itemKey"\s*:\s*"kpy41_acc5_odenmis_sermaye"\s*,\s*"value"\s*:\s*"(?P<value>[^"]+)"',
)
_OID_RE = re.compile(
    r'"mkkMemberOid"\s*:\s*"(?P<oid>[^"]+)"'
    r".{0,500}?"
    r'"stockCode"\s*:\s*"(?P<symbol>[A-Z0-9]{1,8})"',
    re.S,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _unescape_rsc(html: str) -> str:
    text = str(html or "")
    if '\\"' in text:
        text = text.replace('\\"', '"')
    return text


def parse_tr_number(raw: object) -> Optional[Decimal]:
    """Normalize KAP/Borsa numeric text (TRY thousands dots, decimal comma)."""
    text = str(raw or "").strip()
    if not text or text in {"-", "—"}:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    if text.count(".") >= 2 and "," not in text:
        text = text.replace(".", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value.is_nan() or value.is_infinite():
        return None
    return value


def _exchange_flag(key: str, text: str) -> str:
    token = f"{key} {text}".casefold()
    if key == "1" or "görüyor" in token or "goruyor" in token:
        return EXCHANGE_TRADED
    return EXCHANGE_NOT_TRADED


def company_general_url(oid: str) -> str:
    safe = "".join(ch for ch in str(oid or "") if ch.isalnum())
    return f"{KAP_PUBLIC_HOST}{KAP_COMPANY_GENERAL_PATH.format(oid=safe)}"


def classify_public_access(html: str) -> str:
    """Ticker shells are empty; OID genel HTML embeds the table without auth."""
    text = _unescape_rsc(html)
    has_title = TABLE_TITLE in text
    has_rows = bool(_CLASS_RE.search(text))
    if has_title and has_rows:
        return ACCESS_PUBLIC_RENDERED_BUT_PARSEABLE
    if has_title or "sirket-bilgileri" in text.casefold():
        return ACCESS_NOT_PROGRAMMATICALLY_AVAILABLE
    return ACCESS_NOT_PROGRAMMATICALLY_AVAILABLE


def parse_bist_company_oids(html: str) -> dict[str, str]:
    """Map stockCode → mkkMemberOid from the public BIST company list."""
    text = _unescape_rsc(html)
    out: dict[str, str] = {}
    for match in _OID_RE.finditer(text):
        symbol = normalize_bist_symbol(match.group("symbol"))
        oid = match.group("oid").strip()
        if symbol and oid:
            out[symbol] = oid
    return out


def legal_share_count(
    class_total_nominal: Optional[Decimal],
    nominal_value_per_share: Optional[Decimal],
) -> Optional[Decimal]:
    """LEGAL_SHARE_COUNT = class_nominal / nominal_per_legal_share when integral."""
    if (
        class_total_nominal is None
        or nominal_value_per_share is None
        or class_total_nominal <= 0
        or nominal_value_per_share <= 0
    ):
        return None
    try:
        shares = class_total_nominal / nominal_value_per_share
    except (InvalidOperation, ZeroDivisionError):
        return None
    if shares <= 0 or shares != shares.to_integral_value():
        return None
    return shares


@dataclass(frozen=True)
class KapShareClass:
    symbol: str
    share_class: str
    nominal_value_per_share: Optional[Decimal]
    nominal_value_currency: str
    class_total_nominal_value: Optional[Decimal]
    class_total_currency: str
    capital_percentage: Optional[Decimal]
    exchange_traded_flag: str
    source_url: str
    observed_at: str
    legal_share_count: Optional[Decimal] = None

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "share_class": self.share_class,
            "nominal_value_per_share": (
                str(self.nominal_value_per_share) if self.nominal_value_per_share is not None else None
            ),
            "nominal_value_currency": self.nominal_value_currency,
            "class_total_nominal_value": (
                str(self.class_total_nominal_value)
                if self.class_total_nominal_value is not None
                else None
            ),
            "class_total_currency": self.class_total_currency,
            "capital_percentage": (
                str(self.capital_percentage) if self.capital_percentage is not None else None
            ),
            "exchange_traded_flag": self.exchange_traded_flag,
            "source_url": self.source_url,
            "observed_at": self.observed_at,
            "legal_share_count": (
                str(self.legal_share_count) if self.legal_share_count is not None else None
            ),
        }


@dataclass(frozen=True)
class KapCapitalStructure:
    symbol: str
    source_url: str
    observed_at: str
    access_classification: str
    issued_capital: Optional[Decimal] = None
    issued_capital_currency: str = "TRY"
    classes: tuple[KapShareClass, ...] = ()
    class_total_nominal_sum: Optional[Decimal] = None
    total_legal_share_count: Optional[Decimal] = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "source_url": self.source_url,
            "observed_at": self.observed_at,
            "access_classification": self.access_classification,
            "issued_capital": str(self.issued_capital) if self.issued_capital is not None else None,
            "issued_capital_currency": self.issued_capital_currency,
            "classes": [row.to_dict() for row in self.classes],
            "class_total_nominal_sum": (
                str(self.class_total_nominal_sum) if self.class_total_nominal_sum is not None else None
            ),
            "total_legal_share_count": (
                str(self.total_legal_share_count) if self.total_legal_share_count is not None else None
            ),
            "notes": list(self.notes),
        }


def parse_kap_capital_structure_html(
    html: str,
    *,
    symbol: str,
    source_url: str = "",
    observed_at: Optional[str] = None,
) -> KapCapitalStructure:
    canonical = normalize_bist_symbol(symbol)
    if not canonical:
        raise ValueError(f"kap_capital_structure_us_or_unknown_symbol:{symbol}")
    observed = observed_at or _utc_now_iso()
    text = _unescape_rsc(html)
    access = classify_public_access(html)
    url = source_url or ""
    notes: list[str] = []

    issued = None
    issued_match = _ISSUED_RE.search(text)
    if issued_match:
        issued = parse_tr_number(issued_match.group("value"))

    rows: list[KapShareClass] = []
    seen: set[tuple[str, str, str]] = set()
    for match in _CLASS_RE.finditer(text):
        share_class = " ".join(match.group("share_class").split())
        per_share = parse_tr_number(match.group("nominal_per_share"))
        class_total = parse_tr_number(match.group("class_total"))
        pct = parse_tr_number(match.group("pct"))
        key = (share_class, str(per_share), str(class_total))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            KapShareClass(
                symbol=canonical,
                share_class=share_class or "-",
                nominal_value_per_share=per_share,
                nominal_value_currency=match.group("per_share_ccy"),
                class_total_nominal_value=class_total,
                class_total_currency=match.group("class_ccy"),
                capital_percentage=pct,
                exchange_traded_flag=_exchange_flag(
                    match.group("traded_key"),
                    match.group("traded_text"),
                ),
                source_url=url,
                observed_at=observed,
                legal_share_count=legal_share_count(class_total, per_share),
            )
        )

    class_sum = None
    if rows and all(row.class_total_nominal_value is not None for row in rows):
        class_sum = sum((row.class_total_nominal_value or Decimal("0")) for row in rows)
    if issued is not None and class_sum is not None and issued != class_sum:
        notes.append("class_totals_do_not_match_issued_capital")

    total_legal: Optional[Decimal] = None
    class_legals = [row.legal_share_count for row in rows]
    if rows and all(value is not None for value in class_legals):
        total_legal = sum((value or Decimal("0")) for value in class_legals)
        if "class_totals_do_not_match_issued_capital" in notes:
            total_legal = None
            notes.append("total_legal_share_count_unresolved_due_to_issued_mismatch")
    elif (
        issued is not None
        and rows
        and len({row.nominal_value_per_share for row in rows if row.nominal_value_per_share}) == 1
    ):
        nominal = next(row.nominal_value_per_share for row in rows if row.nominal_value_per_share)
        candidate = legal_share_count(issued, nominal)
        if candidate is not None:
            total_legal = candidate
            notes.append("total_legal_share_count_from_issued_capital_and_uniform_nominal")

    if access == ACCESS_PUBLIC_RENDERED_BUT_PARSEABLE:
        notes.append("kap_oid_general_html_parseable_without_auth")
    if not rows:
        notes.append("capital_class_table_not_found")

    return KapCapitalStructure(
        symbol=canonical,
        source_url=url,
        observed_at=observed,
        access_classification=access,
        issued_capital=issued,
        issued_capital_currency="TRY",
        classes=tuple(rows),
        class_total_nominal_sum=class_sum,
        total_legal_share_count=total_legal,
        notes=tuple(notes),
    )
