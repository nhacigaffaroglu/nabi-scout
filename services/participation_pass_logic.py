from __future__ import annotations

from typing import Optional, Sequence, Tuple

from services.participation_business_contract import BusinessActivityScreenResult
from services.participation_business_rules_registry import get_methodology_business_rules
from services.participation_financial_contract import ParticipationFinancialScreenResult
from services.participation_intelligence_contract import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
)
from services.participation_methodology_capabilities import blocking_missing_capabilities
from services.participation_methodology_registry import get_methodology


RULE_TIER_REQUIRED = "required"
RULE_TIER_SUPPORTING = "supporting"

_DEFAULT_RULE_TIERS: dict[str, str] = {
    "sic_exclusions": RULE_TIER_REQUIRED,
    "sector_exclusions": RULE_TIER_REQUIRED,
    "description_keywords": RULE_TIER_SUPPORTING,
    "non_permissible_revenue": RULE_TIER_REQUIRED,
}


def rule_tier_for(rule_id: str) -> str:
    lowered = rule_id.lower()
    for suffix, tier in _DEFAULT_RULE_TIERS.items():
        if suffix in lowered:
            return tier
    return RULE_TIER_REQUIRED


def _required_rule_results(
    rule_results: Sequence,
) -> Tuple[object, ...]:
    return tuple(
        rule
        for rule in rule_results
        if rule_tier_for(getattr(rule, "rule_id", "")) == RULE_TIER_REQUIRED
    )


def can_emit_uygun(
    *,
    methodology_id: str,
    financial_screen: ParticipationFinancialScreenResult,
    business_screen: Optional[BusinessActivityScreenResult],
    missing_capabilities: Sequence[str] = (),
    business_evidence_provided: bool = True,
) -> bool:
    methodology = get_methodology(methodology_id)
    business_rules = get_methodology_business_rules(methodology_id)
    if methodology is None or business_rules is None:
        return False

    if financial_screen.overall_outcome == RULE_OUTCOME_FAIL:
        return False
    if business_screen is not None and business_screen.overall_outcome == RULE_OUTCOME_FAIL:
        return False

    if not methodology.financial_screen_complete_methodology:
        return False
    if not business_rules.business_screen_complete_methodology:
        return False

    if missing_capabilities:
        return False

    if financial_screen.overall_outcome != RULE_OUTCOME_PASS:
        return False
    if not financial_screen.methodology_complete:
        return False
    if not all(rule.outcome == RULE_OUTCOME_PASS for rule in financial_screen.rule_results):
        return False

    if business_screen is None:
        return False
    if business_screen.overall_outcome != RULE_OUTCOME_PASS:
        return False
    if not business_screen.methodology_complete:
        return False

    required_business = _required_rule_results(business_screen.rule_results)
    if not required_business:
        return False
    if any(rule.outcome == RULE_OUTCOME_FAIL for rule in required_business):
        return False
    if any(rule.outcome == RULE_OUTCOME_REVIEW_REQUIRED for rule in required_business):
        return False
    if any(rule.outcome == RULE_OUTCOME_INSUFFICIENT_DATA for rule in required_business):
        return False
    if not all(rule.outcome == RULE_OUTCOME_PASS for rule in required_business):
        return False

    return True
