"""FUND21 decision-evaluation readiness contract.

FUND20 deterministic decision-candidate ranking
-> FUND21 decision-evaluation readiness artifact.

FUND21 answers one question only:

"Is this ranked FUND20 candidate contractually ready to be handed to a later
canonical investment-decision evaluation stage?"

FUND21 does NOT:
- create or change ranking,
- select a winner,
- create BUY/SELL/ADD semantics,
- create CONSIDER_NEW_POSITION / CONSIDER_TOP_UP,
- call 8E,
- call New Money,
- create allocation, target weight, quantity, trade, or order,
- persist portfolio or production state.

This is a fail-closed research handoff gate only.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping


INPUT_SCHEMA = "fund20_decision_candidate_ranking_artifact_1"
OUTPUT_SCHEMA = "fund21_decision_evaluation_readiness_artifact_1"

INPUT_STATUS = "DECISION_CANDIDATE_RANKING_COMPLETE"
OUTPUT_STATUS = "DECISION_EVALUATION_READINESS_COMPLETE"

READINESS_READY = "READY"
READINESS_NOT_READY = "NOT_READY"

EVAL_READY = "READY_FOR_DECISION_EVALUATION"
EVAL_NOT_READY = "NOT_READY_FOR_DECISION_EVALUATION"

REASON_UPSTREAM_NOT_RANKING_ELIGIBLE = "UPSTREAM_NOT_RANKING_ELIGIBLE"
REASON_UPSTREAM_READINESS_NOT_READY = "UPSTREAM_READINESS_NOT_READY"
REASON_DECISION_RANK_MISSING = "DECISION_RANK_MISSING"
REASON_UPSTREAM_READINESS_REASONS_PRESENT = "UPSTREAM_READINESS_REASONS_PRESENT"
REASON_ROLE_FIT_INVALID = "ROLE_FIT_INVALID"
REASON_CONCENTRATION_RISK_INVALID = "CONCENTRATION_RISK_INVALID"
REASON_DIVERSIFICATION_INVALID = "DIVERSIFICATION_CONTRIBUTION_INVALID"
REASON_ECONOMIC_OVERLAP_INVALID = "ECONOMIC_OVERLAP_INVALID"
REASON_FI_SCORE_INVALID = "FI_SCORE_INVALID"

ROLE_FIT_VALUES = frozenset({"STRONG", "PARTIAL", "WEAK"})
CONCENTRATION_VALUES = frozenset({"LOW", "MEDIUM", "HIGH"})
DIVERSIFICATION_VALUES = frozenset({"HIGH", "MEDIUM", "LOW"})
ECONOMIC_OVERLAP_VALUES = frozenset({"LOW", "MEDIUM", "HIGH"})

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")

ZERO_WRITE_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "eight_e_calls": 0,
    "new_money_calls": 0,
}


class DecisionEvaluationReadinessContractError(ValueError):
    """Fail-closed FUND21 contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionEvaluationReadinessContractError(
            f"{field}_must_be_mapping"
        )
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise DecisionEvaluationReadinessContractError(
            f"{field}_must_be_list"
        )
    return list(value)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _fund_code(row: Mapping[str, Any]) -> str:
    code = row.get("fund_code")
    if not isinstance(code, str):
        raise DecisionEvaluationReadinessContractError(
            "candidate_fund_code_invalid"
        )
    if not code or code != code.strip() or code != code.upper():
        raise DecisionEvaluationReadinessContractError(
            "candidate_fund_code_invalid"
        )
    if _CODE_RE.fullmatch(code) is None:
        raise DecisionEvaluationReadinessContractError(
            "candidate_fund_code_invalid"
        )
    return code


def _assert_zero_write_proof(value: Any) -> None:
    proof = _as_dict(value, field="write_proof")
    if proof != ZERO_WRITE_PROOF:
        raise DecisionEvaluationReadinessContractError(
            "upstream_write_proof_not_zero"
        )


