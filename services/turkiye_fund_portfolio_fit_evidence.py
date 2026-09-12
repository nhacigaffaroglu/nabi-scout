"""FUND18 portfolio-fit evidence/provenance contract.

This module validates descriptive evidence used by FUND18.

It does not:
- score candidates
- rank candidates
- choose a winner
- create recommendations
- allocate capital
- execute trades
- persist production data
"""

from __future__ import annotations

import math

from datetime import datetime
from typing import Any, Mapping


EVIDENCE_SCHEMA = "fund18_portfolio_fit_evidence_1"
FRESHNESS_POLICY_SCHEMA = (
    "fund18_portfolio_fit_freshness_policy_1"
)

METRIC_ASSESSMENT_POLICY_SCHEMA = (
    "fund18_metric_assessment_policy_1"
)

METRIC_ASSESSMENT_DIMENSIONS = {
    "role_fit",
    "economic_overlap",
    "diversification_contribution",
    "concentration_risk",
}

METRIC_CLAIM_FIELDS = {
    "portfolio_weight",
}

METRIC_RULE_OPERATORS = {
    "lt",
    "lte",
    "gt",
    "gte",
    "eq",
}

METRIC_ASSESSMENT_VALUES = {
    "role_fit": {
        "STRONG",
        "PARTIAL",
        "WEAK",
    },
    "economic_overlap": {
        "LOW",
        "MEDIUM",
        "HIGH",
    },
    "diversification_contribution": {
        "HIGH",
        "MEDIUM",
        "LOW",
    },
    "concentration_risk": {
        "LOW",
        "MEDIUM",
        "HIGH",
    },
}

DIMENSIONS = {
    "role_fit",
    "economic_overlap",
    "diversification_contribution",
    "concentration_risk",
}

EVIDENCE_STATES = {
    "SUPPORTED",
    "INSUFFICIENT",
    "CONTRADICTORY",
}

CLAIM_FIELDS = {
    "role_fit",
    "economic_overlap",
    "diversification_contribution",
    "concentration_risk",
    "portfolio_weight",
    "economic_exposure",
    "portfolio_role",
    "liquidity_profile",
}

CLAIM_UNITS = {
    "percent",
    "basis_points",
}

ALLOWED_SOURCE_TYPES = {
    "FUND17_PORTFOLIO_CONTEXT",
    "FUND16_CANDIDATE_RESEARCH",
    "KAP_OFFICIAL",
    "TEFAS_OFFICIAL",
    "FUND_PROSPECTUS",
    "HUMAN_APPROVED_RESEARCH",
}


class PortfolioFitEvidenceContractError(ValueError):
    """Fail-closed FUND18 evidence contract violation."""


