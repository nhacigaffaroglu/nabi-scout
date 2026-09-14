"""Apply the approved FUND18 assessment policy to production research output.

This integration layer is intentionally separate from the evidence builder:
- it consumes only structured assessment inputs,
- it requires an explicitly effective, human-approved, locked policy,
- it preserves FUND18 evidence and firewall fields,
- it does not rank, recommend, allocate, execute, or persist.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from services.turkiye_fund_portfolio_fit_assessment_engine import (
    MODE_EFFECTIVE,
    evaluate_portfolio_fit_assessments,
)
from services.turkiye_fund_portfolio_fit_assessment_facts import (
    build_portfolio_fit_assessment_facts,
)
from services.turkiye_fund_portfolio_fit_assessment_policy import (
    normalize_fund18_assessment_policy,
)


DIMENSIONS = (
    "role_fit",
    "economic_overlap",
    "diversification_contribution",
    "concentration_risk",
)


class Fund18EffectiveAssessmentIntegrationError(ValueError):
    """Fail-closed production assessment integration error."""


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Fund18EffectiveAssessmentIntegrationError(
            f"{field}_must_be_object"
        )
    return dict(value)


def apply_effective_portfolio_fit_assessment_policy(
    fund18_artifact: Mapping[str, Any],
    *,
    assessment_inputs: Mapping[str, Any],
    assessment_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply an explicit effective policy to an existing FUND18 artifact."""

    artifact = _mapping(fund18_artifact, field="fund18_artifact")
    inputs = _mapping(assessment_inputs, field="assessment_inputs")

    if artifact.get("schema_version") != "fund18_portfolio_fit_research_artifact_1":
        raise Fund18EffectiveAssessmentIntegrationError(
            "unsupported_fund18_schema"
        )
    if artifact.get("research_only") is not True:
        raise Fund18EffectiveAssessmentIntegrationError(
            "fund18_research_only_not_true"
        )
    if artifact.get("execution_authority") is not False:
        raise Fund18EffectiveAssessmentIntegrationError(
            "fund18_execution_authority_not_false"
        )
    if artifact.get("production_persist") is not False:
        raise Fund18EffectiveAssessmentIntegrationError(
            "fund18_production_persist_not_false"
        )

    policy = normalize_fund18_assessment_policy(
        assessment_policy,
        require_effective=True,
    )

    candidate_exposures = _mapping(
        inputs.get("candidate_exposures"),
        field="candidate_exposures",
    )
    portfolio_weights = _mapping(
        inputs.get("portfolio_weights"),
        field="portfolio_weights",
    )

    portfolio_exposure_raw = inputs.get("portfolio_exposure")
    portfolio_exposure = (
        _mapping(portfolio_exposure_raw, field="portfolio_exposure")
        if portfolio_exposure_raw is not None
        else None
    )

    desired_roles_raw = inputs.get("desired_roles")
    if not isinstance(desired_roles_raw, list):
        raise Fund18EffectiveAssessmentIntegrationError(
            "desired_roles_must_be_list"
        )
    desired_roles = [
        str(role).strip()
        for role in desired_roles_raw
        if str(role).strip()
    ]

    candidates = artifact.get("candidates")
    if not isinstance(candidates, list):
        raise Fund18EffectiveAssessmentIntegrationError(
            "candidates_must_be_list"
        )

    result = deepcopy(artifact)
    result_candidates = result["candidates"]

    seen: set[str] = set()

    for row in result_candidates:
        if not isinstance(row, dict):
            raise Fund18EffectiveAssessmentIntegrationError(
                "candidate_must_be_object"
            )

        code = row.get("fund_code")
        if not isinstance(code, str) or not code:
            raise Fund18EffectiveAssessmentIntegrationError(
                "candidate_fund_code_invalid"
            )
        if code in seen:
            raise Fund18EffectiveAssessmentIntegrationError(
                f"duplicate_candidate:{code}"
            )
        seen.add(code)

        evidence = _mapping(
            row.get("evidence"),
            field=f"candidate_evidence:{code}",
        )

        candidate_exposure_raw = candidate_exposures.get(code)
        candidate_exposure = (
            _mapping(
                candidate_exposure_raw,
                field=f"candidate_exposure:{code}",
            )
            if candidate_exposure_raw is not None
            else None
        )

        weight_raw = portfolio_weights.get(code)
        current_weight_pct = (
            float(weight_raw)
            if weight_raw is not None
            else None
        )

        facts = build_portfolio_fit_assessment_facts(
            fund_code=code,
            evidence=evidence,
            candidate_exposure=candidate_exposure,
            portfolio_exposure=portfolio_exposure,
            current_weight_pct=current_weight_pct,
            desired_roles=desired_roles,
        )

        evaluated = evaluate_portfolio_fit_assessments(
            facts,
            policy,
            mode=MODE_EFFECTIVE,
        ).to_dict()

        for dimension in DIMENSIONS:
            dimension_result = _mapping(
                evaluated.get(dimension),
                field=f"{code}:{dimension}",
            )
            assessment = dimension_result.get("assessment")
            if not isinstance(assessment, str) or not assessment:
                raise Fund18EffectiveAssessmentIntegrationError(
                    f"assessment_missing:{code}:{dimension}"
                )
            row[dimension] = assessment

        row["effective_assessment"] = evaluated

    result["assessment_policy"] = {
        "schema_version": policy.raw["schema_version"],
        "policy_version": policy.raw["policy_version"],
        "decision_id": policy.raw["decision_id"],
        "human_approved": True,
        "locked": True,
        "production_effective": True,
        "mode": MODE_EFFECTIVE,
    }

    evidence_policy = result.get("evidence_policy")
    if isinstance(evidence_policy, dict):
        evidence_policy["effective_assessment_policy_applied"] = True

    limitations = result.get("limitations")
    if isinstance(limitations, list):
        limitations.append(
            "Descriptive assessments may be populated only by the explicit "
            "human-approved, locked, production-effective FUND18 policy."
        )

    return result
