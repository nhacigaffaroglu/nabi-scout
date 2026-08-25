"""Deterministic semantic typing for filing-derived revenue evidence.

Classifies what a revenue label represents from XBRL structure only.
Does not decide permissible/prohibited and does not change methodology.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from services.participation_revenue_attribution_contract import RevenueAttributionItem

SEMANTIC_OWN_ACTIVITY_REVENUE = "OWN_ACTIVITY_REVENUE"
SEMANTIC_CUSTOMER_INDUSTRY_REVENUE = "CUSTOMER_INDUSTRY_REVENUE"
SEMANTIC_GEOGRAPHIC_REVENUE = "GEOGRAPHIC_REVENUE"
SEMANTIC_MERCHANDISE_CATEGORY = "MERCHANDISE_CATEGORY"
SEMANTIC_FINANCE_INTEREST_INCOME = "FINANCE_INTEREST_INCOME"
SEMANTIC_BROAD_OPERATING_SEGMENT = "BROAD_OPERATING_SEGMENT"
SEMANTIC_UNKNOWN = "UNKNOWN"

SEMANTIC_TYPES = (
    SEMANTIC_OWN_ACTIVITY_REVENUE,
    SEMANTIC_CUSTOMER_INDUSTRY_REVENUE,
    SEMANTIC_GEOGRAPHIC_REVENUE,
    SEMANTIC_MERCHANDISE_CATEGORY,
    SEMANTIC_FINANCE_INTEREST_INCOME,
    SEMANTIC_BROAD_OPERATING_SEGMENT,
    SEMANTIC_UNKNOWN,
)

# Overlay only where existing granularity policy would not already refuse.
# BROAD_OPERATING_SEGMENT and GEOGRAPHIC_REVENUE keep the existing
# granularity restriction path and limitation strings unchanged.
SAFE_ZERO_BLOCKED_SEMANTIC_TYPES = frozenset(
    {
        SEMANTIC_CUSTOMER_INDUSTRY_REVENUE,
        SEMANTIC_MERCHANDISE_CATEGORY,
        SEMANTIC_FINANCE_INTEREST_INCOME,
        SEMANTIC_UNKNOWN,
    }
)

_INTEREST_CONCEPT_PATTERNS = (
    re.compile(r"interestincome", re.I),
    re.compile(r"financeincome", re.I),
    re.compile(r"interestandfeeincome", re.I),
    re.compile(r"leasesinterestincome", re.I),
    re.compile(r"investmentincomeinterest", re.I),
)
_EXPENSE_OR_EQUITY_NOISE = (
    re.compile(r"interestexpense", re.I),
    re.compile(r"minorityinterest", re.I),
    re.compile(r"noncontrollinginterest", re.I),
    re.compile(r"stockholders?equity", re.I),
)
_CUSTOMER_INDUSTRY_AXIS_PATTERNS = (
    re.compile(r"byindustry", re.I),
    re.compile(r"customerindustry", re.I),
    re.compile(r"^industryaxis$", re.I),
    re.compile(r"equitysecuritiesbyindustry", re.I),
)
_GEOGRAPHIC_AXIS_PATTERNS = (
    re.compile(r"geograph", re.I),
    re.compile(r"countryaxis", re.I),
)
_BROAD_SEGMENT_AXES = frozenset(
    {
        "StatementBusinessSegmentsAxis",
        "SubsegmentsAxis",
    }
)
_MERCHANDISE_PATTERNS = (
    "grocery",
    "general merch",
    "general merchandise",
    "health and wellness",
    "apparel",
    "hardlines",
    "consumable",
    "supermarket",
)
_FINANCE_OPS_LABEL_PATTERNS = (
    "financial service",
    "finance service",
)


@dataclass(frozen=True)
class RevenueSemanticTypeResult:
    semantic_type: str
    semantic_reason: str


def _axis_local(axis: str) -> str:
    return str(axis or "").split(":")[-1]


def _concept_local(concept: str) -> str:
    return str(concept or "").split(":")[-1]


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def concept_is_finance_interest_income(concept: str) -> bool:
    local = _concept_local(concept)
    if any(pattern.search(local) for pattern in _EXPENSE_OR_EQUITY_NOISE):
        return False
    return any(pattern.search(local) for pattern in _INTEREST_CONCEPT_PATTERNS)


def axis_is_customer_industry(axis: str) -> bool:
    local = _axis_local(axis)
    if "propertyplantandequipment" in local.lower():
        return False
    return any(pattern.search(local) for pattern in _CUSTOMER_INDUSTRY_AXIS_PATTERNS)


def axis_is_geographic(axis: str) -> bool:
    local = _axis_local(axis)
    return any(pattern.search(local) for pattern in _GEOGRAPHIC_AXIS_PATTERNS)


def _label_is_merchandise(normalized_label: str) -> bool:
    return any(pattern in normalized_label for pattern in _MERCHANDISE_PATTERNS)


def _label_is_finance_ops(normalized_label: str) -> bool:
    return any(pattern in normalized_label for pattern in _FINANCE_OPS_LABEL_PATTERNS)


def classify_revenue_semantic_type(
    item: RevenueAttributionItem,
) -> RevenueSemanticTypeResult:
    """Return a structural semantic type. Never infers ticker or halal/haram."""
    axis = _axis_local(item.axis)
    concept = item.concept
    label = _normalize(item.normalized_label or item.reported_label)

    if concept_is_finance_interest_income(concept):
        return RevenueSemanticTypeResult(
            SEMANTIC_FINANCE_INTEREST_INCOME,
            "Concept is finance/interest income, not operating product revenue.",
        )
    if axis_is_customer_industry(axis):
        return RevenueSemanticTypeResult(
            SEMANTIC_CUSTOMER_INDUSTRY_REVENUE,
            f"Axis {axis} reports customer/industry mix, not the issuer's own activity.",
        )
    if axis_is_geographic(axis):
        return RevenueSemanticTypeResult(
            SEMANTIC_GEOGRAPHIC_REVENUE,
            f"Axis {axis} reports geography, not activity classification.",
        )
    if axis in _BROAD_SEGMENT_AXES:
        return RevenueSemanticTypeResult(
            SEMANTIC_BROAD_OPERATING_SEGMENT,
            f"Axis {axis} is a reportable operating-segment breakdown.",
        )
    if axis == "ProductOrServiceAxis":
        if _label_is_merchandise(label):
            return RevenueSemanticTypeResult(
                SEMANTIC_MERCHANDISE_CATEGORY,
                "Product/service axis member is a merchandise category.",
            )
        if _label_is_finance_ops(label):
            return RevenueSemanticTypeResult(
                SEMANTIC_UNKNOWN,
                "Finance-related product member is not proven interest-income evidence.",
            )
        if not label:
            return RevenueSemanticTypeResult(
                SEMANTIC_UNKNOWN,
                "Product/service member label is empty.",
            )
        return RevenueSemanticTypeResult(
            SEMANTIC_OWN_ACTIVITY_REVENUE,
            "Product/service axis reports the issuer's own products or services.",
        )
    return RevenueSemanticTypeResult(
        SEMANTIC_UNKNOWN,
        "Semantic type could not be determined from concept, axis, and label.",
    )


def semantic_type_blocks_safe_zero(semantic_type: Optional[str]) -> bool:
    if not semantic_type:
        return False
    return semantic_type in SAFE_ZERO_BLOCKED_SEMANTIC_TYPES
