"""Official Borsa Istanbul equity quotation basis vs KAP legal shares.

Pay Piyasası Prosedürü 5.1.1 and 5.1.5:
  1,00 TL (nominal) = 1 adet = 1 lot
  published price is the market price of a 1 TRY nominal share.

Index / theoretical-price rules convert KAP issued/paid capital through 5.1.1
and compute company market cap as pay_adedi × price over ALL capital.

LEGAL_SHARE_COUNT (class_nominal / legal_nominal_per_share) is not the
quote unit when legal nominal ≠ 1 TRY. Never multiply THB close by raw
legal share count.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from services.kap_capital_structure import KapCapitalStructure


QUOTE_NOMINAL_BASIS_TRY = Decimal("1")
QUOTE_UNIT_NAME = "1_TRY_NOMINAL_UNITS"

SOURCE_PAY_PIYASASI_PROCEDURE = (
    "https://www.borsaistanbul.com/files/pay-piyasasi-proseduru.pdf"
)
SOURCE_INDEX_RULE_ANNEX = (
    "https://www.borsaistanbul.com/files/pay-endeksleri-kural-seti-ek-3.pdf"
)
SOURCE_THEORETICAL_PRICE = (
    "https://www.borsaistanbul.com/files/teorik-fiyatlarin-belirlenmesi-03-04-2026.pdf"
)

LOT_DEFINITION = "1,00 TL (nominal) = 1 adet = 1 lot"
PRICE_BASIS = "published_price_is_for_1_try_nominal_share"
NOMINAL_BASIS = "1.00 TRY"

MARKET_CAP_DECISION_DIRECT_OFFICIAL = "A"
MARKET_CAP_DECISION_NOMINAL_AND_PRICE = "B"
MARKET_CAP_DECISION_LEGAL_AND_PRICE = "C"
MARKET_CAP_DECISION_UNRESOLVED = "D"

CANONICAL_MARKET_CAP_DECISION = MARKET_CAP_DECISION_NOMINAL_AND_PRICE
CALCULATION_BASIS = "official_thb_close * official_issued_capital / 1.00_try_quote_nominal"

STATUS_DERIVED = "DERIVED_FROM_OFFICIAL_NOMINAL_CAPITAL_AND_BORSA_PRICE"
STATUS_UNRESOLVED = "MARKET_CAP_DERIVATION_UNRESOLVED"
STATUS_ABSURD_LEGAL = "REJECTED_PRICE_TIMES_RAW_LEGAL_SHARES"


def official_quotation_contract() -> dict[str, object]:
    return {
        "official_source": SOURCE_PAY_PIYASASI_PROCEDURE,
        "supporting_sources": (SOURCE_INDEX_RULE_ANNEX, SOURCE_THEORETICAL_PRICE),
        "lot_definition": LOT_DEFINITION,
        "price_basis": PRICE_BASIS,
        "nominal_basis": NOMINAL_BASIS,
        "quote_unit": QUOTE_UNIT_NAME,
        "section": "5.1.1 İşlem Birimi (Lot); 5.1.5 Fiyat İlanı",
        "applies_to": "all_equity_and_rights_except_isbank_founder_shares",
        "canonical_decision": CANONICAL_MARKET_CAP_DECISION,
    }


def quote_equivalent_units(issued_capital_try: Optional[Decimal]) -> Optional[Decimal]:
    """Borsa pay adedi = ödenmiş/çıkarılmış sermaye / 1.00 TRY nominal."""
    if issued_capital_try is None or issued_capital_try <= 0:
        return None
    if issued_capital_try.as_tuple().sign:
        return None
    try:
        units = issued_capital_try / QUOTE_NOMINAL_BASIS_TRY
    except (InvalidOperation, ZeroDivisionError):
        return None
    if units <= 0:
        return None
    return units


def quote_equivalent_units_from_structure(
    structure: KapCapitalStructure,
) -> Optional[Decimal]:
    if structure.issued_capital_currency != "TRY":
        return None
    return quote_equivalent_units(structure.issued_capital)


def derive_market_cap_from_official_nominal_capital_and_price(
    *,
    official_price: Optional[float],
    issued_capital_try: Optional[Decimal],
    price_source: str,
    capital_source: str,
    price_currency: str = "TRY",
) -> dict[str, object]:
    """Generic B: THB close × (issued capital / 1.00 TRY). No legal-share path."""
    units = quote_equivalent_units(issued_capital_try)
    if (
        official_price is None
        or official_price <= 0
        or units is None
        or not price_source
        or not capital_source
        or price_currency != "TRY"
    ):
        return {
            "market_cap": None,
            "quote_equivalent_units": float(units) if units is not None else None,
            "classification": STATUS_UNRESOLVED,
            "calculation_basis": "",
            "decision": MARKET_CAP_DECISION_UNRESOLVED,
        }
    market_cap = (Decimal(str(official_price)) * units).quantize(Decimal("0.01"))
    return {
        "market_cap": float(market_cap),
        "quote_equivalent_units": float(units),
        "classification": STATUS_DERIVED,
        "calculation_basis": CALCULATION_BASIS,
        "decision": MARKET_CAP_DECISION_NOMINAL_AND_PRICE,
    }


def reject_price_times_legal_shares(
    *,
    official_price: Optional[float],
    legal_share_count: Optional[Decimal],
    quote_units: Optional[Decimal],
) -> dict[str, object]:
    """Guard: never treat legal shares as the Borsa quote unit."""
    if (
        official_price is None
        or official_price <= 0
        or legal_share_count is None
        or legal_share_count <= 0
    ):
        return {
            "allowed": False,
            "status": STATUS_UNRESOLVED,
            "absurd_multiple": None,
        }
    if quote_units is None or quote_units <= 0:
        return {
            "allowed": False,
            "status": STATUS_ABSURD_LEGAL,
            "absurd_multiple": None,
        }
    multiple = legal_share_count / quote_units
    return {
        "allowed": False,
        "status": STATUS_ABSURD_LEGAL,
        "absurd_multiple": float(multiple),
        "legal_implied_market_cap": float(Decimal(str(official_price)) * legal_share_count),
        "quote_implied_market_cap": float(Decimal(str(official_price)) * quote_units),
    }


def canonical_market_cap_decision() -> str:
    return CANONICAL_MARKET_CAP_DECISION
