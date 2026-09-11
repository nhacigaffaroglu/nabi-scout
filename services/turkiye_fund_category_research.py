"""FUND15 category-aware research artifact core.

Pure research transformation:
FUND14B candidate artifact -> category-aware research artifact.

This module does not:
- change Participation methodology,
- change FI scoring methodology,
- change or invent the FUND14B promotion threshold,
- create a cross-category winner/composite score,
- call 8E or New Money,
- place trades/orders,
- write portfolio or production state,
- perform network access.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any, Mapping

INPUT_SCHEMA = "fund14b_candidate_artifact_4"
OUTPUT_SCHEMA = "fund15_category_research_artifact_1"

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")


class CategoryResearchContractError(ValueError):
    """Fail-closed FUND15 contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CategoryResearchContractError(f"{field}_must_be_object")
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise CategoryResearchContractError(f"{field}_must_be_list")
    return value


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _validated_code(value: Any) -> str:
    if not isinstance(value, str):
        raise CategoryResearchContractError("fund_code_must_be_string")
    code = value.strip()
    if code != value or code != code.upper() or not _CODE_RE.fullmatch(code):
        raise CategoryResearchContractError(f"fund_code_not_canonical:{value!r}")
    return code


def _category(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CategoryResearchContractError("category_required")
    return value.strip()


def _assert_upstream_firewall(artifact: Mapping[str, Any]) -> None:
    if artifact.get("research_only") is not True:
        raise CategoryResearchContractError("upstream_research_only_not_true")
    if artifact.get("execution_authority") is not False:
        raise CategoryResearchContractError("upstream_execution_authority_not_false")
    if artifact.get("production_persist") is not False:
        raise CategoryResearchContractError("upstream_production_persist_not_false")

    proof = _as_dict(artifact.get("write_proof"), field="write_proof")
    for key in (
        "production_writes",
        "trade_actions",
        "orders",
        "portfolio_writes",
        "eight_e_calls",
        "new_money_calls",
    ):
        value = proof.get(key, 0)
        if isinstance(value, bool) or value not in (0, 0.0, None):
            raise CategoryResearchContractError(f"upstream_{key}_nonzero")


def _assert_promotion_contract(artifact: Mapping[str, Any]) -> None:
    policy = _as_dict(artifact.get("threshold_policy"), field="threshold_policy")
    if policy.get("locked") is not True:
        raise CategoryResearchContractError("threshold_policy_not_locked")
    if _finite_number(policy.get("fi_min")) is None:
        raise CategoryResearchContractError("threshold_policy_fi_min_missing")

    gate = _as_dict(artifact.get("promotion_gate"), field="promotion_gate")
    if gate.get("open") is not True:
        raise CategoryResearchContractError("promotion_gate_not_open")
    if gate.get("execution_authority") is not False:
        raise CategoryResearchContractError("promotion_gate_execution_authority_not_false")
    if gate.get("meaning") != "research_candidate_promotion_only":
        raise CategoryResearchContractError("promotion_gate_meaning_invalid")
    if gate.get("reasons") not in ([], ()):  # closed-state reasons must be empty when open
        raise CategoryResearchContractError("promotion_gate_reasons_not_empty")


def _candidate_index(artifact: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    candidates = _as_list(artifact.get("candidates"), field="candidates")
    out: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        row = _as_dict(raw, field="candidate")
        code = _validated_code(row.get("fund_code"))
        if code in out:
            raise CategoryResearchContractError(f"duplicate_candidate:{code}")
        row["fund_code"] = code
        _category(row.get("category"))
        if _finite_number(row.get("fi_score")) is None:
            raise CategoryResearchContractError(f"candidate_fi_score_missing:{code}")
        out[code] = row
    return out


def _promotion_rows(
    artifact: Mapping[str, Any],
    candidates: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    raw_promotions = _as_list(artifact.get("promotion_eligible"), field="promotion_eligible")
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for raw in raw_promotions:
        promotion = _as_dict(raw, field="promotion")
        code = _validated_code(promotion.get("fund_code"))
        if code in seen:
            raise CategoryResearchContractError(f"duplicate_promotion:{code}")
        seen.add(code)
        candidate = candidates.get(code)
        if candidate is None:
            raise CategoryResearchContractError(f"promotion_candidate_missing:{code}")

        p_score = _finite_number(promotion.get("fi_score"))
        c_score = _finite_number(candidate.get("fi_score"))
        if p_score is None or c_score is None or p_score != c_score:
            raise CategoryResearchContractError(f"promotion_fi_score_mismatch:{code}")
        if promotion.get("candidate_rank") != candidate.get("candidate_rank"):
            raise CategoryResearchContractError(f"promotion_candidate_rank_mismatch:{code}")
        rows.append(dict(candidate))
    return rows


def _sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -float(row["fi_score"]),
        -float(row.get("data_completeness") or 0.0),
        -float(row.get("confidence") or 0.0),
        str(row["fund_code"]),
    )


def _research_view(row: Mapping[str, Any], *, category_rank: int) -> dict[str, Any]:
    return {
        "fund_code": row.get("fund_code"),
        "fund_name": row.get("fund_name"),
        "category": row.get("category"),
        "category_rank": category_rank,
        "candidate_rank": row.get("candidate_rank"),
        "fi_score": row.get("fi_score"),
        "fi_state": row.get("fi_state"),
        "return_1y": row.get("return_1y"),
        "max_drawdown": row.get("max_drawdown"),
        "data_completeness": row.get("data_completeness"),
        "confidence": row.get("confidence"),
        "fi_profile": row.get("fi_profile"),
        "peer_view": row.get("peer_view"),
        "founder": row.get("founder"),
    }


def build_category_research_artifact(
    candidate_artifact: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a category-aware, research-only artifact from FUND14B promotions."""
    artifact = _as_dict(candidate_artifact, field="candidate_artifact")
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise CategoryResearchContractError("unsupported_fund14b_schema")

    _assert_upstream_firewall(artifact)
    _assert_promotion_contract(artifact)

    candidates = _candidate_index(artifact)
    promoted = _promotion_rows(artifact, candidates)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in promoted:
        grouped.setdefault(_category(row.get("category")), []).append(row)

    categories: list[dict[str, Any]] = []
    for category in sorted(grouped):
        rows = sorted(grouped[category], key=_sort_key)
        categories.append(
            {
                "category": category,
                "candidate_count": len(rows),
                "ranking_basis": [
                    "fi_score_desc",
                    "data_completeness_desc",
                    "confidence_desc",
                    "fund_code_asc",
                ],
                "candidates": [
                    _research_view(row, category_rank=index)
                    for index, row in enumerate(rows, start=1)
                ],
            }
        )

    timestamp = generated_at
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source": {
            "fund14b_schema_version": artifact.get("schema_version"),
            "source": artifact.get("source"),
            "threshold_policy": artifact.get("threshold_policy"),
        },
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "cross_category_winner": None,
        "cross_category_composite_score": None,
        "methodology_ownership": {
            "participation": False,
            "fund_intelligence": False,
            "fund14b_threshold": False,
            "eight_e": False,
            "new_money": False,
            "portfolio_allocation": False,
        },
        "counts": {
            "promotion_eligible": len(promoted),
            "categories": len(categories),
        },
        "categories": categories,
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
        },
        "limitations": [
            "Category rank is a research ordering, not a buy/sell instruction.",
            "No cross-category winner or composite investment score is produced.",
            "FUND15 does not alter Participation, FI scoring, or FUND14B threshold policy.",
            "No 8E, New Money, trade, order, portfolio, or production authority exists.",
        ],
    }
