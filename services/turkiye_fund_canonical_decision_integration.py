"""FUND22 canonical decision integration.

FUND21 decision-evaluation readiness
-> persisted canonical Turkish-fund snapshots
-> existing Portfolio Security Decision engine.

FUND22 does NOT:
- create or change FUND20 ranking,
- select a winner,
- build recommendation,
- call New Money,
- create allocation, target weight, quantity, trade, or order,
- persist portfolio or production state.

Canonical investment-decision semantics remain owned by the existing
Portfolio Security Decision engine.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from services.turkiye_fund_decision_evaluation_readiness import (
    EVAL_NOT_READY,
    EVAL_READY,
)
from services.turkiye_fund_snapshot_reader import (
    SnapshotReadError,
    read_turkiye_fund_canonical,
)


INPUT_SCHEMA = "fund21_decision_evaluation_readiness_artifact_1"
OUTPUT_SCHEMA = "fund22_canonical_decision_integration_artifact_1"

INPUT_STATUS = "DECISION_EVALUATION_READINESS_COMPLETE"
OUTPUT_STATUS = "CANONICAL_DECISION_INTEGRATION_COMPLETE"

STATE_EVALUATED = "CANONICAL_DECISION_EVALUATED"
STATE_NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_CANONICAL_DECISION"
STATE_BLOCKED = "CANONICAL_DECISION_INPUT_BLOCKED"

REASON_UPSTREAM_NOT_ELIGIBLE = "UPSTREAM_NOT_DECISION_EVALUATION_ELIGIBLE"
REASON_CANONICAL_SNAPSHOT_BLOCKED = "CANONICAL_SNAPSHOT_BLOCKED"

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")

ZERO_WRITE_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "eight_e_persistence_writes": 0,
    "new_money_calls": 0,
}


class CanonicalDecisionIntegrationContractError(ValueError):
    """Fail-closed FUND22 contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalDecisionIntegrationContractError(
            f"{field}_must_be_mapping"
        )
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise CanonicalDecisionIntegrationContractError(
            f"{field}_must_be_list"
        )
    return list(value)


def _fund_code(row: Mapping[str, Any]) -> str:
    code = row.get("fund_code")
    if not isinstance(code, str):
        raise CanonicalDecisionIntegrationContractError(
            "candidate_fund_code_invalid"
        )
    if not code or code != code.strip() or code != code.upper():
        raise CanonicalDecisionIntegrationContractError(
            "candidate_fund_code_invalid"
        )
    if _CODE_RE.fullmatch(code) is None:
        raise CanonicalDecisionIntegrationContractError(
            "candidate_fund_code_invalid"
        )
    return code


def _finite_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _assert_upstream_write_proof(value: Any) -> None:
    proof = _as_dict(value, field="write_proof")
    required_zero = {
        "production_writes",
        "trade_actions",
        "orders",
        "portfolio_writes",
        "eight_e_calls",
        "new_money_calls",
    }
    if set(proof) != required_zero:
        raise CanonicalDecisionIntegrationContractError(
            "upstream_write_proof_shape_invalid"
        )
    if any(proof[key] != 0 for key in required_zero):
        raise CanonicalDecisionIntegrationContractError(
            "upstream_write_proof_not_zero"
        )


