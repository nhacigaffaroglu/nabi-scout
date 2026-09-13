"""FUND24 deployment eligibility for Turkish participation funds.

FUND23 canonical recommendation projection
-> deployment-eligibility research artifact.

FUND24 answers only:
"May this candidate proceed to New Money / allocation evaluation?"

FUND24 does NOT:
- recalculate or override the canonical 8E decision,
- rerank candidates,
- select a deployment winner or target,
- call allocate_new_money,
- calculate allocation amount or percentage,
- calculate target weight or quantity,
- create trade or order,
- persist portfolio or production state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from services.portfolio_security_decision_contract import (
    DECISION_AVOID,
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REDUCE,
    DECISION_REVIEW,
    DECISION_WATCH,
)


INPUT_SCHEMA = "fund23_recommendation_layer_artifact_1"
OUTPUT_SCHEMA = "fund24_deployment_eligibility_artifact_1"

INPUT_STATUS = "RECOMMENDATION_LAYER_COMPLETE"
OUTPUT_STATUS = "DEPLOYMENT_ELIGIBILITY_COMPLETE"

STATE_ELIGIBLE = "DEPLOYMENT_ELIGIBLE"
STATE_NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_DEPLOYMENT"
STATE_BLOCKED = "DEPLOYMENT_INPUT_BLOCKED"

UPSTREAM_READY = "RECOMMENDATION_READY"
UPSTREAM_NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_RECOMMENDATION"
UPSTREAM_BLOCKED = "RECOMMENDATION_INPUT_BLOCKED"

DEPLOYABLE_ACTIONS = frozenset(
    {
        DECISION_CONSIDER_NEW_POSITION,
        DECISION_CONSIDER_TOP_UP,
    }
)

NON_DEPLOYABLE_ACTIONS = frozenset(
    {
        DECISION_HOLD,
        DECISION_WATCH,
        DECISION_REVIEW,
        DECISION_REDUCE,
        DECISION_AVOID,
        DECISION_INSUFFICIENT_DATA,
    }
)

REASON_DEPLOYMENT_ELIGIBLE = "CANONICAL_RECOMMENDATION_DEPLOYABLE"
REASON_ACTION_NOT_DEPLOYABLE = "CANONICAL_RECOMMENDATION_NOT_DEPLOYABLE"
REASON_UPSTREAM_BLOCKED = "UPSTREAM_RECOMMENDATION_BLOCKED"
REASON_UPSTREAM_NOT_ELIGIBLE = "UPSTREAM_NOT_RECOMMENDATION_ELIGIBLE"

ZERO_WRITE_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "recommendation_history_writes": 0,
    "new_money_calls": 0,
    "allocation_calls": 0,
}


class FundDeploymentEligibilityContractError(ValueError):
    """Fail-closed FUND24 contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FundDeploymentEligibilityContractError(
            f"{field}_must_be_mapping"
        )
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise FundDeploymentEligibilityContractError(
            f"{field}_must_be_list"
        )
    return list(value)


