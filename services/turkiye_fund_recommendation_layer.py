"""FUND23 recommendation layer for Turkish participation funds.

FUND22 canonical Portfolio Security Decision
-> recommendation-facing research artifact.

FUND23 does NOT:
- recalculate or override the canonical 8E decision,
- rerank candidates,
- select a winner or deployment target,
- call NABI Recommendation orchestration,
- call New Money,
- create allocation, target weight, quantity, trade, or order,
- persist recommendation history, portfolio, or production state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from services.portfolio_security_decision_contract import (
    PORTFOLIO_SECURITY_DECISIONS,
)


INPUT_SCHEMA = "fund22_canonical_decision_integration_artifact_1"
OUTPUT_SCHEMA = "fund23_recommendation_layer_artifact_1"

INPUT_STATUS = "CANONICAL_DECISION_INTEGRATION_COMPLETE"
OUTPUT_STATUS = "RECOMMENDATION_LAYER_COMPLETE"

STATE_READY = "RECOMMENDATION_READY"
STATE_NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_RECOMMENDATION"
STATE_BLOCKED = "RECOMMENDATION_INPUT_BLOCKED"

UPSTREAM_EVALUATED = "CANONICAL_DECISION_EVALUATED"
UPSTREAM_NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_CANONICAL_DECISION"
UPSTREAM_BLOCKED = "CANONICAL_DECISION_INPUT_BLOCKED"

REASON_UPSTREAM_NOT_ELIGIBLE = "UPSTREAM_NOT_CANONICAL_DECISION_ELIGIBLE"
REASON_UPSTREAM_BLOCKED = "UPSTREAM_CANONICAL_DECISION_BLOCKED"

ZERO_WRITE_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "recommendation_history_writes": 0,
    "new_money_calls": 0,
}


class FundRecommendationLayerContractError(ValueError):
    """Fail-closed FUND23 contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FundRecommendationLayerContractError(
            f"{field}_must_be_mapping"
        )
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise FundRecommendationLayerContractError(
            f"{field}_must_be_list"
        )
    return list(value)