def normalize_metric_assessment_policy(
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a locked human-approved metric assessment policy.

    Validation only. This function does not apply thresholds, derive
    assessments, infer from categories, or supply default financial rules.
    """
    policy = _as_dict(
        raw,
        field="metric_assessment_policy",
    )

    allowed_policy_keys = {
        "schema_version",
        "human_approved",
        "locked",
        "policy_id",
        "rules",
    }
    unknown_policy_keys = sorted(
        set(policy) - allowed_policy_keys
    )
    if unknown_policy_keys:
        raise PortfolioFitEvidenceContractError(
            "metric_assessment_policy_unknown_key:"
            f"{unknown_policy_keys[0]}"
        )

    if (
        policy.get("schema_version")
        != METRIC_ASSESSMENT_POLICY_SCHEMA
    ):
        raise PortfolioFitEvidenceContractError(
            "unsupported_metric_assessment_policy_schema"
        )

    if policy.get("human_approved") is not True:
        raise PortfolioFitEvidenceContractError(
            "metric_assessment_policy_not_human_approved"
        )

    if policy.get("locked") is not True:
        raise PortfolioFitEvidenceContractError(
            "metric_assessment_policy_not_locked"
        )

    policy_id = _nonempty_string(
        policy.get("policy_id"),
        field="metric_assessment_policy_id",
    )

    raw_rules = policy.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise PortfolioFitEvidenceContractError(
            "metric_assessment_policy_requires_rule"
        )

    allowed_rule_keys = {
        "rule_id",
        "dimension",
        "claim_field",
        "unit",
        "operator",
        "threshold",
        "assessment",
    }

    normalized_rules: list[dict[str, Any]] = []
    seen_rule_ids: set[str] = set()

    for index, raw_rule in enumerate(raw_rules):
        rule = _as_dict(
            raw_rule,
            field=f"metric_assessment_policy_rule:{index}",
        )

        unknown_rule_keys = sorted(
            set(rule) - allowed_rule_keys
        )
        if unknown_rule_keys:
            raise PortfolioFitEvidenceContractError(
                "metric_assessment_policy_rule_unknown_key:"
                f"{unknown_rule_keys[0]}"
            )

        missing_rule_keys = sorted(
            allowed_rule_keys - set(rule)
        )
        if missing_rule_keys:
            raise PortfolioFitEvidenceContractError(
                "metric_assessment_policy_rule_missing_key:"
                f"{missing_rule_keys[0]}"
            )

        rule_id = _nonempty_string(
            rule.get("rule_id"),
            field="metric_assessment_policy_rule_id",
        )
        if rule_id in seen_rule_ids:
            raise PortfolioFitEvidenceContractError(
                "metric_assessment_policy_duplicate_rule_id:"
                f"{rule_id}"
            )
        seen_rule_ids.add(rule_id)

        dimension = rule.get("dimension")
        if dimension not in METRIC_ASSESSMENT_DIMENSIONS:
            raise PortfolioFitEvidenceContractError(
                "metric_assessment_policy_invalid_dimension:"
                f"{dimension}"
            )

        claim_field = rule.get("claim_field")
        if claim_field not in METRIC_CLAIM_FIELDS:
            raise PortfolioFitEvidenceContractError(
                "metric_assessment_policy_invalid_metric_field:"
                f"{claim_field}"
            )

        unit = rule.get("unit")
        if unit not in CLAIM_UNITS:
            raise PortfolioFitEvidenceContractError(
                "metric_assessment_policy_invalid_unit:"
                f"{unit}"
            )

        operator = rule.get("operator")
        if operator not in METRIC_RULE_OPERATORS:
            raise PortfolioFitEvidenceContractError(
                "metric_assessment_policy_invalid_operator:"
                f"{operator}"
            )

        threshold = rule.get("threshold")
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or (
                isinstance(threshold, float)
                and not math.isfinite(threshold)
            )
        ):
            raise PortfolioFitEvidenceContractError(
                "metric_assessment_policy_invalid_threshold:"
                f"{rule_id}"
            )

        assessment = rule.get("assessment")
        if assessment not in METRIC_ASSESSMENT_VALUES[dimension]:
            raise PortfolioFitEvidenceContractError(
                "metric_assessment_policy_invalid_assessment:"
                f"{rule_id}"
            )

        normalized_rules.append(
            {
                "rule_id": rule_id,
                "dimension": dimension,
                "claim_field": claim_field,
                "unit": unit,
                "operator": operator,
                "threshold": threshold,
                "assessment": assessment,
            }
        )

    normalized_rules.sort(
        key=lambda row: row["rule_id"]
    )

    return {
        "schema_version": METRIC_ASSESSMENT_POLICY_SCHEMA,
        "human_approved": True,
        "locked": True,
        "policy_id": policy_id,
        "rules": normalized_rules,
    }


def normalize_freshness_policy(
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an explicit human-approved evidence freshness policy.

    No default freshness threshold is supplied by code. A source type is
    age-limited only when it is explicitly present in the approved policy.
    """
    policy = _as_dict(
        raw,
        field="freshness_policy",
    )

    if policy.get("schema_version") != FRESHNESS_POLICY_SCHEMA:
        raise PortfolioFitEvidenceContractError(
            "unsupported_freshness_policy_schema"
        )

    if policy.get("human_approved") is not True:
        raise PortfolioFitEvidenceContractError(
            "freshness_policy_not_human_approved"
        )

    policy_id = _nonempty_string(
        policy.get("policy_id"),
        field="freshness_policy_id",
    )

    raw_limits = _as_dict(
        policy.get("source_max_age_days"),
        field="freshness_policy_source_max_age_days",
    )

    if not raw_limits:
        raise PortfolioFitEvidenceContractError(
            "freshness_policy_requires_source_limit"
        )

    normalized_limits: dict[str, int] = {}

    for source_type, max_age_days in sorted(raw_limits.items()):
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise PortfolioFitEvidenceContractError(
                f"freshness_policy_invalid_source_type:{source_type}"
            )

        if (
            isinstance(max_age_days, bool)
            or not isinstance(max_age_days, int)
            or max_age_days <= 0
        ):
            raise PortfolioFitEvidenceContractError(
                f"freshness_policy_invalid_max_age_days:{source_type}"
            )

        normalized_limits[source_type] = max_age_days

    return {
        "schema_version": FRESHNESS_POLICY_SCHEMA,
        "human_approved": True,
        "policy_id": policy_id,
        "source_max_age_days": normalized_limits,
    }


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioFitEvidenceContractError(
            f"{field}_must_be_object"
        )
    return dict(value)


def _nonempty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioFitEvidenceContractError(
            f"{field}_must_be_nonempty_string"
        )
    return value.strip()


def _normalize_structured_claim(
    value: Any,
    *,
    field: str,
) -> dict[str, Any]:
    claim = _as_dict(value, field=field)

    required_fields = {"field", "value"}
    optional_fields = {
        "unit",
        "method",
        "evidence_id",
    }
    allowed_fields = required_fields | optional_fields

    if not required_fields.issubset(claim):
        raise PortfolioFitEvidenceContractError(
            f"{field}_required_field_missing"
        )

    unknown_fields = set(claim) - allowed_fields
    if unknown_fields:
        raise PortfolioFitEvidenceContractError(
            f"{field}_field_set_mismatch"
        )

    claim_field = _nonempty_string(
        claim.get("field"),
        field=f"{field}_field",
    )

    if claim_field not in CLAIM_FIELDS:
        raise PortfolioFitEvidenceContractError(
            f"{field}_unsupported_claim_field:{claim_field}"
        )

    claim_value = claim.get("value")

    if (
        claim_value is None
        or isinstance(claim_value, (dict, list))
        or not isinstance(
            claim_value,
            (str, int, float, bool),
        )
    ):
        raise PortfolioFitEvidenceContractError(
            f"{field}_value_must_be_scalar"
        )

    if isinstance(claim_value, str):
        claim_value = claim_value.strip()
        if not claim_value:
            raise PortfolioFitEvidenceContractError(
                f"{field}_value_must_be_nonempty"
            )

    if (
        isinstance(claim_value, float)
        and not math.isfinite(claim_value)
    ):
        raise PortfolioFitEvidenceContractError(
            f"{field}_value_must_be_finite"
        )

    normalized = {
        "field": claim_field,
        "value": claim_value,
    }

    for optional_field in (
        "unit",
        "method",
        "evidence_id",
    ):
        if optional_field in claim:
            optional_value = _nonempty_string(
                claim.get(optional_field),
                field=f"{field}_{optional_field}",
            )

            if (
                optional_field == "unit"
                and optional_value not in CLAIM_UNITS
            ):
                raise PortfolioFitEvidenceContractError(
                    f"{field}_unsupported_claim_unit:{optional_value}"
                )

            normalized[optional_field] = optional_value

    return normalized


def canonical_metric_value(
    *,
    claim_field: str,
    unit: str,
    value: Any,
) -> int | float:
    """Return a canonical numeric metric value for policy comparison.

    Currently only portfolio_weight is an approved numeric metric.
    Percent and basis-points inputs are compared on a basis-points scale.
    No thresholds or financial rules are supplied here.
    """
    if claim_field not in METRIC_CLAIM_FIELDS:
        raise PortfolioFitEvidenceContractError(
            f"unsupported_metric_claim_field:{claim_field}"
        )

    if unit not in CLAIM_UNITS:
        raise PortfolioFitEvidenceContractError(
            f"unsupported_metric_claim_unit:{unit}"
        )

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (
            isinstance(value, float)
            and not math.isfinite(value)
        )
    ):
        raise PortfolioFitEvidenceContractError(
            f"invalid_metric_claim_value:{claim_field}"
        )

    if claim_field == "portfolio_weight":
        return (
            value * 100
            if unit == "percent"
            else value
        )

    raise PortfolioFitEvidenceContractError(
        f"unsupported_metric_claim_field:{claim_field}"
    )