def _assert_fund21_firewall(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise CanonicalDecisionIntegrationContractError(
            "unsupported_fund21_schema"
        )
    if artifact.get("decision_evaluation_readiness_status") != INPUT_STATUS:
        raise CanonicalDecisionIntegrationContractError(
            "upstream_fund21_status_invalid"
        )
    if artifact.get("research_only") is not True:
        raise CanonicalDecisionIntegrationContractError(
            "upstream_research_only_not_true"
        )
    if artifact.get("execution_authority") is not False:
        raise CanonicalDecisionIntegrationContractError(
            "upstream_execution_authority_not_false"
        )
    if artifact.get("production_persist") is not False:
        raise CanonicalDecisionIntegrationContractError(
            "upstream_production_persist_not_false"
        )
    if artifact.get("decision_winner") is not None:
        raise CanonicalDecisionIntegrationContractError(
            "upstream_decision_winner_present"
        )
    if artifact.get("recommendation") is not None:
        raise CanonicalDecisionIntegrationContractError(
            "upstream_recommendation_present"
        )
    if artifact.get("allocation") is not None:
        raise CanonicalDecisionIntegrationContractError(
            "upstream_allocation_present"
        )
    _assert_upstream_write_proof(artifact.get("write_proof"))


def _validate_candidate_contract(row: Mapping[str, Any]) -> None:
    eligible = row.get("decision_evaluation_eligible")
    if not isinstance(eligible, bool):
        raise CanonicalDecisionIntegrationContractError(
            "decision_evaluation_eligible_must_be_boolean"
        )

    readiness = row.get("decision_evaluation_readiness")

    if eligible:
        if readiness != EVAL_READY:
            raise CanonicalDecisionIntegrationContractError(
                "eligible_candidate_readiness_invalid"
            )

        rank = row.get("decision_evaluation_source_rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise CanonicalDecisionIntegrationContractError(
                "eligible_candidate_source_rank_invalid"
            )

        if row.get("decision_rank") != rank:
            raise CanonicalDecisionIntegrationContractError(
                "decision_rank_provenance_mismatch"
            )

        if row.get("decision_ranking_eligible") is not True:
            raise CanonicalDecisionIntegrationContractError(
                "eligible_candidate_upstream_ranking_invalid"
            )
    else:
        if readiness != EVAL_NOT_READY:
            raise CanonicalDecisionIntegrationContractError(
                "ineligible_candidate_readiness_invalid"
            )


def _portfolio_context(
    code: str,
    contexts: Mapping[str, Any],
) -> tuple[bool, Optional[float]]:
    if code not in contexts:
        raise CanonicalDecisionIntegrationContractError(
            f"portfolio_context_missing:{code}"
        )

    raw = contexts[code]
    ctx = _as_dict(raw, field=f"portfolio_context:{code}")

    if "is_holding" not in ctx:
        raise CanonicalDecisionIntegrationContractError(
            f"portfolio_context_is_holding_missing:{code}"
        )

    unknown = set(ctx) - {"is_holding", "portfolio_weight"}
    if unknown:
        raise CanonicalDecisionIntegrationContractError(
            f"portfolio_context_unknown_fields:{code}"
        )

    is_holding = ctx.get("is_holding", False)
    if not isinstance(is_holding, bool):
        raise CanonicalDecisionIntegrationContractError(
            f"portfolio_context_is_holding_invalid:{code}"
        )

    raw_weight = ctx.get("portfolio_weight")
    weight = _finite_number(raw_weight)

    if raw_weight is not None and weight is None:
        raise CanonicalDecisionIntegrationContractError(
            f"portfolio_context_weight_invalid:{code}"
        )

    if weight is not None and (weight < 0 or weight > 100):
        raise CanonicalDecisionIntegrationContractError(
            f"portfolio_context_weight_out_of_range:{code}"
        )

    if not is_holding and weight is not None:
        raise CanonicalDecisionIntegrationContractError(
            f"nonholding_candidate_has_portfolio_weight:{code}"
        )

    return is_holding, weight


def build_canonical_decision_integration_artifact(
    fund21_artifact: Mapping[str, Any],
    *,
    participation_repo: Any,
    snapshot_repo: Any,
    portfolio_contexts: Optional[Mapping[str, Any]] = None,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    artifact = _as_dict(
        fund21_artifact,
        field="fund21_artifact",
    )
    _assert_fund21_firewall(artifact)

    contexts = (
        {}
        if portfolio_contexts is None
        else _as_dict(portfolio_contexts, field="portfolio_contexts")
    )

    raw_candidates = _as_list(
        artifact.get("candidates"),
        field="candidates",
    )

    candidates: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    for raw in raw_candidates:
        row = _as_dict(raw, field="candidate")
        code = _fund_code(row)
        if code in seen_codes:
            raise CanonicalDecisionIntegrationContractError(
                f"duplicate_candidate:{code}"
            )
        seen_codes.add(code)
        _validate_candidate_contract(row)
        candidates.append(row)

    output_rows: list[dict[str, Any]] = []
    evaluated_count = 0
    blocked_count = 0
    not_eligible_count = 0

    for row in candidates:
        code = str(row["fund_code"])
        eligible = row["decision_evaluation_eligible"]

        out = dict(row)

        if not eligible:
            not_eligible_count += 1
            out.update(
                {
                    "canonical_decision_integration_state": STATE_NOT_ELIGIBLE,
                    "canonical_decision": None,
                    "canonical_decision_payload": None,
                    "canonical_decision_reasons": [
                        REASON_UPSTREAM_NOT_ELIGIBLE
                    ],
                    "canonical_decision_source_rank": row.get(
                        "decision_evaluation_source_rank"
                    ),
                    "canonical_snapshot_provenance": None,
                    "decision_winner": None,
                    "recommendation": None,
                    "allocation": None,
                }
            )
            output_rows.append(out)
            continue

        is_holding, portfolio_weight = _portfolio_context(
            code,
            contexts,
        )

        try:
            canonical = read_turkiye_fund_canonical(
                participation_repo=participation_repo,
                snapshot_repo=snapshot_repo,
                fund_code=code,
                is_holding=is_holding,
                portfolio_weight=portfolio_weight,
            )
        except SnapshotReadError as exc:
            blocked_count += 1
            out.update(
                {
                    "canonical_decision_integration_state": STATE_BLOCKED,
                    "canonical_decision": None,
                    "canonical_decision_payload": None,
                    "canonical_decision_reasons": [
                        REASON_CANONICAL_SNAPSHOT_BLOCKED,
                        str(exc.reason),
                    ],
                    "canonical_decision_source_rank": row.get(
                        "decision_evaluation_source_rank"
                    ),
                    "canonical_snapshot_provenance": None,
                    "decision_winner": None,
                    "recommendation": None,
                    "allocation": None,
                }
            )
            output_rows.append(out)
            continue

        decision = canonical.decision.to_dict()

        evaluated_count += 1
        out.update(
            {
                "canonical_decision_integration_state": STATE_EVALUATED,
                "canonical_decision": decision["decision"],
                "canonical_decision_payload": decision,
                "canonical_decision_reasons": list(
                    decision.get("reason_codes") or []
                ),
                "canonical_decision_source_rank": row.get(
                    "decision_evaluation_source_rank"
                ),
                "canonical_snapshot_provenance": {
                    "participation_row_id": canonical.participation.row_id,
                    "participation_methodology_id":
                        canonical.participation.methodology_id,
                    "participation_methodology_version":
                        canonical.participation.methodology_version,
                    "participation_semantic_identity":
                        canonical.participation.semantic_identity,
                    "fi_row_id": canonical.fund_intelligence.row_id,
                    "fi_as_of_key": canonical.fund_intelligence.as_of_key,
                    "fi_facts_version":
                        canonical.fund_intelligence.facts_version,
                    "fi_engine_version":
                        canonical.fund_intelligence.engine_version,
                },
                "decision_winner": None,
                "recommendation": None,
                "allocation": None,
            }
        )
        output_rows.append(out)

    timestamp = generated_at or datetime.now(timezone.utc).isoformat()

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source_schema_version": INPUT_SCHEMA,
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "canonical_decision_integration_status": OUTPUT_STATUS,
        "decision_winner": None,
        "recommendation": None,
        "allocation": None,
        "counts": {
            "candidates": len(output_rows),
            "canonical_decisions_evaluated": evaluated_count,
            "canonical_inputs_blocked": blocked_count,
            "not_eligible_for_canonical_decision": not_eligible_count,
        },
        "candidates": output_rows,
        "write_proof": dict(ZERO_WRITE_PROOF),
        "limitations": [
            "FUND22 reuses the existing canonical Portfolio Security Decision engine.",
            "FUND22 reads persisted Participation and Fund Intelligence snapshots only.",
            "FUND22 preserves FUND20/FUND21 rank provenance and never reranks.",
            "Canonical decision output is not a BUY/SELL order or winner selection.",
            "FUND22 does not build Recommendation or call New Money.",
            "FUND22 does not create allocation, target weight, quantity, trade, or order.",
            "FUND22 has no portfolio-write or production-persistence authority.",
        ],
    }
