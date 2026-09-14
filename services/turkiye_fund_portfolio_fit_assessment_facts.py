"""Structured assessment facts for FUND18 portfolio-fit policy evaluation.

This module deliberately does not parse evidence ``observed_fact`` strings.
Assessment facts come only from structured production inputs:
- approved portfolio context / desired roles,
- official candidate economic exposure,
- canonical portfolio economic exposure,
- canonical current candidate weight,
- FUND18 evidence states.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


DIMENSIONS = (
    "role_fit",
    "economic_overlap",
    "diversification_contribution",
    "concentration_risk",
)

VALID_EVIDENCE_STATES = {
    "SUPPORTED",
    "INSUFFICIENT",
    "CONTRADICTORY",
}


class PortfolioFitAssessmentFactsError(ValueError):
    """Fail-closed structured fact validation error."""


@dataclass(frozen=True)
class PortfolioFitAssessmentFacts:
    fund_code: str
    desired_roles: tuple[str, ...]
    candidate_primary_exposure: str | None
    candidate_exposure_as_of: str | None
    candidate_exposure_confidence: str | None
    portfolio_bucket_weights: dict[str, float]
    portfolio_unknown_pct: float | None
    portfolio_completeness: str | None
    current_candidate_weight_pct: float | None
    evidence_states: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite_pct(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PortfolioFitAssessmentFactsError(
            f"{field}_must_be_numeric"
        ) from exc

    if not 0.0 <= number <= 100.0:
        raise PortfolioFitAssessmentFactsError(
            f"{field}_out_of_range"
        )

    return number


def _extract_evidence_states(
    evidence: Mapping[str, Any],
) -> dict[str, str]:
    if evidence.get("schema_version") != "fund18_portfolio_fit_evidence_1":
        raise PortfolioFitAssessmentFactsError(
            "unsupported_evidence_schema"
        )

    dimensions = evidence.get("dimensions")
    if not isinstance(dimensions, Mapping):
        raise PortfolioFitAssessmentFactsError(
            "evidence_dimensions_must_be_object"
        )

    states: dict[str, str] = {}

    for dimension in DIMENSIONS:
        raw = dimensions.get(dimension)

        if not isinstance(raw, Mapping):
            raise PortfolioFitAssessmentFactsError(
                f"evidence_dimension_missing:{dimension}"
            )

        state = raw.get("state")

        if state not in VALID_EVIDENCE_STATES:
            raise PortfolioFitAssessmentFactsError(
                f"evidence_state_invalid:{dimension}"
            )

        states[dimension] = str(state)

    return states


def _extract_portfolio_buckets(
    portfolio_exposure: Mapping[str, Any] | None,
) -> tuple[dict[str, float], float | None, str | None]:
    if not portfolio_exposure:
        return {}, None, None

    completeness = portfolio_exposure.get("completeness")
    if completeness is not None:
        completeness = str(completeness)

    buckets: dict[str, float] = {}
    unknown_pct: float | None = None

    raw_buckets = portfolio_exposure.get("buckets")

    if isinstance(raw_buckets, Mapping):
        iterable = raw_buckets.items()
    elif isinstance(raw_buckets, list):
        iterable = []
        for row in raw_buckets:
            if not isinstance(row, Mapping):
                continue
            bucket_id = row.get("bucket_id")
            if isinstance(bucket_id, str):
                iterable.append((bucket_id, row))
    else:
        iterable = []

    for bucket_id, raw in iterable:
        if not isinstance(bucket_id, str) or not bucket_id:
            continue

        if isinstance(raw, Mapping):
            value = raw.get("observable_weight_pct")
            if value is None:
                value = raw.get("weight_pct")
        else:
            value = raw

        if value is None:
            continue

        pct = _finite_pct(
            value,
            field=f"portfolio_bucket:{bucket_id}",
        )

        key = bucket_id.strip().lower()

        if key == "unknown":
            unknown_pct = pct
        else:
            buckets[key] = pct

    if unknown_pct is None:
        explicit_unknown = portfolio_exposure.get("unknown_pct")
        if explicit_unknown is not None:
            unknown_pct = _finite_pct(
                explicit_unknown,
                field="portfolio_unknown_pct",
            )

    return buckets, unknown_pct, completeness


def build_portfolio_fit_assessment_facts(
    *,
    fund_code: str,
    evidence: Mapping[str, Any],
    candidate_exposure: Mapping[str, Any] | None,
    portfolio_exposure: Mapping[str, Any] | None,
    current_weight_pct: float | None,
    desired_roles: Sequence[str],
) -> PortfolioFitAssessmentFacts:
    if not isinstance(fund_code, str) or not fund_code.strip():
        raise PortfolioFitAssessmentFactsError(
            "fund_code_invalid"
        )

    if not isinstance(evidence, Mapping):
        raise PortfolioFitAssessmentFactsError(
            "evidence_must_be_object"
        )

    evidence_states = _extract_evidence_states(evidence)

    roles = tuple(
        dict.fromkeys(
            str(role).strip()
            for role in desired_roles
            if str(role).strip()
        )
    )

    primary_exposure: str | None = None
    exposure_as_of: str | None = None
    exposure_confidence: str | None = None

    if candidate_exposure:
        raw_primary = candidate_exposure.get("primary_exposure")
        if isinstance(raw_primary, str) and raw_primary.strip():
            primary_exposure = raw_primary.strip().lower()

        raw_as_of = candidate_exposure.get("as_of")
        if isinstance(raw_as_of, str) and raw_as_of.strip():
            exposure_as_of = raw_as_of.strip()

        raw_conf = candidate_exposure.get("confidence")
        if isinstance(raw_conf, str) and raw_conf.strip():
            exposure_confidence = raw_conf.strip()

    buckets, unknown_pct, completeness = _extract_portfolio_buckets(
        portfolio_exposure
    )

    weight: float | None = None
    if current_weight_pct is not None:
        weight = _finite_pct(
            current_weight_pct,
            field="current_candidate_weight_pct",
        )

    return PortfolioFitAssessmentFacts(
        fund_code=fund_code.strip().upper(),
        desired_roles=roles,
        candidate_primary_exposure=primary_exposure,
        candidate_exposure_as_of=exposure_as_of,
        candidate_exposure_confidence=exposure_confidence,
        portfolio_bucket_weights=buckets,
        portfolio_unknown_pct=unknown_pct,
        portfolio_completeness=completeness,
        current_candidate_weight_pct=weight,
        evidence_states=evidence_states,
    )
