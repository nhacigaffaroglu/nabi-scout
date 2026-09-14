"""FUND18 portfolio-fit policy simulation.

Simulation is deliberately non-production:
- does not alter FUND18 production assessments,
- does not feed FUND19/FUND22,
- does not persist,
- does not create ranking/recommendation/allocation/execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from services.turkiye_fund_portfolio_fit_assessment_engine import (
    MODE_SIMULATION,
    evaluate_portfolio_fit_assessments,
)
from services.turkiye_fund_portfolio_fit_assessment_facts import (
    build_portfolio_fit_assessment_facts,
)
from services.turkiye_fund_portfolio_fit_assessment_policy import (
    Fund18AssessmentPolicy,
)


OUTPUT_SCHEMA = "fund18_policy_simulation_artifact_1"


class Fund18PolicySimulationError(ValueError):
    """Fail-closed simulation contract error."""


def _as_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Fund18PolicySimulationError(
            f"{field}_must_be_object"
        )
    return dict(value)


def build_fund18_policy_simulation_artifact(
    *,
    production_fund18_artifact: Mapping[str, Any],
    assessment_inputs: Mapping[str, Any],
    policy: Fund18AssessmentPolicy,
    generated_at: str | None = None,
) -> dict[str, Any]:
    production = _as_mapping(
        production_fund18_artifact,
        field="production_fund18_artifact",
    )

    if (
        production.get("schema_version")
        != "fund18_portfolio_fit_research_artifact_1"
    ):
        raise Fund18PolicySimulationError(
            "unsupported_production_fund18_schema"
        )

    if production.get("research_only") is not True:
        raise Fund18PolicySimulationError(
            "production_research_only_not_true"
        )

    if production.get("execution_authority") is not False:
        raise Fund18PolicySimulationError(
            "production_execution_authority_not_false"
        )

    if production.get("production_persist") is not False:
        raise Fund18PolicySimulationError(
            "production_persist_not_false"
        )

    if policy.production_effective:
        raise Fund18PolicySimulationError(
            "simulation_requires_non_effective_policy"
        )

    candidates = production.get("candidates")
    if not isinstance(candidates, list):
        raise Fund18PolicySimulationError(
            "production_candidates_must_be_list"
        )

    candidate_exposures = assessment_inputs.get(
        "candidate_exposures"
    )
    portfolio_exposure = assessment_inputs.get(
        "portfolio_exposure"
    )
    portfolio_weights = assessment_inputs.get(
        "portfolio_weights"
    )
    desired_roles = assessment_inputs.get(
        "desired_roles"
    )

    if not isinstance(candidate_exposures, Mapping):
        raise Fund18PolicySimulationError(
            "candidate_exposures_must_be_object"
        )

    if not isinstance(portfolio_exposure, Mapping):
        raise Fund18PolicySimulationError(
            "portfolio_exposure_must_be_object"
        )

    if not isinstance(portfolio_weights, Mapping):
        raise Fund18PolicySimulationError(
            "portfolio_weights_must_be_object"
        )

    if not isinstance(desired_roles, Sequence) or isinstance(
        desired_roles,
        (str, bytes),
    ):
        raise Fund18PolicySimulationError(
            "desired_roles_must_be_sequence"
        )

    simulated: list[dict[str, Any]] = []

    seen: set[str] = set()

    for raw in candidates:
        if not isinstance(raw, Mapping):
            raise Fund18PolicySimulationError(
                "candidate_must_be_object"
            )

        row = dict(raw)
        code = row.get("fund_code")

        if not isinstance(code, str) or not code:
            raise Fund18PolicySimulationError(
                "candidate_fund_code_invalid"
            )

        if code in seen:
            raise Fund18PolicySimulationError(
                f"duplicate_candidate:{code}"
            )
        seen.add(code)

        evidence = row.get("evidence")
        if not isinstance(evidence, Mapping):
            raise Fund18PolicySimulationError(
                f"candidate_evidence_invalid:{code}"
            )

        facts = build_portfolio_fit_assessment_facts(
            fund_code=code,
            evidence=evidence,
            candidate_exposure=candidate_exposures.get(code),
            portfolio_exposure=portfolio_exposure,
            current_weight_pct=portfolio_weights.get(code),
            desired_roles=desired_roles,
        )

        result = evaluate_portfolio_fit_assessments(
            facts,
            policy,
            mode=MODE_SIMULATION,
        )

        simulated.append(result.to_dict())

    timestamp = generated_at
    if timestamp is None:
        timestamp = (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    return {
        "schema_version": OUTPUT_SCHEMA,
        "generated_at": timestamp,
        "mode": MODE_SIMULATION,
        "policy": {
            "schema_version": policy.raw["schema_version"],
            "policy_version": policy.raw["policy_version"],
            "decision_id": policy.raw["decision_id"],
            "human_approved": policy.raw["human_approved"],
            "locked": policy.raw["locked"],
            "production_effective":
                policy.raw["production_effective"],
        },
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "production_assessments_unchanged": True,
        "candidate_count": len(simulated),
        "simulated_assessments": simulated,
        "write_proof": {
            "production_writes": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
            "trade_actions": 0,
            "orders": 0,
        },
        "limitations": [
            "Simulation output cannot alter production FUND18 assessments.",
            "Simulation output cannot be consumed as FUND19 input.",
            "Simulation output creates no rank, recommendation, allocation, trade, order, or production write.",
        ],
    }
