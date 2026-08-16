from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

from services.wealth_contract import (
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    ASSET_CLASS_ETF,
    ASSET_CLASS_FUND,
    ASSET_CLASS_OTHER,
)

ASSET_CLASS_GOLD = "gold"
ASSET_CLASS_SUKUK = "sukuk"
ASSET_CLASS_PRECIOUS_METAL = "precious_metal"
ASSET_CLASS_FIXED_INCOME = "fixed_income"

WAVE4_ASSET_CLASSES = frozenset({
    ASSET_CLASS_EQUITY,
    ASSET_CLASS_ETF,
    ASSET_CLASS_FUND,
    ASSET_CLASS_CASH,
    ASSET_CLASS_GOLD,
    ASSET_CLASS_PRECIOUS_METAL,
    ASSET_CLASS_SUKUK,
    ASSET_CLASS_FIXED_INCOME,
    ASSET_CLASS_OTHER,
})

PRICING_CANDIDATE_SNAPSHOT = "candidate_snapshot"
PRICING_MANUAL = "manual"
PRICING_FUND_NAV = "fund_nav"
PRICING_UNSUPPORTED = "unsupported"
PRICING_NOMINAL_CASH = "nominal_cash"

RESEARCH_EQUITY = "equity_research"
RESEARCH_FUND = "fund_research"
RESEARCH_NOT_APPLICABLE = "not_applicable"
RESEARCH_NOT_EVALUATED = "not_evaluated"
RESEARCH_UNSUPPORTED = "unsupported"

PARTICIPATION_EQUITY = "equity_engine"
PARTICIPATION_FUND_LOOKTHROUGH = "fund_lookthrough"
PARTICIPATION_NOT_APPLICABLE = "not_applicable"
PARTICIPATION_POLICY_DEFINED = "policy_defined"


@dataclass(frozen=True)
class AssetCapabilityProfile:
    asset_class: str
    pricing_method: str
    research_capability: str
    participation_capability: str
    company_report_eligible: bool
    fund_report_eligible: bool
    dividend_semantics: str
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def capability_for_asset_class(asset_class: str) -> AssetCapabilityProfile:
    normalized = str(asset_class or ASSET_CLASS_OTHER).strip().lower()
    if normalized == ASSET_CLASS_EQUITY:
        return AssetCapabilityProfile(
            asset_class=normalized,
            pricing_method=PRICING_CANDIDATE_SNAPSHOT,
            research_capability=RESEARCH_EQUITY,
            participation_capability=PARTICIPATION_EQUITY,
            company_report_eligible=True,
            fund_report_eligible=False,
            dividend_semantics="equity_dividend",
            limitation="",
        )
    if normalized in {ASSET_CLASS_ETF, ASSET_CLASS_FUND}:
        return AssetCapabilityProfile(
            asset_class=normalized,
            pricing_method=PRICING_CANDIDATE_SNAPSHOT,
            research_capability=RESEARCH_FUND,
            participation_capability=PARTICIPATION_FUND_LOOKTHROUGH,
            company_report_eligible=False,
            fund_report_eligible=True,
            dividend_semantics="distribution_if_supported",
            limitation="Katılım durumu alt holding kanıtına dayanır.",
        )
    if normalized == ASSET_CLASS_CASH:
        return AssetCapabilityProfile(
            asset_class=normalized,
            pricing_method=PRICING_NOMINAL_CASH,
            research_capability=RESEARCH_NOT_APPLICABLE,
            participation_capability=PARTICIPATION_NOT_APPLICABLE,
            company_report_eligible=False,
            fund_report_eligible=False,
            dividend_semantics="not_applicable",
            limitation="",
        )
    if normalized in {ASSET_CLASS_GOLD, ASSET_CLASS_PRECIOUS_METAL}:
        return AssetCapabilityProfile(
            asset_class=normalized,
            pricing_method=PRICING_MANUAL,
            research_capability=RESEARCH_UNSUPPORTED,
            participation_capability=PARTICIPATION_POLICY_DEFINED,
            company_report_eligible=False,
            fund_report_eligible=False,
            dividend_semantics="not_applicable",
            limitation="Canlı altın fiyatı sağlayıcısı yok; manuel/değerleme gerekir.",
        )
    if normalized in {ASSET_CLASS_SUKUK, ASSET_CLASS_FIXED_INCOME}:
        return AssetCapabilityProfile(
            asset_class=normalized,
            pricing_method=PRICING_MANUAL,
            research_capability=RESEARCH_UNSUPPORTED,
            participation_capability=PARTICIPATION_POLICY_DEFINED,
            company_report_eligible=False,
            fund_report_eligible=False,
            dividend_semantics="coupon_if_supported",
            limitation="Getiri/verim hesaplaması desteklenmiyor.",
        )
    return AssetCapabilityProfile(
        asset_class=ASSET_CLASS_OTHER,
        pricing_method=PRICING_UNSUPPORTED,
        research_capability=RESEARCH_NOT_EVALUATED,
        participation_capability=PARTICIPATION_NOT_APPLICABLE,
        company_report_eligible=False,
        fund_report_eligible=False,
        dividend_semantics="unknown",
        limitation="Desteklenmeyen varlık türü.",
    )


def route_report_page(asset_class: str) -> str:
    profile = capability_for_asset_class(asset_class)
    if profile.fund_report_eligible:
        return "fund_report"
    if profile.company_report_eligible:
        return "company_report"
    return "asset_detail"