def _assert_upstream_firewall(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise FundRecommendationLayerContractError(
            "unsupported_fund22_schema"
        )

    if artifact.get("canonical_decision_integration_status") != INPUT_STATUS:
        raise FundRecommendationLayerContractError(
            "upstream_fund22_status_invalid"
        )

    if artifact.get("research_only") is not True:
        raise FundRecommendationLayerContractError(
            "upstream_research_only_not_true"
        )

    if artifact.get("execution_authority") is not False:
        raise FundRecommendationLayerContractError(
            "upstream_execution_authority_not_false"
        )

    if artifact.get("production_persist") is not False:
        raise FundRecommendationLayerContractError(
            "upstream_production_persist_not_false"
        )

    if artifact.get("decision_winner") is not None:
        raise FundRecommendationLayerContractError(
            "upstream_decision_winner_present"
        )

    if artifact.get("recommendation") is not None:
        raise FundRecommendationLayerContractError(
            "upstream_recommendation_present"
        )

    if artifact.get("allocation") is not None:
        raise FundRecommendationLayerContractError(
            "upstream_allocation_present"
        )


def _validate_evaluated_candidate(row: Mapping[str, Any]) -> None:
    decision = row.get("canonical_decision")

    if decision not in PORTFOLIO_SECURITY_DECISIONS:
        raise FundRecommendationLayerContractError(
            "canonical_decision_invalid"
        )

    payload = _as_dict(
        row.get("canonical_decision_payload"),
        field="canonical_decision_payload",
    )

    if payload.get("decision") != decision:
        raise FundRecommendationLayerContractError(
            "canonical_decision_payload_mismatch"
        )

    rank = row.get("canonical_decision_source_rank")
    upstream_rank = row.get("decision_evaluation_source_rank")

    if (
        isinstance(rank, bool)
        or not isinstance(rank, int)
        or rank < 1
    ):
        raise FundRecommendationLayerContractError(
            "canonical_decision_source_rank_invalid"
        )

    if rank != upstream_rank or rank != row.get("decision_rank"):
        raise FundRecommendationLayerContractError(
            "recommendation_rank_provenance_mismatch"
        )

    provenance = row.get("canonical_snapshot_provenance")
    if not isinstance(provenance, Mapping):
        raise FundRecommendationLayerContractError(
            "canonical_snapshot_provenance_missing"
        )


def build_fund_recommendation_layer_artifact(
    fund22_artifact: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact = _as_dict(
        fund22_artifact,
        field="fund22_artifact",
    )
    _assert_upstream_firewall(artifact)

    raw_candidates = _as_list(
        artifact.get("candidates"),
        field="candidates",
    )

    output_rows: list[dict[str, Any]] = []
    ready_count = 0
    blocked_count = 0
    not_eligible_count = 0

    seen_codes: set[str] = set()

    for raw in raw_candidates:
        row = _as_dict(raw, field="candidate")

        code = row.get("fund_code")
        if not isinstance(code, str) or not code:
            raise FundRecommendationLayerContractError(
                "candidate_fund_code_invalid"
            )

        if code in seen_codes:
            raise FundRecommendationLayerContractError(
                f"duplicate_candidate:{code}"
            )
        seen_codes.add(code)

        upstream_state = row.get(
            "canonical_decision_integration_state"
        )

        out = dict(row)

        if upstream_state == UPSTREAM_EVALUATED:
            _validate_evaluated_candidate(row)

            ready_count += 1

            out.update(
                {
                    "recommendation_state": STATE_READY,
                    "recommendation_action": row["canonical_decision"],
                    "recommendation_reasons": list(
                        row.get("canonical_decision_reasons") or []
                    ),
                    "recommendation_source_rank": row[
                        "canonical_decision_source_rank"
                    ],
                    "recommendation_source": "CANONICAL_8E_DECISION",
                    "recommended_symbol": None,
                    "decision_winner": None,
                    "allocation": None,
                    "target_weight": None,
                    "quantity": None,
                    "trade": None,
                    "order": None,
                }
            )

        elif upstream_state == UPSTREAM_BLOCKED:
            blocked_count += 1

            out.update(
                {
                    "recommendation_state": STATE_BLOCKED,
                    "recommendation_action": None,
                    "recommendation_reasons": [
                        REASON_UPSTREAM_BLOCKED,
                        *list(
                            row.get(
                                "canonical_decision_reasons"
                            )
                            or []
                        ),
                    ],
                    "recommendation_source_rank": row.get(
                        "canonical_decision_source_rank"
                    ),
                    "recommendation_source": None,
                    "recommended_symbol": None,
                    "decision_winner": None,
                    "allocation": None,
                    "target_weight": None,
                    "quantity": None,
                    "trade": None,
                    "order": None,
                }
            )

        elif upstream_state == UPSTREAM_NOT_ELIGIBLE:
            not_eligible_count += 1

            out.update(
                {
                    "recommendation_state": STATE_NOT_ELIGIBLE,
                    "recommendation_action": None,
                    "recommendation_reasons": [
                        REASON_UPSTREAM_NOT_ELIGIBLE
                    ],
                    "recommendation_source_rank": row.get(
                        "canonical_decision_source_rank"
                    ),
                    "recommendation_source": None,
                    "recommended_symbol": None,
                    "decision_winner": None,
                    "allocation": None,
                    "target_weight": None,
                    "quantity": None,
                    "trade": None,
                    "order": None,
                }
            )

        else:
            raise FundRecommendationLayerContractError(
                f"canonical_integration_state_invalid:{code}"
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
        "recommendation_layer_status": OUTPUT_STATUS,
        "decision_winner": None,
        "recommended_symbol": None,
        "allocation": None,
        "target_weight": None,
        "quantity": None,
        "trade": None,
        "order": None,
        "counts": {
            "candidates": len(output_rows),
            "recommendation_ready": ready_count,
            "recommendation_inputs_blocked": blocked_count,
            "not_eligible_for_recommendation": not_eligible_count,
        },
        "candidates": output_rows,
        "write_proof": dict(ZERO_WRITE_PROOF),
        "limitations": [
            "FUND23 does not recalculate or override canonical 8E decisions.",
            "Recommendation action is a projection of the canonical decision.",
            "FUND23 preserves FUND20/FUND21/FUND22 rank provenance and never reranks.",
            "FUND23 does not select a recommendation winner or deployment symbol.",
            "FUND23 does not call build_nabi_recommendation or build_nabi_decision_v3.",
            "FUND23 does not call New Money.",
            "FUND23 does not create allocation, target weight, quantity, trade, or order.",
            "FUND23 does not persist recommendation history, portfolio, or production state.",
        ],
    }
