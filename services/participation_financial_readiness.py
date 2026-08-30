"""Read-only Participation financial-input readiness. No verdicts.

Audits existing methodology and classifies public BIST/KAP components
without inventing AAOIFI or NPR rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from services.kap_financial_bridge import (
    PARTICIPATION_MISSING_REQUIRED,
    PARTICIPATION_SUPPORTED_FROM_KAP,
    participation_inputs_from_kap,
    participation_inputs_from_kap_period,
)
from services.kap_financial_contract import KapNormalizedBundle
from services.kap_financial_normalization import fy_facts_only, period_compatibility
from services.kap_public_contract import KapPublicFinancialDocument
from services.security_intelligence_contract import PERIOD_INCOMPATIBLE as PERIOD_INCOMPATIBLE_KIND


STATUS_VALUE_AVAILABLE = "VALUE_AVAILABLE"
STATUS_DERIVED_SAFE = "DERIVED_SAFE"
STATUS_DATA_MISSING = "DATA_MISSING"
STATUS_METHODOLOGY_UNRESOLVED = "METHODOLOGY_UNRESOLVED"
STATUS_PERIOD_INCOMPATIBLE = "PERIOD_INCOMPATIBLE"

INCLUDED_BY_EXISTING_METHOD = "INCLUDED_BY_EXISTING_METHOD"
EXCLUDED_BY_EXISTING_METHOD = "EXCLUDED_BY_EXISTING_METHOD"
AMBIGUOUS = "AMBIGUOUS"
NOT_RELEVANT = "NOT_RELEVANT"

# Existing SEC IFRS AR precedence. Current only. First tag wins. No noncurrent.
EXISTING_IFRS_AR_TAGS = (
    "CurrentTradeReceivables",
    "TradeReceivables",
    "TradeAndOtherCurrentReceivables",
)
EXISTING_US_GAAP_AR_TAGS = (
    "AccountsReceivableNetCurrent",
    "AccountsReceivableNet",
)

# Existing SEC IFRS tags used for total_debt, not interest_bearing_debt.
EXISTING_IFRS_TOTAL_DEBT_TAGS = (
    "CurrentPortionOfLongtermBorrowings",
    "ShorttermBorrowings",
    "LongtermBorrowings",
)

# Existing SEC IFRS interest-bearing securities tags. Ambiguous for BIST funds/equity.
EXISTING_IFRS_IBS_TAGS = (
    "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
    "FinancialAssetsAtFairValueThroughProfitOrLoss",
    "OtherCurrentFinancialAssets",
)

MSCI_FINANCIAL_REQUIRED = (
    "total_debt",
    "total_assets",
    "cash_and_interest_bearing_securities",
    "accounts_receivable",
    "cash",
    "non_permissible_revenue",
    "total_revenue",
)

DEBT_COMPONENT_RULES = {
    "ifrs-full_LongtermBorrowings": AMBIGUOUS,
    "ifrs-full_CurrentPortionOfLongtermBorrowings": AMBIGUOUS,
    "ifrs-full_ShorttermBorrowings": AMBIGUOUS,
    "kap-fr_CurrentBorrowingsFromRelatedParties": AMBIGUOUS,
    "kap-fr_CurrentBorrowingsFromUnrelatedParties": AMBIGUOUS,
    "kap-fr_CurrentPortionOfNoncurrentBorrowings": AMBIGUOUS,
    "kap-fr_LongTermBorrowingsFromRelatedParties": AMBIGUOUS,
    "kap-fr_LongTermBorrowingsFromUnrelatedParties": AMBIGUOUS,
    "kap-fr_PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities": NOT_RELEVANT,
    "ifrs-full_ProceedsFromBorrowingsClassifiedAsFinancingActivities": NOT_RELEVANT,
    "ifrs-full_RepaymentsOfBorrowingsClassifiedAsFinancingActivities": NOT_RELEVANT,
}

CASH_COMPONENT_RULES = {
    "ifrs-full_CashAndCashEquivalents": INCLUDED_BY_EXISTING_METHOD,
    "ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLoss": AMBIGUOUS,
    "ifrs-full_FinancialAssetsAtFairValueThroughProfitOrLoss": AMBIGUOUS,
    "ifrs-full_CurrentDerivativeFinancialAssets": NOT_RELEVANT,
    "ifrs-full_NoncurrentDerivativeFinancialAssets": NOT_RELEVANT,
    "kap-fr_OtherCurrentFinancialInvestments": AMBIGUOUS,
    "kap-fr_CurrentFinancialAssetsMeasuredAtAmortisedCost": AMBIGUOUS,
    "kap-fr_CurrentFinancialAssetsHeldForTrading": AMBIGUOUS,
}


@dataclass(frozen=True)
class MethodologyFieldAudit:
    field: str
    existing_definition: str
    formula: str
    methodology_explicit: bool
    bist_implementable: bool
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "existing_definition": self.existing_definition,
            "formula": self.formula,
            "methodology_explicit": self.methodology_explicit,
            "bist_implementable": self.bist_implementable,
            "note": self.note,
        }


@dataclass(frozen=True)
class ComponentClassification:
    concept: str
    classification: str
    value: Optional[float] = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "classification": self.classification,
            "value": self.value,
            "note": self.note,
        }


@dataclass(frozen=True)
class ParticipationFinancialReadiness:
    symbol: str
    period: str
    available_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    methodology_unresolved_fields: tuple[str, ...]
    period_incompatible_fields: tuple[str, ...]
    field_status: dict[str, str]
    financial_screen_ready: bool
    limitation: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "period": self.period,
            "available_fields": list(self.available_fields),
            "missing_fields": list(self.missing_fields),
            "methodology_unresolved_fields": list(self.methodology_unresolved_fields),
            "period_incompatible_fields": list(self.period_incompatible_fields),
            "field_status": dict(self.field_status),
            "financial_screen_ready": self.financial_screen_ready,
            "limitation": self.limitation,
            "provenance": dict(self.provenance or {}),
        }


def audit_existing_methodology() -> tuple[MethodologyFieldAudit, ...]:
    return (
        MethodologyFieldAudit(
            field="accounts_receivable",
            existing_definition="SEC IFRS: CurrentTradeReceivables first, then TradeReceivables / TradeAndOtherCurrentReceivables. US-GAAP: AccountsReceivableNetCurrent.",
            formula="MSCI: (accounts_receivable + cash) / total_assets <= entry 46% / constituent 70%",
            methodology_explicit=True,
            bist_implementable=True,
            note="Current only. Noncurrent trade receivables are not in the existing tag list.",
        ),
        MethodologyFieldAudit(
            field="cash_and_interest_bearing_securities",
            existing_definition="cash + interest_bearing_securities only when both exist. IFRS IBS tags are FVTPL / OtherCurrentFinancialAssets.",
            formula="MSCI: cash_and_interest_bearing_securities / total_assets <= 30% entry",
            methodology_explicit=False,
            bist_implementable=False,
            note="Existing IFRS IBS tags can include equity funds. BIST decomposition is not proven.",
        ),
        MethodologyFieldAudit(
            field="interest_bearing_debt",
            existing_definition="Dedicated input. total_debt is never substituted. AAOIFI numerator only.",
            formula="AAOIFI: interest_bearing_debt / market_capitalization. MSCI uses total_debt, not this field.",
            methodology_explicit=False,
            bist_implementable=False,
            note="No existing include-list for KAP borrowings vs leases.",
        ),
        MethodologyFieldAudit(
            field="non_permissible_revenue",
            existing_definition="SEC 10-K inline XBRL revenue attribution / mapped prohibited segments.",
            formula="MSCI: non_permissible_revenue / total_revenue < 5%",
            methodology_explicit=True,
            bist_implementable=False,
            note="No equivalent public BIST/KAP NPR source. 1F segments are unknown.",
        ),
        MethodologyFieldAudit(
            field="market_capitalization",
            existing_definition="External market value. Existing resolver is price × shares_outstanding.",
            formula="AAOIFI denominator. MSCI default does not use market cap.",
            methodology_explicit=True,
            bist_implementable=False,
            note="BIST public price exists. Authoritative share count is not on KAP taxonomy or BIST pricing facts.",
        ),
        MethodologyFieldAudit(
            field="average_market_cap_24m",
            existing_definition="Existing helper: monthly last price × current shares (FMP). Not used if shares missing.",
            formula="DJIM denominator. MSCI default does not use 24m market cap.",
            methodology_explicit=True,
            bist_implementable=False,
            note="FMP is not a free BIST source. No public 24m price+share history in the BIST foundation.",
        ),
    )


def classify_observed_concepts(
    observed: Iterable[str],
    rules: dict[str, str],
    *,
    values: Optional[dict[str, float]] = None,
) -> tuple[ComponentClassification, ...]:
    found: list[ComponentClassification] = []
    have = {str(item) for item in observed}
    for concept, classification in rules.items():
        if concept in have or concept.lower() in {item.lower() for item in have}:
            value = None
            if values:
                value = values.get(concept)
                if value is None:
                    value = values.get(concept.lower())
            found.append(
                ComponentClassification(
                    concept=concept,
                    classification=classification,
                    value=value,
                )
            )
    return tuple(found)


def derive_market_cap(
    *,
    price: Optional[float],
    shares_outstanding: Optional[float],
    price_source: str = "",
    shares_source: str = "",
) -> Optional[float]:
    """price × shares only. No guessed share count."""
    if price is None or shares_outstanding is None:
        return None
    if price <= 0 or shares_outstanding <= 0:
        return None
    if not price_source or not shares_source:
        return None
    return price * shares_outstanding


def derive_average_market_cap_24m(
    *,
    monthly_prices: Optional[Iterable[float]] = None,
    shares_outstanding: Optional[float] = None,
    historical_share_counts: Optional[Iterable[float]] = None,
) -> Optional[float]:
    """Fail-closed. Does not invent average(price) × current shares for BIST."""
    del monthly_prices, shares_outstanding, historical_share_counts
    return None


def field_status_for_pilot(
    *,
    bundle: KapNormalizedBundle,
    document: Optional[KapPublicFinancialDocument] = None,
    price: Optional[float] = None,
    shares_outstanding: Optional[float] = None,
) -> dict[str, str]:
    fy_inputs, _ = participation_inputs_from_kap(bundle)
    ytd_inputs, _ = participation_inputs_from_kap_period(bundle, "YTD")
    fy_has_ar = fy_inputs.accounts_receivable is not None
    ytd_has_ar = ytd_inputs.accounts_receivable is not None
    if fy_has_ar:
        ar_status = STATUS_VALUE_AVAILABLE
    elif ytd_has_ar:
        ar_status = STATUS_VALUE_AVAILABLE
    else:
        ar_status = STATUS_DATA_MISSING

    mcap = derive_market_cap(
        price=price,
        shares_outstanding=shares_outstanding,
        price_source="bist_public_price" if price is not None else "",
        shares_source="authoritative_share_count" if shares_outstanding is not None else "",
    )
    return {
        "accounts_receivable": ar_status,
        "interest_bearing_debt": STATUS_METHODOLOGY_UNRESOLVED,
        "cash_and_interest_bearing_securities": STATUS_METHODOLOGY_UNRESOLVED,
        "non_permissible_revenue": STATUS_METHODOLOGY_UNRESOLVED,
        "market_capitalization": STATUS_DERIVED_SAFE if mcap is not None else STATUS_DATA_MISSING,
        "average_market_cap_24m": STATUS_DATA_MISSING,
    }


def build_participation_financial_readiness(
    bundle: KapNormalizedBundle,
    *,
    document: Optional[KapPublicFinancialDocument] = None,
    price: Optional[float] = None,
    shares_outstanding: Optional[float] = None,
) -> ParticipationFinancialReadiness:
    fy = fy_facts_only(bundle.mapped)
    ytd_inputs, ytd_missing = participation_inputs_from_kap_period(bundle, "YTD")
    fy_inputs, fy_missing = participation_inputs_from_kap(bundle)
    latest_period = "FY" if fy else ("YTD" if ytd_inputs.as_of_date or ytd_inputs.cash or ytd_inputs.accounts_receivable else "")
    latest_inputs = fy_inputs if fy else ytd_inputs
    status = field_status_for_pilot(
        bundle=bundle,
        document=document,
        price=price,
        shares_outstanding=shares_outstanding,
    )
    if fy and (ytd_inputs.accounts_receivable is not None or ytd_inputs.total_revenue is not None):
        if period_compatibility("FY", "YTD") == PERIOD_INCOMPATIBLE_KIND:
            if not fy_inputs.accounts_receivable and ytd_inputs.accounts_receivable:
                status["accounts_receivable"] = STATUS_PERIOD_INCOMPATIBLE

    available = tuple(
        name
        for name in (*PARTICIPATION_SUPPORTED_FROM_KAP, "accounts_receivable")
        if getattr(latest_inputs, name, None) is not None
    )
    unresolved = tuple(
        name
        for name, value in status.items()
        if value == STATUS_METHODOLOGY_UNRESOLVED
    )
    incompatible = tuple(
        name
        for name, value in status.items()
        if value == STATUS_PERIOD_INCOMPATIBLE
    )
    missing = tuple(
        name
        for name in (*PARTICIPATION_MISSING_REQUIRED, "total_debt", "accounts_receivable")
        if getattr(latest_inputs, name, None) is None and name not in unresolved
    )
    screen_ready = all(
        getattr(latest_inputs, name, None) is not None for name in MSCI_FINANCIAL_REQUIRED
    )
    return ParticipationFinancialReadiness(
        symbol=bundle.symbol,
        period=latest_period,
        available_fields=tuple(dict.fromkeys(available)),
        missing_fields=tuple(dict.fromkeys(missing)),
        methodology_unresolved_fields=unresolved,
        period_incompatible_fields=incompatible,
        field_status=status,
        financial_screen_ready=False if not screen_ready else True,
        limitation="READINESS_ONLY_NO_PARTICIPATION_VERDICT",
        provenance={
            "fy_missing": list(fy_missing),
            "ytd_missing": list(ytd_missing),
            "latest_period": latest_period,
        },
    )

