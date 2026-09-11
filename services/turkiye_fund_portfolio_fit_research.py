"""FUND18 descriptive portfolio-fit research contract.

FUND17 portfolio-fit gate artifact
-> FUND18 descriptive portfolio-fit research artifact.

FUND18 may populate four descriptive research dimensions only:
- role_fit
- economic_overlap
- diversification_contribution
- concentration_risk

It must not create:
- composite score
- cross-candidate rank
- winner
- buy/sell recommendation
- allocation
- trade/order
- 8E/New Money action
- production persistence
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


INPUT_SCHEMA = "fund17_portfolio_fit_artifact_1"
OUTPUT_SCHEMA = "fund18_portfolio_fit_research_artifact_1"

ROLE_FIT_VALUES = {"STRONG", "PARTIAL", "WEAK", "UNKNOWN"}
OVERLAP_VALUES = {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}
DIVERSIFICATION_VALUES = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
CONCENTRATION_VALUES = {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}


class PortfolioFitResearchContractError(ValueError):
    """Fail-closed FUND18 contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioFitResearchContractError(f"{field}_must_be_object")
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise PortfolioFitResearchContractError(f"{field}_must_be_list")
    return value


def _assert_zero_write_proof(artifact: Mapping[str, Any]) -> None:
    proof = _as_dict(artifact.get("write_proof"), field="write_proof")
    expected = {
        "production_writes": 0,
        "trade_actions": 0,
        "orders": 0,
        "portfolio_writes": 0,
        "eight_e_calls": 0,
        "new_money_calls": 0,
    }
    if proof != expected:
        raise PortfolioFitResearchContractError("upstream_write_proof_not_zero")


