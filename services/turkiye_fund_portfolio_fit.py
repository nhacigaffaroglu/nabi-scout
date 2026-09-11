"""FUND17 portfolio-fit research gate.

Pure research transformation:
FUND16 category comparison artifact + explicit portfolio context
-> descriptive portfolio-fit research artifact.

No composite score, no winner, no recommendation, no 8E/New Money execution,
no portfolio writes, no trades/orders, and no production persistence.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any, Mapping

INPUT_SCHEMA = "fund16_category_comparison_artifact_1"
PORTFOLIO_CONTEXT_SCHEMA = "fund17_portfolio_context_1"
OUTPUT_SCHEMA = "fund17_portfolio_fit_artifact_1"

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")


class PortfolioFitContractError(ValueError):
    """Fail-closed FUND17 contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioFitContractError(f"{field}_must_be_object")
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise PortfolioFitContractError(f"{field}_must_be_list")
    return value


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _code(value: Any) -> str:
    if not isinstance(value, str):
        raise PortfolioFitContractError("fund_code_must_be_string")
    if value != value.strip() or value != value.upper() or not _CODE_RE.fullmatch(value):
        raise PortfolioFitContractError(f"fund_code_not_canonical:{value!r}")
    return value


def _assert_threshold_provenance(artifact: Mapping[str, Any]) -> None:
    source = _as_dict(artifact.get("source"), field="source")
    fund15_source = _as_dict(source.get("source"), field="source.source")
    policy = _as_dict(
        fund15_source.get("threshold_policy"),
        field="source.source.threshold_policy",
    )

    if policy.get("locked") is not True:
        raise PortfolioFitContractError("threshold_policy_not_locked")
    if _finite(policy.get("fi_min")) != 60.0:
        raise PortfolioFitContractError("threshold_policy_fi_min_not_60")
    if policy.get("source") != "human_decision":
        raise PortfolioFitContractError("threshold_policy_source_not_human_decision")
    if policy.get("decision_id") != "FUND14B-FI60-2026-09-11":
        raise PortfolioFitContractError("threshold_policy_decision_id_mismatch")


def _assert_upstream_firewall(artifact: Mapping[str, Any]) -> None:
    if artifact.get("research_only") is not True:
        raise PortfolioFitContractError("upstream_research_only_not_true")
    if artifact.get("execution_authority") is not False:
        raise PortfolioFitContractError("upstream_execution_authority_not_false")
    if artifact.get("production_persist") is not False:
        raise PortfolioFitContractError("upstream_production_persist_not_false")
    if artifact.get("cross_category_winner") is not None:
        raise PortfolioFitContractError("upstream_cross_category_winner_present")
    if artifact.get("cross_category_composite_score") is not None:
        raise PortfolioFitContractError("upstream_cross_category_composite_present")
    if artifact.get("recommendation") is not None:
        raise PortfolioFitContractError("upstream_recommendation_present")

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
            raise PortfolioFitContractError(f"upstream_{key}_nonzero")