def _structured_claim_comparison_identity(
    claim: dict[str, Any],
) -> tuple[tuple[str, str | None], Any]:
    """Return a deterministic identity/value for contradiction checks.

    Evidence provenance remains unchanged. Only portfolio_weight claims
    expressed in the controlled percent/basis_points units are compared
    on a common basis-points scale.
    """
    claim_field = claim["field"]
    claim_unit = claim.get("unit")
    claim_value = claim["value"]

    if (
        claim_field == "portfolio_weight"
        and claim_unit in {"percent", "basis_points"}
        and isinstance(claim_value, (int, float))
        and not isinstance(claim_value, bool)
    ):
        basis_points_value = canonical_metric_value(
            claim_field=claim_field,
            unit=claim_unit,
            value=claim_value,
        )
        return (
            (claim_field, "basis_points"),
            basis_points_value,
        )

    return (
        (claim_field, claim_unit),
        claim_value,
    )


def _has_structured_claim_contradiction(
    sources: list[dict[str, Any]],
) -> bool:
    values_by_claim: dict[
        tuple[str, str | None],
        list[Any],
    ] = {}

    for source in sources:
        claim = source.get("claim")
        if claim is None:
            continue

        claim_key, claim_value = (
            _structured_claim_comparison_identity(claim)
        )

        observed_values = values_by_claim.setdefault(
            claim_key,
            [],
        )

        if not any(
            existing == claim_value
            and type(existing) is type(claim_value)
            for existing in observed_values
        ):
            observed_values.append(claim_value)

    return any(
        len(values) > 1
        for values in values_by_claim.values()
    )


