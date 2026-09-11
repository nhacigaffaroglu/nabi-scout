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

from datetime import datetime
from typing import Any, Mapping


EVIDENCE_SCHEMA = "fund18_portfolio_fit_evidence_1"
FRESHNESS_POLICY_SCHEMA = (
    "fund18_portfolio_fit_freshness_policy_1"
)

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

    if set(claim) != {"field", "value"}:
        raise PortfolioFitEvidenceContractError(
            f"{field}_field_set_mismatch"
        )

    claim_field = _nonempty_string(
        claim.get("field"),
        field=f"{field}_field",
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

    return {
        "field": claim_field,
        "value": claim_value,
    }


def _has_structured_claim_contradiction(
    sources: list[dict[str, Any]],
) -> bool:
    values_by_field: dict[str, list[Any]] = {}

    for source in sources:
        claim = source.get("claim")
        if claim is None:
            continue

        claim_field = claim["field"]
        claim_value = claim["value"]

        observed_values = values_by_field.setdefault(
            claim_field,
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
        for values in values_by_field.values()
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
