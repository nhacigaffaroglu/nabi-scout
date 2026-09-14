"""Versioned FUND18 portfolio-fit assessment policy contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


POLICY_SCHEMA = "fund18_assessment_policy_1"
POLICY_VERSION = "1.0"
DECISION_ID = "FUND18-POLICY-V1"

ROLE_VALUES = {"STRONG", "PARTIAL", "WEAK"}
OVERLAP_VALUES = {"LOW", "MEDIUM", "HIGH"}
DIVERSIFICATION_VALUES = {"HIGH", "MEDIUM", "LOW"}
CONCENTRATION_VALUES = {"LOW", "MEDIUM", "HIGH"}

ALLOWED_MULTI_ROLE_RESOLUTION = {
    "BEST_SUPPORTED_MATCH",
}


class Fund18AssessmentPolicyError(ValueError):
    """Fail-closed policy validation error."""


@dataclass(frozen=True)
class Fund18AssessmentPolicy:
    raw: dict[str, Any]

    @property
    def production_effective(self) -> bool:
        return bool(self.raw["production_effective"])

    @property
    def human_approved(self) -> bool:
        return bool(self.raw["human_approved"])

    @property
    def locked(self) -> bool:
        return bool(self.raw["locked"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)


def draft_fund18_assessment_policy_v1() -> dict[str, Any]:
    return {
        "schema_version": POLICY_SCHEMA,
        "policy_version": POLICY_VERSION,
        "decision_id": DECISION_ID,
        "human_approved": False,
        "locked": False,
        "production_effective": False,
        "research_only": True,
        "role_fit": {
            "multi_role_resolution": "BEST_SUPPORTED_MATCH",
            "category_fallback_allowed": False,
            "rules": [
                {
                    "rule_id": "ROLE-EQUITY-CORE-GROWTH-01",
                    "primary_exposure": "equity",
                    "desired_role": "core_growth",
                    "assessment": "STRONG",
                },
                {
                    "rule_id": "ROLE-EQUITY-DIVERSIFICATION-01",
                    "primary_exposure": "equity",
                    "desired_role": "diversification",
                    "assessment": "WEAK",
                },
                {
                    "rule_id": "ROLE-MULTI-ASSET-CORE-GROWTH-01",
                    "primary_exposure": "multi_asset",
                    "desired_role": "core_growth",
                    "assessment": "PARTIAL",
                },
                {
                    "rule_id": "ROLE-MULTI-ASSET-DIVERSIFICATION-01",
                    "primary_exposure": "multi_asset",
                    "desired_role": "diversification",
                    "assessment": "STRONG",
                },
                {
                    "rule_id": "ROLE-SUKUK-CORE-GROWTH-01",
                    "primary_exposure": "sukuk",
                    "desired_role": "core_growth",
                    "assessment": "WEAK",
                },
                {
                    "rule_id": "ROLE-SUKUK-DIVERSIFICATION-01",
                    "primary_exposure": "sukuk",
                    "desired_role": "diversification",
                    "assessment": "STRONG",
                },
                {
                    "rule_id": "ROLE-CASH-LIKE-CORE-GROWTH-01",
                    "primary_exposure": "cash_like",
                    "desired_role": "core_growth",
                    "assessment": "WEAK",
                },
                {
                    "rule_id": "ROLE-CASH-LIKE-DIVERSIFICATION-01",
                    "primary_exposure": "cash_like",
                    "desired_role": "diversification",
                    "assessment": "PARTIAL",
                },
            ],
        },
        "economic_overlap": {
            "method": "PORTFOLIO_BUCKET_UNCERTAINTY_INTERVAL",
            "low_upper_exclusive_pct": 15.0,
            "medium_upper_inclusive_pct": 35.0,
            "renormalize_unknown": False,
        },
        "diversification_contribution": {
            "method": "PORTFOLIO_BUCKET_UNCERTAINTY_INTERVAL",
            "high_upper_exclusive_pct": 10.0,
            "medium_upper_inclusive_pct": 25.0,
            "renormalize_unknown": False,
        },
        "concentration_risk": {
            "method": "CURRENT_CANONICAL_PORTFOLIO_WEIGHT",
            "low_upper_inclusive_pct": 5.0,
            "medium_upper_inclusive_pct": 10.0,
        },
        "fail_closed": {
            "require_supported_evidence": True,
            "reject_future_evidence": True,
            "contradictory_maps_to_unknown": True,
            "missing_structured_fact_maps_to_unknown": True,
            "unmeasured_bucket_maps_to_unknown": True,
            "cross_band_interval_maps_to_unknown": True,
            "preserve_unknown_portfolio_exposure": True,
            "parse_observed_fact": False,
            "category_only_assessment_allowed": False,
        },
    }


def _pct(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise Fund18AssessmentPolicyError(
            f"{field}_must_be_numeric"
        ) from exc

    if not 0.0 <= number <= 100.0:
        raise Fund18AssessmentPolicyError(
            f"{field}_out_of_range"
        )

    return number


def _require_mapping(
    value: Any,
    *,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Fund18AssessmentPolicyError(
            f"{field}_must_be_object"
        )
    return dict(value)


def normalize_fund18_assessment_policy(
    raw: Mapping[str, Any],
    *,
    require_effective: bool = False,
) -> Fund18AssessmentPolicy:
    if not isinstance(raw, Mapping):
        raise Fund18AssessmentPolicyError(
            "policy_must_be_object"
        )

    policy = dict(raw)

    if policy.get("schema_version") != POLICY_SCHEMA:
        raise Fund18AssessmentPolicyError(
            "unsupported_policy_schema"
        )

    if policy.get("policy_version") != POLICY_VERSION:
        raise Fund18AssessmentPolicyError(
            "unsupported_policy_version"
        )

    if policy.get("decision_id") != DECISION_ID:
        raise Fund18AssessmentPolicyError(
            "unexpected_decision_id"
        )

    if policy.get("research_only") is not True:
        raise Fund18AssessmentPolicyError(
            "research_only_not_true"
        )

    role_fit = _require_mapping(
        policy.get("role_fit"),
        field="role_fit",
    )

    if (
        role_fit.get("multi_role_resolution")
        not in ALLOWED_MULTI_ROLE_RESOLUTION
    ):
        raise Fund18AssessmentPolicyError(
            "unsupported_multi_role_resolution"
        )

    if role_fit.get("category_fallback_allowed") is not False:
        raise Fund18AssessmentPolicyError(
            "category_fallback_must_be_false"
        )

    rules = role_fit.get("rules")
    if not isinstance(rules, list):
        raise Fund18AssessmentPolicyError(
            "role_fit_rules_must_be_list"
        )

    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()

    for rule in rules:
        if not isinstance(rule, Mapping):
            raise Fund18AssessmentPolicyError(
                "role_fit_rule_must_be_object"
            )

        rule_id = rule.get("rule_id")
        exposure = rule.get("primary_exposure")
        role = rule.get("desired_role")
        assessment = rule.get("assessment")

        if not isinstance(rule_id, str) or not rule_id:
            raise Fund18AssessmentPolicyError(
                "role_fit_rule_id_invalid"
            )

        if rule_id in seen_ids:
            raise Fund18AssessmentPolicyError(
                f"duplicate_rule_id:{rule_id}"
            )
        seen_ids.add(rule_id)

        if not isinstance(exposure, str) or not exposure:
            raise Fund18AssessmentPolicyError(
                f"role_fit_exposure_invalid:{rule_id}"
            )

        if not isinstance(role, str) or not role:
            raise Fund18AssessmentPolicyError(
                f"role_fit_role_invalid:{rule_id}"
            )

        pair = (exposure, role)
        if pair in seen_pairs:
            raise Fund18AssessmentPolicyError(
                f"duplicate_role_mapping:{exposure}:{role}"
            )
        seen_pairs.add(pair)

        if assessment not in ROLE_VALUES:
            raise Fund18AssessmentPolicyError(
                f"role_fit_assessment_invalid:{rule_id}"
            )

    overlap = _require_mapping(
        policy.get("economic_overlap"),
        field="economic_overlap",
    )
    diversification = _require_mapping(
        policy.get("diversification_contribution"),
        field="diversification_contribution",
    )
    concentration = _require_mapping(
        policy.get("concentration_risk"),
        field="concentration_risk",
    )
    fail_closed = _require_mapping(
        policy.get("fail_closed"),
        field="fail_closed",
    )

    if (
        overlap.get("method")
        != "PORTFOLIO_BUCKET_UNCERTAINTY_INTERVAL"
    ):
        raise Fund18AssessmentPolicyError(
            "economic_overlap_method_invalid"
        )

    overlap_low = _pct(
        overlap.get("low_upper_exclusive_pct"),
        field="economic_overlap.low_upper_exclusive_pct",
    )
    overlap_medium = _pct(
        overlap.get("medium_upper_inclusive_pct"),
        field="economic_overlap.medium_upper_inclusive_pct",
    )
    if overlap_low >= overlap_medium:
        raise Fund18AssessmentPolicyError(
            "economic_overlap_thresholds_reversed"
        )

    if overlap.get("renormalize_unknown") is not False:
        raise Fund18AssessmentPolicyError(
            "economic_overlap_renormalization_forbidden"
        )

    if (
        diversification.get("method")
        != "PORTFOLIO_BUCKET_UNCERTAINTY_INTERVAL"
    ):
        raise Fund18AssessmentPolicyError(
            "diversification_method_invalid"
        )

    div_high = _pct(
        diversification.get("high_upper_exclusive_pct"),
        field="diversification.high_upper_exclusive_pct",
    )
    div_medium = _pct(
        diversification.get("medium_upper_inclusive_pct"),
        field="diversification.medium_upper_inclusive_pct",
    )
    if div_high >= div_medium:
        raise Fund18AssessmentPolicyError(
            "diversification_thresholds_reversed"
        )

    if diversification.get("renormalize_unknown") is not False:
        raise Fund18AssessmentPolicyError(
            "diversification_renormalization_forbidden"
        )

    if (
        concentration.get("method")
        != "CURRENT_CANONICAL_PORTFOLIO_WEIGHT"
    ):
        raise Fund18AssessmentPolicyError(
            "concentration_method_invalid"
        )

    concentration_low = _pct(
        concentration.get("low_upper_inclusive_pct"),
        field="concentration.low_upper_inclusive_pct",
    )
    concentration_medium = _pct(
        concentration.get("medium_upper_inclusive_pct"),
        field="concentration.medium_upper_inclusive_pct",
    )
    if concentration_low >= concentration_medium:
        raise Fund18AssessmentPolicyError(
            "concentration_thresholds_reversed"
        )

    required_false = {
        "parse_observed_fact",
        "category_only_assessment_allowed",
    }
    for key in required_false:
        if fail_closed.get(key) is not False:
            raise Fund18AssessmentPolicyError(
                f"fail_closed_flag_invalid:{key}"
            )

    required_true = {
        "require_supported_evidence",
        "reject_future_evidence",
        "contradictory_maps_to_unknown",
        "missing_structured_fact_maps_to_unknown",
        "unmeasured_bucket_maps_to_unknown",
        "cross_band_interval_maps_to_unknown",
        "preserve_unknown_portfolio_exposure",
    }
    for key in required_true:
        if fail_closed.get(key) is not True:
            raise Fund18AssessmentPolicyError(
                f"fail_closed_flag_invalid:{key}"
            )

    effective = policy.get("production_effective") is True

    if effective or require_effective:
        if policy.get("human_approved") is not True:
            raise Fund18AssessmentPolicyError(
                "effective_policy_requires_human_approval"
            )
        if policy.get("locked") is not True:
            raise Fund18AssessmentPolicyError(
                "effective_policy_requires_lock"
            )
        if policy.get("production_effective") is not True:
            raise Fund18AssessmentPolicyError(
                "policy_not_production_effective"
            )

    return Fund18AssessmentPolicy(raw=policy)