def _iso_timestamp(value: Any, *, field: str) -> str:
    raw = _nonempty_string(value, field=field)

    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise PortfolioFitEvidenceContractError(
            f"{field}_must_be_iso8601"
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PortfolioFitEvidenceContractError(
            f"{field}_must_include_timezone"
        )

    return raw


def normalize_candidate_evidence(
    raw: Mapping[str, Any],
    *,
    expected_code: str,
    not_after: str | None = None,
    freshness_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row = _as_dict(
        raw,
        field=f"evidence:{expected_code}",
    )

    if row.get("schema_version") != EVIDENCE_SCHEMA:
        raise PortfolioFitEvidenceContractError(
            f"unsupported_evidence_schema:{expected_code}"
        )

    if row.get("fund_code") != expected_code:
        raise PortfolioFitEvidenceContractError(
            f"evidence_fund_code_mismatch:{expected_code}"
        )

    if row.get("research_only") is not True:
        raise PortfolioFitEvidenceContractError(
            f"evidence_research_only_not_true:{expected_code}"
        )

    if row.get("execution_authority") is not False:
        raise PortfolioFitEvidenceContractError(
            f"evidence_execution_authority_not_false:{expected_code}"
        )

    if row.get("production_persist") is not False:
        raise PortfolioFitEvidenceContractError(
            f"evidence_production_persist_not_false:{expected_code}"
        )

    dimensions = _as_dict(
        row.get("dimensions"),
        field=f"dimensions:{expected_code}",
    )

    if set(dimensions) != DIMENSIONS:
        raise PortfolioFitEvidenceContractError(
            f"evidence_dimension_set_mismatch:{expected_code}"
        )

    normalized_freshness_policy = None
    if freshness_policy is not None:
        normalized_freshness_policy = normalize_freshness_policy(
            freshness_policy
        )
        if not_after is None:
            raise PortfolioFitEvidenceContractError(
                f"freshness_policy_requires_not_after:{expected_code}"
            )

    not_after_dt = None
    if not_after is not None:
        normalized_not_after = _iso_timestamp(
            not_after,
            field=f"evidence_not_after:{expected_code}",
        )
        candidate = (
            normalized_not_after[:-1] + "+00:00"
            if normalized_not_after.endswith("Z")
            else normalized_not_after
        )
        not_after_dt = datetime.fromisoformat(candidate)

    normalized_dimensions: dict[str, Any] = {}

    for dimension in sorted(DIMENSIONS):
        item = _as_dict(
            dimensions[dimension],
            field=f"{expected_code}:{dimension}",
        )

        state = item.get("state")
        if state not in EVIDENCE_STATES:
            raise PortfolioFitEvidenceContractError(
                f"invalid_evidence_state:{expected_code}:{dimension}"
            )

        sources = item.get("sources")
        if not isinstance(sources, list):
            raise PortfolioFitEvidenceContractError(
                f"evidence_sources_must_be_list:{expected_code}:{dimension}"
            )

        normalized_sources = []

        for index, source_raw in enumerate(sources):
            source = _as_dict(
                source_raw,
                field=(
                    f"{expected_code}:{dimension}:source:{index}"
                ),
            )

            source_type = source.get("source_type")
            if source_type not in ALLOWED_SOURCE_TYPES:
                raise PortfolioFitEvidenceContractError(
                    f"invalid_source_type:{expected_code}:{dimension}"
                )

            source_id = _nonempty_string(
                source.get("source_id"),
                field=(
                    f"{expected_code}:{dimension}:source_id"
                ),
            )

            observed_fact = _nonempty_string(
                source.get("observed_fact"),
                field=(
                    f"{expected_code}:{dimension}:observed_fact"
                ),
            )

            as_of = _iso_timestamp(
                source.get("as_of"),
                field=(
                    f"{expected_code}:{dimension}:as_of"
                ),
            )

            if not_after_dt is not None:
                candidate = (
                    as_of[:-1] + "+00:00"
                    if as_of.endswith("Z")
                    else as_of
                )
                as_of_dt = datetime.fromisoformat(candidate)

                if as_of_dt > not_after_dt:
                    raise PortfolioFitEvidenceContractError(
                        f"evidence_as_of_in_future:"
                        f"{expected_code}:{dimension}"
                    )

                if normalized_freshness_policy is not None:
                    max_age_days = (
                        normalized_freshness_policy[
                            "source_max_age_days"
                        ].get(source_type)
                    )

                    if max_age_days is not None:
                        age = not_after_dt - as_of_dt

                        if age.total_seconds() > max_age_days * 86400:
                            raise PortfolioFitEvidenceContractError(
                                f"evidence_stale:"
                                f"{expected_code}:{dimension}:"
                                f"{source_type}"
                            )

            normalized_source = {
                "source_type": source_type,
                "source_id": source_id,
                "observed_fact": observed_fact,
                "as_of": as_of,
            }

            if "claim" in source:
                normalized_source["claim"] = (
                    _normalize_structured_claim(
                        source["claim"],
                        field=(
                            f"{expected_code}:{dimension}:"
                            f"source:{index}:claim"
                        ),
                    )
                )

            normalized_sources.append(normalized_source)

        if state == "SUPPORTED" and not normalized_sources:
            raise PortfolioFitEvidenceContractError(
                f"supported_dimension_requires_source:"
                f"{expected_code}:{dimension}"
            )

        if _has_structured_claim_contradiction(
            normalized_sources
        ):
            state = "CONTRADICTORY"

        rationale = item.get("rationale")
        if not isinstance(rationale, list) or not rationale:
            raise PortfolioFitEvidenceContractError(
                f"evidence_rationale_required:"
                f"{expected_code}:{dimension}"
            )

        if any(
            not isinstance(value, str) or not value.strip()
            for value in rationale
        ):
            raise PortfolioFitEvidenceContractError(
                f"evidence_rationale_invalid:"
                f"{expected_code}:{dimension}"
            )

        normalized_dimensions[dimension] = {
            "state": state,
            "sources": normalized_sources,
            "rationale": [value.strip() for value in rationale],
        }

    return {
        "schema_version": EVIDENCE_SCHEMA,
        "fund_code": expected_code,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "dimensions": normalized_dimensions,
    }