def _assert_fund20_firewall(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise DecisionEvaluationReadinessContractError(
            "unsupported_fund20_schema"
        )
    upstream_status = artifact.get("decision_ranking_status")
    if upstream_status is None:
        upstream_status = artifact.get("decision_candidate_ranking_status")

    if upstream_status != INPUT_STATUS:
        raise DecisionEvaluationReadinessContractError(
            "upstream_fund20_status_invalid"
        )
    if artifact.get("research_only") is not True:
        raise DecisionEvaluationReadinessContractError(
            "upstream_research_only_not_true"
        )
    if artifact.get("execution_authority") is not False:
        raise DecisionEvaluationReadinessContractError(
            "upstream_execution_authority_not_false"
        )
    if artifact.get("production_persist") is not False:
        raise DecisionEvaluationReadinessContractError(
            "upstream_production_persist_not_false"
        )
    if artifact.get("decision_winner") is not None:
        raise DecisionEvaluationReadinessContractError(
            "upstream_decision_winner_present"
        )
    if artifact.get("recommendation") is not None:
        raise DecisionEvaluationReadinessContractError(
            "upstream_recommendation_present"
        )
    if artifact.get("allocation") is not None:
        raise DecisionEvaluationReadinessContractError(
            "upstream_allocation_present"
        )
    _assert_zero_write_proof(artifact.get("write_proof"))


def _candidate_reasons(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("decision_readiness_reasons", [])
    if not isinstance(raw, (list, tuple)):
        raise DecisionEvaluationReadinessContractError(
            "decision_readiness_reasons_must_be_sequence"
        )
    return [str(item) for item in raw]


def _evaluation_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []

    ranking_eligible = row.get("decision_ranking_eligible")
    if ranking_eligible is not True:
        reasons.append(REASON_UPSTREAM_NOT_RANKING_ELIGIBLE)
        return reasons

    rank = row.get("decision_rank")
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        reasons.append(REASON_DECISION_RANK_MISSING)

    readiness = row.get("decision_readiness")
    if readiness != READINESS_READY:
        reasons.append(REASON_UPSTREAM_READINESS_NOT_READY)

    upstream_reasons = _candidate_reasons(row)
    if upstream_reasons:
        reasons.append(REASON_UPSTREAM_READINESS_REASONS_PRESENT)

    if row.get("role_fit") not in ROLE_FIT_VALUES:
        reasons.append(REASON_ROLE_FIT_INVALID)

    if row.get("concentration_risk") not in CONCENTRATION_VALUES:
        reasons.append(REASON_CONCENTRATION_RISK_INVALID)

    if row.get("diversification_contribution") not in DIVERSIFICATION_VALUES:
        reasons.append(REASON_DIVERSIFICATION_INVALID)

    if row.get("economic_overlap") not in ECONOMIC_OVERLAP_VALUES:
        reasons.append(REASON_ECONOMIC_OVERLAP_INVALID)

    if _finite_number(row.get("fi_score")) is None:
        reasons.append(REASON_FI_SCORE_INVALID)

    return list(dict.fromkeys(reasons))


def _validate_rank_integrity(candidates: list[dict[str, Any]]) -> None:
    ranks: list[int] = []

    for row in candidates:
        eligible = row.get("decision_ranking_eligible")
        rank = row.get("decision_rank")

        if eligible is True:
            if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
                raise DecisionEvaluationReadinessContractError(
                    "eligible_candidate_decision_rank_invalid"
                )
            ranks.append(rank)
        elif eligible is False:
            if rank is not None:
                raise DecisionEvaluationReadinessContractError(
                    "ineligible_candidate_has_decision_rank"
                )
        else:
            raise DecisionEvaluationReadinessContractError(
                "decision_ranking_eligible_must_be_boolean"
            )

    if len(ranks) != len(set(ranks)):
        raise DecisionEvaluationReadinessContractError(
            "duplicate_decision_rank"
        )

    expected = list(range(1, len(ranks) + 1))
    if sorted(ranks) != expected:
        raise DecisionEvaluationReadinessContractError(
            "decision_rank_sequence_invalid"
        )


def build_decision_evaluation_readiness_artifact(
    fund20_artifact: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact = _as_dict(
        fund20_artifact,
        field="fund20_artifact",
    )
    _assert_fund20_firewall(artifact)

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
            raise DecisionEvaluationReadinessContractError(
                f"duplicate_candidate:{code}"
            )
        seen_codes.add(code)
        candidates.append(row)

    _validate_rank_integrity(candidates)

    output_rows: list[dict[str, Any]] = []
    ready_count = 0

    for row in candidates:
        reasons = _evaluation_reasons(row)
        eligible = not reasons

        state = EVAL_READY if eligible else EVAL_NOT_READY
        if eligible:
            ready_count += 1

        out = dict(row)
        out.update(
            {
                "decision_evaluation_readiness": state,
                "decision_evaluation_eligible": eligible,
                "decision_evaluation_reasons": reasons,
                # FUND21 preserves FUND20 rank. It never creates a new rank.
                "decision_evaluation_source_rank": row.get("decision_rank"),
                "decision_action": None,
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
        "decision_evaluation_readiness_status": OUTPUT_STATUS,
        "decision_winner": None,
        "recommendation": None,
        "allocation": None,
        "counts": {
            "candidates": len(output_rows),
            "ready_for_decision_evaluation": ready_count,
            "not_ready_for_decision_evaluation": len(output_rows) - ready_count,
        },
        "candidates": output_rows,
        "write_proof": dict(ZERO_WRITE_PROOF),
        "limitations": [
            "FUND21 is a fail-closed decision-evaluation handoff gate only.",
            "FUND21 preserves FUND20 decision_rank and does not rerank candidates.",
            "READY_FOR_DECISION_EVALUATION is not BUY, SELL, ADD, winner, or recommendation.",
            "FUND21 does not call 8E or New Money.",
            "FUND21 does not create allocation, target weight, quantity, trade, or order.",
            "FUND21 has no portfolio-write or production-persistence authority.",
        ],
    }
