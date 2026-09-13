"""FUND19 decision-readiness research contract.

FUND18 descriptive portfolio-fit research artifact
-> FUND19 decision-readiness research artifact.

FUND19 answers one question only:

    Is there sufficient evidence to advance this candidate
    to a later decision/ranking stage?

It must not create:
- composite score
- cross-candidate rank
- winner
- buy/sell recommendation
- allocation
- trade/order
- 8E/New Money action
- production persistence

Fail closed:
- UNKNOWN descriptive dimensions cannot be decision-ready.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


INPUT_SCHEMA = "fund18_portfolio_fit_research_artifact_1"
OUTPUT_SCHEMA = "fund19_decision_readiness_artifact_1"

READINESS_READY = "READY"
READINESS_NOT_READY = "NOT_READY"

VALID_READINESS = {
    READINESS_READY,
    READINESS_NOT_READY,
}

DESCRIPTIVE_DIMENSIONS = (
    "role_fit",
    "economic_overlap",
    "diversification_contribution",
    "concentration_risk",
)

REASON_UNKNOWN_DESCRIPTIVE_DIMENSION = (
    "UNKNOWN_DESCRIPTIVE_DIMENSION"
)
REASON_UPSTREAM_EVIDENCE_MISSING = "UPSTREAM_EVIDENCE_MISSING"
REASON_UPSTREAM_EVIDENCE_INVALID = "UPSTREAM_EVIDENCE_INVALID"


class DecisionReadinessContractError(ValueError):
    """Fail-closed FUND19 contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionReadinessContractError(
            f"{field}_must_be_object"
        )
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise DecisionReadinessContractError(
            f"{field}_must_be_list"
        )
    return value


def _assert_zero_write_proof(
    artifact: Mapping[str, Any],
) -> None:
    proof = _as_dict(
        artifact.get("write_proof"),
        field="write_proof",
    )

    expected = {
        "production_writes": 0,
        "trade_actions": 0,
        "orders": 0,
        "portfolio_writes": 0,
        "eight_e_calls": 0,
        "new_money_calls": 0,
    }

    if proof != expected:
        raise DecisionReadinessContractError(
            "upstream_write_proof_not_zero"
        )


def _assert_fund18_firewall(
    artifact: Mapping[str, Any],
) -> None:
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise DecisionReadinessContractError(
            "unsupported_fund18_schema"
        )

    if artifact.get("research_only") is not True:
        raise DecisionReadinessContractError(
            "upstream_research_only_not_true"
        )

    if artifact.get("execution_authority") is not False:
        raise DecisionReadinessContractError(
            "upstream_execution_authority_not_false"
        )

    if artifact.get("production_persist") is not False:
        raise DecisionReadinessContractError(
            "upstream_production_persist_not_false"
        )

    if (
        artifact.get("portfolio_fit_status")
        != "DESCRIPTIVE_RESEARCH_COMPLETE"
    ):
        raise DecisionReadinessContractError(
            "descriptive_research_not_complete"
        )

    if artifact.get("portfolio_fit_winner") is not None:
        raise DecisionReadinessContractError(
            "upstream_winner_present"
        )

    if artifact.get(
        "portfolio_fit_composite_score"
    ) is not None:
        raise DecisionReadinessContractError(
            "upstream_composite_score_present"
        )

    if artifact.get("recommendation") is not None:
        raise DecisionReadinessContractError(
            "upstream_recommendation_present"
        )

    _assert_zero_write_proof(artifact)


def _candidate_readiness(
    row: Mapping[str, Any],
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []

    for dimension in DESCRIPTIVE_DIMENSIONS:
        value = row.get(dimension)

        if value is None or value == "UNKNOWN":
            reasons.append(
                f"{REASON_UNKNOWN_DESCRIPTIVE_DIMENSION}:"
                f"{dimension}"
            )

    evidence = row.get("evidence")

    if evidence is None:
        reasons.append(REASON_UPSTREAM_EVIDENCE_MISSING)
    elif not isinstance(evidence, Mapping):
        reasons.append(REASON_UPSTREAM_EVIDENCE_INVALID)
    elif evidence.get("schema_version") != "fund18_portfolio_fit_evidence_1":
        reasons.append(REASON_UPSTREAM_EVIDENCE_INVALID)

    if reasons:
        return READINESS_NOT_READY, tuple(dict.fromkeys(reasons))

    return READINESS_READY, ()


def build_decision_readiness_artifact(
    fund18_artifact: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact = _as_dict(
        fund18_artifact,
        field="fund18_artifact",
    )

    _assert_fund18_firewall(artifact)

    candidates = _as_list(
        artifact.get("candidates"),
        field="candidates",
    )

    output_candidates: list[dict[str, Any]] = []

    seen: set[str] = set()

    for raw in candidates:
        row = _as_dict(raw, field="candidate")

        code = row.get("fund_code")

        if not isinstance(code, str) or not code:
            raise DecisionReadinessContractError(
                "candidate_fund_code_invalid"
            )

        if code in seen:
            raise DecisionReadinessContractError(
                f"duplicate_candidate:{code}"
            )

        seen.add(code)

        readiness, reasons = _candidate_readiness(row)

        output_candidates.append(
            {
                **row,
                "decision_readiness": readiness,
                "decision_readiness_reasons": list(reasons),
                "portfolio_fit_composite_score": None,
                "portfolio_fit_rank": None,
                "recommendation": None,
            }
        )

    timestamp = generated_at

    if timestamp is None:
        timestamp = (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    ready_count = sum(
        row["decision_readiness"] == READINESS_READY
        for row in output_candidates
    )

    not_ready_count = sum(
        row["decision_readiness"] == READINESS_NOT_READY
        for row in output_candidates
    )

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source": {
            "fund18_schema_version": artifact.get(
                "schema_version"
            ),
            "source": artifact.get("source"),
        },
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "decision_readiness_status":
            "DECISION_READINESS_RESEARCH_COMPLETE",
        "portfolio_fit_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
        "counts": {
            "candidates": len(output_candidates),
            "ready": ready_count,
            "not_ready": not_ready_count,
        },
        "candidates": output_candidates,
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
        },
        "limitations": [
            "FUND19 evaluates decision readiness only.",
            "READY does not mean BUY or preferred candidate.",
            "No composite score, ranking, winner, recommendation, allocation, or execution is created.",
            "No production persistence, 8E action, or New Money action is permitted.",
        ],
    }