def _assert_upstream_firewall(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise FundDeploymentEligibilityContractError(
            "unsupported_fund23_schema"
        )

    if artifact.get("recommendation_layer_status") != INPUT_STATUS:
        raise FundDeploymentEligibilityContractError(
            "upstream_fund23_status_invalid"
        )

    if artifact.get("research_only") is not True:
        raise FundDeploymentEligibilityContractError(
            "upstream_research_only_not_true"
        )

    if artifact.get("execution_authority") is not False:
        raise FundDeploymentEligibilityContractError(
            "upstream_execution_authority_not_false"
        )

    if artifact.get("production_persist") is not False:
        raise FundDeploymentEligibilityContractError(
            "upstream_production_persist_not_false"
        )

    for field in (
        "decision_winner",
        "recommended_symbol",
        "allocation",
        "target_weight",
        "quantity",
        "trade",
        "order",
    ):
        if artifact.get(field) is not None:
            raise FundDeploymentEligibilityContractError(
                f"upstream_{field}_present"
            )


def _validate_ready_candidate(row: Mapping[str, Any]) -> None:
    action = row.get("recommendation_action")

    if action not in DEPLOYABLE_ACTIONS | NON_DEPLOYABLE_ACTIONS:
        raise FundDeploymentEligibilityContractError(
            "recommendation_action_invalid"
        )

    canonical = row.get("canonical_decision")
    if canonical != action:
        raise FundDeploymentEligibilityContractError(
            "recommendation_canonical_decision_mismatch"
        )

    recommendation_rank = row.get("recommendation_source_rank")
    canonical_rank = row.get("canonical_decision_source_rank")
    evaluation_rank = row.get("decision_evaluation_source_rank")
    decision_rank = row.get("decision_rank")

    if (
        isinstance(recommendation_rank, bool)
        or not isinstance(recommendation_rank, int)
        or recommendation_rank < 1
    ):
        raise FundDeploymentEligibilityContractError(
            "recommendation_source_rank_invalid"
        )

    if not (
        recommendation_rank
        == canonical_rank
        == evaluation_rank
        == decision_rank
    ):
        raise FundDeploymentEligibilityContractError(
            "deployment_rank_provenance_mismatch"
        )

    if row.get("recommendation_source") != "CANONICAL_8E_DECISION":
        raise FundDeploymentEligibilityContractError(
            "recommendation_source_invalid"
        )


def build_fund_deployment_eligibility_artifact(
    fund23_artifact: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact = _as_dict(
        fund23_artifact,
        field="fund23_artifact",
    )
    _assert_upstream_firewall(artifact)

    raw_candidates = _as_list(
        artifact.get("candidates"),
        field="candidates",
    )

    output_rows: list[dict[str, Any]] = []

    eligible_count = 0
    not_eligible_count = 0
    blocked_count = 0

    seen_codes: set[str] = set()

    for raw in raw_candidates:
        row = _as_dict(raw, field="candidate")

        code = row.get("fund_code")
        if not isinstance(code, str) or not code:
            raise FundDeploymentEligibilityContractError(
                "candidate_fund_code_invalid"
            )

        if code in seen_codes:
            raise FundDeploymentEligibilityContractError(
                f"duplicate_candidate:{code}"
            )
        seen_codes.add(code)

        upstream_state = row.get("recommendation_state")
        out = dict(row)

        if upstream_state == UPSTREAM_READY:
            _validate_ready_candidate(row)

            action = row["recommendation_action"]
            rank = row["recommendation_source_rank"]

            canonical_payload = _as_dict(
                row.get("canonical_decision_payload"),
                field="canonical_decision_payload",
            )
            exposure_increase_allowed = canonical_payload.get(
                "exposure_increase_allowed"
            )

            if (
                action in DEPLOYABLE_ACTIONS
                and exposure_increase_allowed is True
            ):
                eligible_count += 1

                out.update(
                    {
                        "deployment_state": STATE_ELIGIBLE,
                        "deployment_eligible": True,
                        "deployment_action": action,
                        "deployment_reasons": [
                            REASON_DEPLOYMENT_ELIGIBLE,
                            *list(row.get("recommendation_reasons") or []),
                        ],
                        "deployment_source_rank": rank,
                        "deployment_source": "FUND23_RECOMMENDATION",
                    }
                )

            else:
                not_eligible_count += 1

                out.update(
                    {
                        "deployment_state": STATE_NOT_ELIGIBLE,
                        "deployment_eligible": False,
                        "deployment_action": None,
                        "deployment_reasons": [
                            REASON_ACTION_NOT_DEPLOYABLE,
                            *list(row.get("recommendation_reasons") or []),
                        ],
                        "deployment_source_rank": rank,
                        "deployment_source": "FUND23_RECOMMENDATION",
                    }
                )

        elif upstream_state == UPSTREAM_BLOCKED:
            blocked_count += 1

            out.update(
                {
                    "deployment_state": STATE_BLOCKED,
                    "deployment_eligible": False,
                    "deployment_action": None,
                    "deployment_reasons": [
                        REASON_UPSTREAM_BLOCKED,
                        *list(row.get("recommendation_reasons") or []),
                    ],
                    "deployment_source_rank": row.get(
                        "recommendation_source_rank"
                    ),
                    "deployment_source": None,
                }
            )

        elif upstream_state == UPSTREAM_NOT_ELIGIBLE:
            not_eligible_count += 1

            out.update(
                {
                    "deployment_state": STATE_NOT_ELIGIBLE,
                    "deployment_eligible": False,
                    "deployment_action": None,
                    "deployment_reasons": [
                        REASON_UPSTREAM_NOT_ELIGIBLE,
                        *list(row.get("recommendation_reasons") or []),
                    ],
                    "deployment_source_rank": row.get(
                        "recommendation_source_rank"
                    ),
                    "deployment_source": None,
                }
            )

        else:
            raise FundDeploymentEligibilityContractError(
                f"recommendation_state_invalid:{code}"
            )

        out.update(
            {
                "deployment_target": None,
                "deployment_amount": None,
                "allocation": None,
                "allocation_pct": None,
                "target_weight": None,
                "quantity": None,
                "trade": None,
                "order": None,
            }
        )

        output_rows.append(out)

    timestamp = generated_at or datetime.now(
        timezone.utc
    ).isoformat()

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source_schema_version": INPUT_SCHEMA,
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "deployment_eligibility_status": OUTPUT_STATUS,
        "decision_winner": None,
        "recommended_symbol": None,
        "deployment_target": None,
        "deployment_amount": None,
        "allocation": None,
        "allocation_pct": None,
        "target_weight": None,
        "quantity": None,
        "trade": None,
        "order": None,
        "counts": {
            "candidates": len(output_rows),
            "deployment_eligible": eligible_count,
            "not_eligible_for_deployment": not_eligible_count,
            "deployment_inputs_blocked": blocked_count,
        },
        "candidates": output_rows,
        "write_proof": dict(ZERO_WRITE_PROOF),
        "limitations": [
            "FUND24 does not recalculate or override canonical 8E decisions.",
            "Only CONSIDER_NEW_POSITION and CONSIDER_TOP_UP may become deployment eligible.",
            "FUND24 preserves FUND20/FUND21/FUND22/FUND23 rank provenance and never reranks.",
            "FUND24 does not select a deployment winner or deployment target.",
            "FUND24 does not call allocate_new_money.",
            "FUND24 does not calculate deployment amount or allocation percentage.",
            "FUND24 does not create target weight, quantity, trade, or order.",
            "FUND24 does not persist portfolio, recommendation history, or production state.",
        ],
    }
