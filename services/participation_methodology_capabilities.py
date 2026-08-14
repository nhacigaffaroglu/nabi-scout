from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Tuple

from services.participation_methodology_registry import get_methodology

CAPABILITY_PROHIBITED_REVENUE = "prohibited_revenue_inference"
CAPABILITY_HISTORICAL_MARKET_CAP_24M = "historical_market_cap_24m"
CAPABILITY_HISTORICAL_MVE_36M = "historical_market_value_equity_36m"
CAPABILITY_BUSINESS_SCREENING = "business_activity_screening"
CAPABILITY_ASSESSMENT_PERSISTENCE = "assessment_persistence"

_MARKET_CAP_DENOMINATORS = frozenset(
    {
        "trailing_24_month_average_market_capitalization",
        "market_capitalization",
    }
)
_MVE_DENOMINATORS = frozenset({"trailing_36_month_average_market_value_of_equity"})


@dataclass(frozen=True)
class MethodologyCapabilityGraph:
    methodology_id: str
    required_financial_fields: FrozenSet[str] = field(default_factory=frozenset)
    required_business_evidence: FrozenSet[str] = field(default_factory=frozenset)
    optional_capabilities: FrozenSet[str] = field(default_factory=frozenset)
    required_capabilities: FrozenSet[str] = field(default_factory=frozenset)
    requires_persistence: bool = False


def build_methodology_capability_graph(methodology_id: str) -> MethodologyCapabilityGraph:
    methodology = get_methodology(methodology_id)
    if methodology is None:
        return MethodologyCapabilityGraph(methodology_id=methodology_id)

    fields: set[str] = {
        "total_debt",
        "total_assets",
        "cash",
        "accounts_receivable",
        "total_revenue",
    }
    needs_cash_ib = False
    needs_non_perm = False
    needs_mcap_24 = False
    needs_mve_36 = False
    for rule in methodology.rules:
        if rule.numerator == "cash_and_interest_bearing_securities":
            needs_cash_ib = True
        if rule.numerator in {
            "cash_plus_interest_bearing_securities",
            "cash_and_interest_bearing_items",
        }:
            needs_cash_ib = True
        if rule.numerator == "non_permissible_revenue":
            needs_non_perm = True
        if rule.denominator in _MARKET_CAP_DENOMINATORS:
            if rule.denominator == "trailing_24_month_average_market_capitalization":
                needs_mcap_24 = True
            else:
                fields.add("market_capitalization")
        if rule.denominator in _MVE_DENOMINATORS:
            needs_mve_36 = True
    if needs_cash_ib:
        fields.add("cash_and_interest_bearing_securities")
    if needs_non_perm:
        fields.add("non_permissible_revenue")
    required_caps: set[str] = {CAPABILITY_BUSINESS_SCREENING}
    optional_caps: set[str] = {CAPABILITY_ASSESSMENT_PERSISTENCE}
    if needs_non_perm:
        required_caps.add(CAPABILITY_PROHIBITED_REVENUE)
    if needs_mcap_24:
        required_caps.add(CAPABILITY_HISTORICAL_MARKET_CAP_24M)
    else:
        optional_caps.add(CAPABILITY_HISTORICAL_MARKET_CAP_24M)
    if needs_mve_36:
        required_caps.add(CAPABILITY_HISTORICAL_MVE_36M)
    else:
        optional_caps.add(CAPABILITY_HISTORICAL_MVE_36M)
    if needs_mcap_24:
        fields.add("average_market_cap_24m")
    if needs_mve_36:
        fields.add("average_market_value_of_equity_36m")

    return MethodologyCapabilityGraph(
        methodology_id=methodology_id,
        required_financial_fields=frozenset(fields),
        required_business_evidence=frozenset(
            {"sic", "structured_sector", "revenue_segments"}
        ),
        optional_capabilities=frozenset(optional_caps),
        required_capabilities=frozenset(required_caps),
        requires_persistence=False,
    )


def blocking_missing_capabilities(
    methodology_id: str,
    *,
    financial_inputs: Optional[object] = None,
    business_screen: Optional[object] = None,
    business_evidence_provided: bool = False,
) -> Tuple[str, ...]:
    graph = build_methodology_capability_graph(methodology_id)
    missing: list[str] = []

    if not business_evidence_provided or business_screen is None:
        missing.append(CAPABILITY_BUSINESS_SCREENING)
    elif not getattr(business_screen, "business_rules_evaluated", False):
        missing.append(CAPABILITY_BUSINESS_SCREENING)

    if financial_inputs is not None:
        if CAPABILITY_PROHIBITED_REVENUE in graph.required_capabilities:
            if getattr(financial_inputs, "non_permissible_revenue", None) is None:
                missing.append(CAPABILITY_PROHIBITED_REVENUE)
        if CAPABILITY_HISTORICAL_MARKET_CAP_24M in graph.required_capabilities:
            if getattr(financial_inputs, "average_market_cap_24m", None) is None:
                missing.append(CAPABILITY_HISTORICAL_MARKET_CAP_24M)
        if CAPABILITY_HISTORICAL_MVE_36M in graph.required_capabilities:
            if getattr(financial_inputs, "average_market_value_of_equity_36m", None) is None:
                missing.append(CAPABILITY_HISTORICAL_MVE_36M)
    else:
        missing.extend(
            cap
            for cap in graph.required_capabilities
            if cap != CAPABILITY_BUSINESS_SCREENING
        )

    return tuple(dict.fromkeys(missing))
