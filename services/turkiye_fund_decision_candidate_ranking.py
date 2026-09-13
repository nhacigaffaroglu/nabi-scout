"""FUND20 decision-candidate ranking contract.

FUND19 decision-readiness research artifact
-> FUND20 deterministic decision-candidate ranking artifact.

FUND20 answers one question only:

    Among decision-ready candidates, what is the deterministic
    research ordering given the existing portfolio-fit evidence?

It must not:
- recalculate Fund Intelligence score,
- create a composite investment score,
- declare a winner,
- create a buy/sell recommendation,
- create allocation or position sizing,
- call 8E or New Money,
- place trades/orders,
- write portfolio or production state.

Rank #1 is not a BUY instruction and is not a winner.

Ranking policy:
1. role_fit:
   STRONG > PARTIAL > WEAK
2. concentration_risk:
   LOW > MEDIUM > HIGH
3. diversification_contribution:
   HIGH > MEDIUM > LOW
4. economic_overlap:
   LOW > MEDIUM > HIGH
5. fi_score DESC
6. data_completeness DESC
7. confidence DESC
8. fund_code ASC

Fail closed:
- only FUND19 READY candidates may be ranked,
- malformed READY candidates are upstream contract violations,
- execution authority always remains false.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any, Mapping


INPUT_SCHEMA = "fund19_decision_readiness_artifact_1"
OUTPUT_SCHEMA = "fund20_decision_candidate_ranking_artifact_1"

INPUT_STATUS = "DECISION_READINESS_RESEARCH_COMPLETE"
OUTPUT_STATUS = "DECISION_CANDIDATE_RANKING_COMPLETE"

READINESS_READY = "READY"
READINESS_NOT_READY = "NOT_READY"

VALID_READINESS = {
    READINESS_READY,
    READINESS_NOT_READY,
}

RANKING_BASIS = (
    "role_fit_desc",
    "concentration_risk_asc",
    "diversification_contribution_desc",
    "economic_overlap_asc",
    "fi_score_desc",
    "data_completeness_desc",
    "confidence_desc",
    "fund_code_asc",
)

ROLE_FIT_ORDER = {
    "STRONG": 0,
    "PARTIAL": 1,
    "WEAK": 2,
}

CONCENTRATION_RISK_ORDER = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
}

DIVERSIFICATION_ORDER = {
    "HIGH": 0,
    "MEDIUM": 1,
    "LOW": 2,
}

ECONOMIC_OVERLAP_ORDER = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
}

_CODE_RE = re.compile(
    r"^[A-Z0-9][A-Z0-9._-]{0,15}$"
)

ZERO_WRITE_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "eight_e_calls": 0,
    "new_money_calls": 0,
}


class DecisionCandidateRankingContractError(ValueError):
    """Fail-closed FUND20 contract violation."""


def _as_dict(
    value: Any,
    *,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionCandidateRankingContractError(
            f"{field}_must_be_object"
        )
    return dict(value)


def _as_list(
    value: Any,
    *,
    field: str,
) -> list[Any]:
    if not isinstance(value, list):
        raise DecisionCandidateRankingContractError(
            f"{field}_must_be_list"
        )
    return value


def _finite_number(value: Any) -> float | None:
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        return None

    result = float(value)

    if not math.isfinite(result):
        return None

    return result


def _optional_metric_for_sort(value: Any) -> float:
    number = _finite_number(value)
    return number if number is not None else -1.0


def _assert_zero_write_proof(
    artifact: Mapping[str, Any],
) -> None:
    proof = _as_dict(
        artifact.get("write_proof"),
        field="write_proof",
    )

    if proof != ZERO_WRITE_PROOF:
        raise DecisionCandidateRankingContractError(
            "upstream_write_proof_not_zero"
        )


def _assert_fund19_firewall(
    artifact: Mapping[str, Any],
) -> None:
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise DecisionCandidateRankingContractError(
            "unsupported_fund19_schema"
        )

    if artifact.get("research_only") is not True:
        raise DecisionCandidateRankingContractError(
            "upstream_research_only_not_true"
        )

    if artifact.get("execution_authority") is not False:
        raise DecisionCandidateRankingContractError(
            "upstream_execution_authority_not_false"
        )

    if artifact.get("production_persist") is not False:
        raise DecisionCandidateRankingContractError(
            "upstream_production_persist_not_false"
        )

    if artifact.get("decision_readiness_status") != INPUT_STATUS:
        raise DecisionCandidateRankingContractError(
            "decision_readiness_research_not_complete"
        )

    if artifact.get("portfolio_fit_winner") is not None:
        raise DecisionCandidateRankingContractError(
            "upstream_winner_present"
        )

    if artifact.get(
        "portfolio_fit_composite_score"
    ) is not None:
        raise DecisionCandidateRankingContractError(
            "upstream_composite_score_present"
        )

    if artifact.get("recommendation") is not None:
        raise DecisionCandidateRankingContractError(
            "upstream_recommendation_present"
        )

    _assert_zero_write_proof(artifact)


def _validated_enum(
    row: Mapping[str, Any],
    *,
    field: str,
    allowed: Mapping[str, int],
    fund_code: str,
) -> str:
    value = row.get(field)

    if value not in allowed:
        raise DecisionCandidateRankingContractError(
            f"ready_candidate_{field}_invalid:{fund_code}"
        )

    return str(value)


def _validate_ready_candidate(
    row: Mapping[str, Any],
    *,
    fund_code: str,
) -> None:
    _validated_enum(
        row,
        field="role_fit",
        allowed=ROLE_FIT_ORDER,
        fund_code=fund_code,
    )

    _validated_enum(
        row,
        field="concentration_risk",
        allowed=CONCENTRATION_RISK_ORDER,
        fund_code=fund_code,
    )

    _validated_enum(
        row,
        field="diversification_contribution",
        allowed=DIVERSIFICATION_ORDER,
        fund_code=fund_code,
    )

    _validated_enum(
        row,
        field="economic_overlap",
        allowed=ECONOMIC_OVERLAP_ORDER,
        fund_code=fund_code,
    )

    if _finite_number(row.get("fi_score")) is None:
        raise DecisionCandidateRankingContractError(
            f"ready_candidate_fi_score_invalid:{fund_code}"
        )


def _rank_key(
    row: Mapping[str, Any],
) -> tuple[Any, ...]:
    return (
        ROLE_FIT_ORDER[str(row["role_fit"])],
        CONCENTRATION_RISK_ORDER[
            str(row["concentration_risk"])
        ],
        DIVERSIFICATION_ORDER[
            str(row["diversification_contribution"])
        ],
        ECONOMIC_OVERLAP_ORDER[
            str(row["economic_overlap"])
        ],
        -float(row["fi_score"]),
        -_optional_metric_for_sort(
            row.get("data_completeness")
        ),
        -_optional_metric_for_sort(
            row.get("confidence")
        ),
        str(row["fund_code"]),
    )


def build_decision_candidate_ranking_artifact(
    fund19_artifact: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact = _as_dict(
        fund19_artifact,
        field="fund19_artifact",
    )

    _assert_fund19_firewall(artifact)

    candidates = _as_list(
        artifact.get("candidates"),
        field="candidates",
    )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in candidates:
        row = _as_dict(
            raw,
            field="candidate",
        )

        code = row.get("fund_code")

        if (
            not isinstance(code, str)
            or not code
            or code != code.strip()
            or code != code.upper()
            or not _CODE_RE.fullmatch(code)
        ):
            raise DecisionCandidateRankingContractError(
                "candidate_fund_code_invalid"
            )

        if code in seen:
            raise DecisionCandidateRankingContractError(
                f"duplicate_candidate:{code}"
            )

        seen.add(code)

        readiness = row.get("decision_readiness")

        if readiness not in VALID_READINESS:
            raise DecisionCandidateRankingContractError(
                f"candidate_decision_readiness_invalid:{code}"
            )

        reasons = row.get("decision_readiness_reasons")

        if not isinstance(reasons, (list, tuple)):
            raise DecisionCandidateRankingContractError(
                f"candidate_readiness_reasons_invalid:{code}"
            )

        if readiness == READINESS_READY:
            if reasons:
                raise DecisionCandidateRankingContractError(
                    f"ready_candidate_has_readiness_reasons:{code}"
                )

            _validate_ready_candidate(
                row,
                fund_code=code,
            )

        elif not reasons:
            raise DecisionCandidateRankingContractError(
                f"not_ready_candidate_missing_readiness_reasons:{code}"
            )

        normalized.append(row)

    ready_rows = [
        row
        for row in normalized
        if row["decision_readiness"] == READINESS_READY
    ]

    ordered = sorted(
        ready_rows,
        key=_rank_key,
    )

    rank_map = {
        row["fund_code"]: index
        for index, row in enumerate(
            ordered,
            start=1,
        )
    }

    output_candidates: list[dict[str, Any]] = []

    for row in normalized:
        code = str(row["fund_code"])
        ready = (
            row["decision_readiness"]
            == READINESS_READY
        )

        output_candidates.append(
            {
                **row,
                "decision_rank":
                    rank_map.get(code),
                "decision_ranking_eligible":
                    ready,
                "decision_ranking_basis":
                    list(RANKING_BASIS),
                "decision_ranking_reasons":
                    (
                        []
                        if ready
                        else list(
                            row.get(
                                "decision_readiness_reasons"
                            )
                            or []
                        )
                    ),
                "decision_winner": None,
                "recommendation": None,
                "allocation": None,
            }
        )

    timestamp = generated_at

    if timestamp is None:
        timestamp = (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    not_ready_count = sum(
        row["decision_readiness"]
        == READINESS_NOT_READY
        for row in normalized
    )

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source": {
            "fund19_schema_version":
                artifact.get("schema_version"),
            "source":
                artifact.get("source"),
        },
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "decision_ranking_status":
            OUTPUT_STATUS,
        "decision_ranking_basis":
            list(RANKING_BASIS),
        "decision_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
        "allocation": None,
        "counts": {
            "candidates":
                len(output_candidates),
            "ready":
                len(ready_rows),
            "ranked":
                len(ordered),
            "not_ready":
                not_ready_count,
        },
        "candidates":
            output_candidates,
        "write_proof":
            dict(ZERO_WRITE_PROOF),
        "limitations": [
            (
                "FUND20 ranks only FUND19 READY "
                "decision candidates."
            ),
            (
                "Decision rank is deterministic "
                "research ordering only."
            ),
            (
                "Rank #1 is not a winner, BUY, "
                "increase-exposure, or allocation instruction."
            ),
            (
                "FUND20 does not recalculate FI score "
                "or create a composite investment score."
            ),
            (
                "No 8E, New Money, trade, order, portfolio "
                "write, or production authority exists."
            ),
        ],
    }