def _assert_fund17_firewall(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise PortfolioFitResearchContractError("unsupported_fund17_schema")

    if artifact.get("research_only") is not True:
        raise PortfolioFitResearchContractError("upstream_research_only_not_true")

    if artifact.get("execution_authority") is not False:
        raise PortfolioFitResearchContractError(
            "upstream_execution_authority_not_false"
        )

    if artifact.get("production_persist") is not False:
        raise PortfolioFitResearchContractError(
            "upstream_production_persist_not_false"
        )

    if artifact.get("portfolio_context_available") is not True:
        raise PortfolioFitResearchContractError(
            "portfolio_context_not_available"
        )

    if artifact.get("portfolio_fit_status") != "READY_FOR_PORTFOLIO_FIT_RESEARCH":
        raise PortfolioFitResearchContractError(
            "portfolio_fit_not_ready_for_research"
        )

    if artifact.get("portfolio_fit_winner") is not None:
        raise PortfolioFitResearchContractError("upstream_winner_present")

    if artifact.get("portfolio_fit_composite_score") is not None:
        raise PortfolioFitResearchContractError(
            "upstream_composite_score_present"
        )

    if artifact.get("recommendation") is not None:
        raise PortfolioFitResearchContractError(
            "upstream_recommendation_present"
        )

    _assert_zero_write_proof(artifact)


def _normalize_assessment(
    raw: Mapping[str, Any],
    *,
    expected_code: str,
) -> dict[str, Any]:
    row = _as_dict(raw, field=f"assessment:{expected_code}")

    if row.get("fund_code") != expected_code:
        raise PortfolioFitResearchContractError(
            f"assessment_fund_code_mismatch:{expected_code}"
        )

    role_fit = row.get("role_fit")
    overlap = row.get("economic_overlap")
    diversification = row.get("diversification_contribution")
    concentration = row.get("concentration_risk")

    if role_fit not in ROLE_FIT_VALUES:
        raise PortfolioFitResearchContractError(
            f"invalid_role_fit:{expected_code}"
        )

    if overlap not in OVERLAP_VALUES:
        raise PortfolioFitResearchContractError(
            f"invalid_economic_overlap:{expected_code}"
        )

    if diversification not in DIVERSIFICATION_VALUES:
        raise PortfolioFitResearchContractError(
            f"invalid_diversification_contribution:{expected_code}"
        )

    if concentration not in CONCENTRATION_VALUES:
        raise PortfolioFitResearchContractError(
            f"invalid_concentration_risk:{expected_code}"
        )

    rationale = row.get("rationale")
    if not isinstance(rationale, list) or not rationale:
        raise PortfolioFitResearchContractError(
            f"assessment_rationale_required:{expected_code}"
        )

    if any(not isinstance(x, str) or not x.strip() for x in rationale):
        raise PortfolioFitResearchContractError(
            f"assessment_rationale_invalid:{expected_code}"
        )

    return {
        "fund_code": expected_code,
        "role_fit": role_fit,
        "economic_overlap": overlap,
        "diversification_contribution": diversification,
        "concentration_risk": concentration,
        "rationale": list(rationale),
    }


def build_portfolio_fit_research_artifact(
    fund17_artifact: Mapping[str, Any],
    *,
    assessments: Mapping[str, Mapping[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact = _as_dict(fund17_artifact, field="fund17_artifact")
    _assert_fund17_firewall(artifact)

    if not isinstance(assessments, Mapping):
        raise PortfolioFitResearchContractError(
            "assessments_must_be_object"
        )

    candidates = _as_list(artifact.get("candidates"), field="candidates")
    upstream_codes = []

    for raw in candidates:
        row = _as_dict(raw, field="candidate")
        code = row.get("fund_code")

        if not isinstance(code, str) or not code:
            raise PortfolioFitResearchContractError(
                "candidate_fund_code_invalid"
            )

        if code in upstream_codes:
            raise PortfolioFitResearchContractError(
                f"duplicate_candidate:{code}"
            )

        upstream_codes.append(code)

    if set(assessments.keys()) != set(upstream_codes):
        raise PortfolioFitResearchContractError(
            "assessment_candidate_set_mismatch"
        )

    output_candidates = []

    for raw in candidates:
        row = _as_dict(raw, field="candidate")
        code = row["fund_code"]

        assessment = _normalize_assessment(
            assessments[code],
            expected_code=code,
        )

        output_candidates.append(
            {
                "fund_code": code,
                "fund_name": row.get("fund_name"),
                "category": row.get("category"),
                "fi_score": row.get("fi_score"),
                "fi_state": row.get("fi_state"),
                "return_1y": row.get("return_1y"),
                "return_1y_rank": row.get("return_1y_rank"),
                "max_drawdown": row.get("max_drawdown"),
                "drawdown_resilience_rank": row.get(
                    "drawdown_resilience_rank"
                ),
                "role_fit": assessment["role_fit"],
                "economic_overlap": assessment["economic_overlap"],
                "diversification_contribution": assessment[
                    "diversification_contribution"
                ],
                "concentration_risk": assessment["concentration_risk"],
                "rationale": assessment["rationale"],
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

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source": {
            "fund17_schema_version": artifact.get("schema_version"),
            "source": artifact.get("source"),
        },
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "portfolio_context": artifact.get("portfolio_context"),
        "portfolio_fit_status": "DESCRIPTIVE_RESEARCH_COMPLETE",
        "portfolio_fit_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
        "counts": {
            "candidates": len(output_candidates),
            "descriptive_assessments": len(output_candidates),
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
            "FUND18 produces descriptive portfolio-fit research only.",
            "Assessments require explicit evidence-backed inputs.",
            "No composite score, ranking, winner, recommendation, allocation, or execution is created.",
            "Participation, FI, FI60, and FUND16 peer ranks remain unchanged.",
        ],
    }


def build_evidence_backed_portfolio_fit_research_artifact(
    fund17_artifact: Mapping[str, Any],
    *,
    assessments: Mapping[str, Mapping[str, Any]],
    evidence: Mapping[str, Mapping[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build FUND18 research with explicit per-dimension evidence.

    Fail-closed rule:
    a descriptive dimension may keep its assessment only when the
    corresponding evidence state is SUPPORTED.

    INSUFFICIENT or CONTRADICTORY evidence forces that dimension to UNKNOWN.
    """
    from services.turkiye_fund_portfolio_fit_evidence import (
        normalize_candidate_evidence,
    )

    artifact = _as_dict(
        fund17_artifact,
        field="fund17_artifact",
    )
    _assert_fund17_firewall(artifact)

    if not isinstance(evidence, Mapping):
        raise PortfolioFitResearchContractError(
            "evidence_must_be_object"
        )

    candidates = _as_list(
        artifact.get("candidates"),
        field="candidates",
    )

    candidate_codes: list[str] = []

    for raw in candidates:
        row = _as_dict(raw, field="candidate")
        code = row.get("fund_code")

        if not isinstance(code, str) or not code:
            raise PortfolioFitResearchContractError(
                "candidate_fund_code_invalid"
            )

        candidate_codes.append(code)

    if set(evidence.keys()) != set(candidate_codes):
        raise PortfolioFitResearchContractError(
            "evidence_candidate_set_mismatch"
        )

    if set(assessments.keys()) != set(candidate_codes):
        raise PortfolioFitResearchContractError(
            "assessment_candidate_set_mismatch"
        )

    normalized_evidence: dict[str, dict[str, Any]] = {}
    safe_assessments: dict[str, dict[str, Any]] = {}

    dimensions = (
        "role_fit",
        "economic_overlap",
        "diversification_contribution",
        "concentration_risk",
    )

    for code in candidate_codes:
        normalized = normalize_candidate_evidence(
            evidence[code],
            expected_code=code,
        )
        normalized_evidence[code] = normalized

        assessment = _normalize_assessment(
            assessments[code],
            expected_code=code,
        )

        safe = dict(assessment)

        evidence_rationale: list[str] = []

        for dimension in dimensions:
            dimension_evidence = normalized["dimensions"][dimension]

            if dimension_evidence["state"] != "SUPPORTED":
                safe[dimension] = "UNKNOWN"

            evidence_rationale.extend(
                dimension_evidence["rationale"]
            )

        safe["rationale"] = list(
            dict.fromkeys(
                list(assessment["rationale"])
                + evidence_rationale
            )
        )

        safe_assessments[code] = safe

    result = build_portfolio_fit_research_artifact(
        artifact,
        assessments=safe_assessments,
        generated_at=generated_at,
    )

    for row in result["candidates"]:
        code = row["fund_code"]
        row["evidence"] = normalized_evidence[code]

    result["counts"]["evidence_backed_assessments"] = len(
        result["candidates"]
    )

    result["evidence_policy"] = {
        "schema_version": "fund18_portfolio_fit_evidence_policy_1",
        "supported_required_for_non_unknown": True,
        "insufficient_maps_to_unknown": True,
        "contradictory_maps_to_unknown": True,
    }

    result["limitations"].append(
        "Any FUND18 dimension without SUPPORTED evidence is forced to UNKNOWN."
    )

    return result
