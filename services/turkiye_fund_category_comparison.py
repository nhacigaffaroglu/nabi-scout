"""FUND16 within-category peer comparison core.

Pure research transformation:
FUND15 category research artifact -> metric-by-metric category comparison.

No new composite score, no recommendation, no cross-category winner, no network,
no 8E/New Money, no portfolio or production writes, and no execution authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any, Mapping

INPUT_SCHEMA = "fund15_category_research_artifact_1"
OUTPUT_SCHEMA = "fund16_category_comparison_artifact_1"

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")


class CategoryComparisonContractError(ValueError):
    """Fail-closed FUND16 contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CategoryComparisonContractError(f"{field}_must_be_object")
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise CategoryComparisonContractError(f"{field}_must_be_list")
    return value


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _code(value: Any) -> str:
    if not isinstance(value, str):
        raise CategoryComparisonContractError("fund_code_must_be_string")
    if value != value.strip() or value != value.upper() or not _CODE_RE.fullmatch(value):
        raise CategoryComparisonContractError(f"fund_code_not_canonical:{value!r}")
    return value


def _assert_threshold_provenance(artifact: Mapping[str, Any]) -> None:
    source = _as_dict(artifact.get("source"), field="source")
    policy = _as_dict(source.get("threshold_policy"), field="source.threshold_policy")

    if policy.get("locked") is not True:
        raise CategoryComparisonContractError("threshold_policy_not_locked")
    if _finite(policy.get("fi_min")) != 60.0:
        raise CategoryComparisonContractError("threshold_policy_fi_min_not_60")
    if policy.get("source") != "human_decision":
        raise CategoryComparisonContractError("threshold_policy_source_not_human_decision")
    if policy.get("decision_id") != "FUND14B-FI60-2026-09-11":
        raise CategoryComparisonContractError("threshold_policy_decision_id_mismatch")


def _assert_firewall(artifact: Mapping[str, Any]) -> None:
    if artifact.get("research_only") is not True:
        raise CategoryComparisonContractError("upstream_research_only_not_true")
    if artifact.get("execution_authority") is not False:
        raise CategoryComparisonContractError("upstream_execution_authority_not_false")
    if artifact.get("production_persist") is not False:
        raise CategoryComparisonContractError("upstream_production_persist_not_false")
    if artifact.get("cross_category_winner") is not None:
        raise CategoryComparisonContractError("upstream_cross_category_winner_present")
    if artifact.get("cross_category_composite_score") is not None:
        raise CategoryComparisonContractError("upstream_cross_category_composite_present")

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
            raise CategoryComparisonContractError(f"upstream_{key}_nonzero")


def _rank(values: list[tuple[str, float]], *, descending: bool) -> dict[str, int]:
    ordered = sorted(values, key=lambda x: ((-x[1]) if descending else x[1], x[0]))
    return {code: idx for idx, (code, _) in enumerate(ordered, start=1)}


def _validate_group(raw: Any) -> tuple[str, list[dict[str, Any]]]:
    group = _as_dict(raw, field="category_group")
    category = group.get("category")
    if not isinstance(category, str) or not category.strip() or category != category.strip():
        raise CategoryComparisonContractError("category_invalid")

    rows = _as_list(group.get("candidates"), field=f"{category}.candidates")
    if group.get("candidate_count") != len(rows):
        raise CategoryComparisonContractError(f"candidate_count_mismatch:{category}")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for expected_rank, raw_row in enumerate(rows, start=1):
        row = _as_dict(raw_row, field="candidate")
        code = _code(row.get("fund_code"))
        if code in seen:
            raise CategoryComparisonContractError(f"duplicate_candidate:{code}")
        seen.add(code)
        if row.get("category") != category:
            raise CategoryComparisonContractError(f"category_mismatch:{code}")
        if row.get("category_rank") != expected_rank:
            raise CategoryComparisonContractError(f"category_rank_mismatch:{code}")
        if _finite(row.get("fi_score")) is None:
            raise CategoryComparisonContractError(f"fi_score_missing:{code}")
        normalized.append(row)
    return category, normalized