def _collect_candidates(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = _as_list(artifact.get("categories"), field="categories")
    counts = _as_dict(artifact.get("counts"), field="counts")
    if counts.get("categories") != len(groups):
        raise PortfolioFitContractError("category_count_mismatch")

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    for raw_group in groups:
        group = _as_dict(raw_group, field="category_group")
        category = group.get("category")
        if not isinstance(category, str) or not category.strip():
            raise PortfolioFitContractError("category_invalid")

        candidates = _as_list(group.get("candidates"), field=f"{category}.candidates")
        if group.get("candidate_count") != len(candidates):
            raise PortfolioFitContractError(f"candidate_count_mismatch:{category}")

        for raw_row in candidates:
            row = _as_dict(raw_row, field="candidate")
            code = _code(row.get("fund_code"))
            if code in seen:
                raise PortfolioFitContractError(f"duplicate_candidate:{code}")
            seen.add(code)
            if row.get("category") != category:
                raise PortfolioFitContractError(f"category_mismatch:{code}")
            rows.append(row)

    if counts.get("promotion_eligible") != len(rows):
        raise PortfolioFitContractError("promotion_count_mismatch")
    return rows


def _normalize_context(context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if context is None:
        return None

    ctx = _as_dict(context, field="portfolio_context")
    if ctx.get("schema_version") != PORTFOLIO_CONTEXT_SCHEMA:
        raise PortfolioFitContractError("unsupported_portfolio_context_schema")
    if ctx.get("human_supplied") is not True:
        raise PortfolioFitContractError("portfolio_context_not_human_supplied")
    if ctx.get("research_only") is not True:
        raise PortfolioFitContractError("portfolio_context_research_only_not_true")
    if ctx.get("execution_authority") is not False:
        raise PortfolioFitContractError("portfolio_context_execution_authority_not_false")

    roles = _as_list(ctx.get("desired_roles"), field="portfolio_context.desired_roles")
    exposures = _as_list(
        ctx.get("existing_exposures"),
        field="portfolio_context.existing_exposures",
    )
    constraints = _as_list(
        ctx.get("constraints"),
        field="portfolio_context.constraints",
    )

    for field, values in (
        ("desired_roles", roles),
        ("existing_exposures", exposures),
        ("constraints", constraints),
    ):
        if any(not isinstance(x, str) or not x.strip() for x in values):
            raise PortfolioFitContractError(f"portfolio_context_{field}_invalid")

    return {
        "schema_version": PORTFOLIO_CONTEXT_SCHEMA,
        "human_supplied": True,
        "research_only": True,
        "execution_authority": False,
        "desired_roles": roles,
        "existing_exposures": exposures,
        "constraints": constraints,
        "notes": ctx.get("notes"),
    }


def build_portfolio_fit_artifact(
    comparison_artifact: Mapping[str, Any],
    *,
    portfolio_context: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact = _as_dict(comparison_artifact, field="comparison_artifact")
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise PortfolioFitContractError("unsupported_fund16_schema")

    _assert_upstream_firewall(artifact)
    _assert_threshold_provenance(artifact)
    rows = _collect_candidates(artifact)
    context = _normalize_context(portfolio_context)

    timestamp = generated_at
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    context_available = context is not None
    status = "READY_FOR_PORTFOLIO_FIT_RESEARCH" if context_available else "PORTFOLIO_CONTEXT_REQUIRED"

    candidates = []
    for row in rows:
        candidates.append(
            {
                "fund_code": row.get("fund_code"),
                "fund_name": row.get("fund_name"),
                "category": row.get("category"),
                "fi_score": row.get("fi_score"),
                "fi_state": row.get("fi_state"),
                "return_1y": row.get("return_1y"),
                "return_1y_rank": row.get("return_1y_rank"),
                "max_drawdown": row.get("max_drawdown"),
                "drawdown_resilience_rank": row.get("drawdown_resilience_rank"),
                "portfolio_fit_status": status,
                "role_fit": None,
                "economic_overlap": None,
                "diversification_contribution": None,
                "concentration_risk": None,
                "portfolio_fit_composite_score": None,
                "portfolio_fit_rank": None,
                "recommendation": None,
            }
        )

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source": {
            "fund16_schema_version": artifact.get("schema_version"),
            "source": artifact.get("source"),
        },
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "portfolio_context_available": context_available,
        "portfolio_context": context,
        "portfolio_fit_status": status,
        "portfolio_fit_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
        "counts": {
            "candidates": len(candidates),
            "context_ready": len(candidates) if context_available else 0,
            "context_required": 0 if context_available else len(candidates),
        },
        "candidates": candidates,
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
        },
        "limitations": [
            "FUND17 is a research gate, not a buy/sell or allocation recommendation.",
            "No portfolio-fit composite score, ranking, or winner is created.",
            "Without explicit human-supplied portfolio context, fit dimensions remain unevaluated.",
            "FUND17 does not alter Participation, FI scoring, FI60, or FUND16 peer ranks.",
            "No 8E, New Money, portfolio write, trade, order, or production authority exists.",
        ],
    }