def _comparison_group(category: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    comparable = len(rows) >= 2

    return_values = [(r["fund_code"], _finite(r.get("return_1y"))) for r in rows]
    dd_values = [(r["fund_code"], _finite(r.get("max_drawdown"))) for r in rows]

    return_rank = _rank(
        [(code, value) for code, value in return_values if value is not None],
        descending=True,
    )
    # Higher max_drawdown value is more resilient: -8% ranks ahead of -11%.
    dd_rank = _rank(
        [(code, value) for code, value in dd_values if value is not None],
        descending=True,
    )

    candidates: list[dict[str, Any]] = []
    for row in rows:
        code = row["fund_code"]
        candidates.append(
            {
                "fund_code": code,
                "fund_name": row.get("fund_name"),
                "category": category,
                "fi_score": row.get("fi_score"),
                "fi_state": row.get("fi_state"),
                "fi_category_rank": row.get("category_rank"),
                "return_1y": row.get("return_1y"),
                "return_1y_rank": return_rank.get(code) if comparable else None,
                "max_drawdown": row.get("max_drawdown"),
                "drawdown_resilience_rank": dd_rank.get(code) if comparable else None,
                "data_completeness": row.get("data_completeness"),
                "confidence": row.get("confidence"),
                "fi_profile": row.get("fi_profile"),
                "peer_view": row.get("peer_view"),
                "founder": row.get("founder"),
            }
        )

    return {
        "category": category,
        "candidate_count": len(rows),
        "peer_comparison_available": comparable,
        "comparison_basis": [
            "fi_score_existing_methodology_only",
            "return_1y_desc_when_available",
            "max_drawdown_resilience_desc_when_available",
        ],
        "composite_score": None,
        "winner": None,
        "candidates": candidates,
        "limitations": (
            []
            if comparable
            else [
                "Only one promoted candidate exists in this category; "
                "no within-category peer conclusion is produced."
            ]
        ),
    }


def build_category_comparison_artifact(
    category_artifact: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact = _as_dict(category_artifact, field="category_artifact")
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise CategoryComparisonContractError("unsupported_fund15_schema")

    _assert_firewall(artifact)
    _assert_threshold_provenance(artifact)

    raw_groups = _as_list(artifact.get("categories"), field="categories")
    counts = _as_dict(artifact.get("counts"), field="counts")
    if counts.get("categories") != len(raw_groups):
        raise CategoryComparisonContractError("category_count_mismatch")

    groups: list[dict[str, Any]] = []
    total = 0
    seen_categories: set[str] = set()
    seen_codes: set[str] = set()

    for raw in raw_groups:
        category, rows = _validate_group(raw)
        if category in seen_categories:
            raise CategoryComparisonContractError(f"duplicate_category:{category}")
        seen_categories.add(category)

        for row in rows:
            code = row["fund_code"]
            if code in seen_codes:
                raise CategoryComparisonContractError(f"cross_category_duplicate:{code}")
            seen_codes.add(code)

        total += len(rows)
        groups.append(_comparison_group(category, rows))

    if counts.get("promotion_eligible") != total:
        raise CategoryComparisonContractError("promotion_count_mismatch")

    timestamp = generated_at
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source": {
            "fund15_schema_version": artifact.get("schema_version"),
            "source": artifact.get("source"),
        },
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "cross_category_winner": None,
        "cross_category_composite_score": None,
        "recommendation": None,
        "counts": {
            "promotion_eligible": total,
            "categories": len(groups),
            "peer_comparable_categories": sum(
                1 for group in groups if group["peer_comparison_available"]
            ),
        },
        "categories": groups,
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
        },
        "limitations": [
            "Metric ranks are descriptive research views, not buy/sell recommendations.",
            "No new composite score or winner is created inside or across categories.",
            "FUND16 does not alter Participation, FI scoring, or the human-locked FI60 promotion gate.",
            "No 8E, New Money, portfolio allocation, trade, order, or production authority exists.",
        ],
    }
