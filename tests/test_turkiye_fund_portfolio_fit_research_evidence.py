import copy

import pytest

from services.turkiye_fund_portfolio_fit_research import (
    PortfolioFitResearchContractError,
    build_evidence_backed_portfolio_fit_research_artifact,
)


ZERO_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "eight_e_calls": 0,
    "new_money_calls": 0,
}


def fund17():
    return {
        "schema_version": "fund17_portfolio_fit_artifact_1",
        "source": {
            "fund16_schema_version":
                "fund16_category_comparison_artifact_1",
            "source": {},
        },
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "portfolio_context_available": True,
        "portfolio_context": {
            "schema_version": "fund17_portfolio_context_1",
            "human_supplied": True,
            "research_only": True,
            "execution_authority": False,
            "desired_roles": ["diversification"],
            "existing_exposures": ["equity"],
            "constraints": ["research only"],
        },
        "portfolio_fit_status":
            "READY_FOR_PORTFOLIO_FIT_RESEARCH",
        "portfolio_fit_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
        "candidates": [
            {
                "fund_code": "IAT",
                "fund_name": "IAT Fund",
                "category": "sukuk",
                "fi_score": 60.49,
                "fi_state": "NEUTRAL",
                "return_1y": 40.76,
                "return_1y_rank": None,
                "max_drawdown": -0.22,
                "drawdown_resilience_rank": None,
            }
        ],
        "write_proof": dict(ZERO_PROOF),
    }


def assessments():
    return {
        "IAT": {
            "fund_code": "IAT",
            "role_fit": "STRONG",
            "economic_overlap": "LOW",
            "diversification_contribution": "HIGH",
            "concentration_risk": "LOW",
            "rationale": [
                "Synthetic assessment fixture only."
            ],
        }
    }


def source():
    return {
        "source_type": "FUND17_PORTFOLIO_CONTEXT",
        "source_id": "synthetic-context-1",
        "observed_fact": "Synthetic evidence only.",
        "as_of": "2026-09-11T18:00:00Z",
    }


def dimension(state="SUPPORTED"):
    return {
        "state": state,
        "sources": [source()] if state == "SUPPORTED" else [],
        "rationale": [
            f"Synthetic {state.lower()} evidence fixture."
        ],
    }


def evidence():
    return {
        "IAT": {
            "schema_version":
                "fund18_portfolio_fit_evidence_1",
            "fund_code": "IAT",
            "research_only": True,
            "execution_authority": False,
            "production_persist": False,
            "dimensions": {
                "role_fit": dimension(),
                "economic_overlap": dimension(),
                "diversification_contribution": dimension(),
                "concentration_risk": dimension(),
            },
        }
    }


def test_supported_evidence_preserves_descriptive_values():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=evidence(),
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "STRONG"
    assert row["economic_overlap"] == "LOW"
    assert row["diversification_contribution"] == "HIGH"
    assert row["concentration_risk"] == "LOW"


@pytest.mark.parametrize(
    "state",
    ["INSUFFICIENT", "CONTRADICTORY"],
)
def test_non_supported_evidence_forces_unknown(state):
    data = evidence()
    data["IAT"]["dimensions"]["role_fit"] = dimension(state)

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=data,
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert row["economic_overlap"] == "LOW"


def test_output_carries_normalized_evidence_and_policy():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=evidence(),
    )

    row = result["candidates"][0]

    assert (
        row["evidence"]["schema_version"]
        == "fund18_portfolio_fit_evidence_1"
    )
    assert (
        result["counts"]["evidence_backed_assessments"]
        == 1
    )
    assert (
        result["evidence_policy"][
            "supported_required_for_non_unknown"
        ]
        is True
    )


def test_evidence_candidate_set_must_match_exactly():
    with pytest.raises(
        PortfolioFitResearchContractError,
        match="evidence_candidate_set_mismatch",
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17(),
            assessments=assessments(),
            evidence={},
        )


def test_firewall_remains_zero():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=evidence(),
    )

    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["production_persist"] is False
    assert result["write_proof"] == ZERO_PROOF
    assert result["portfolio_fit_winner"] is None
    assert result["portfolio_fit_composite_score"] is None
    assert result["recommendation"] is None


def test_does_not_mutate_inputs():
    upstream = fund17()
    assessment_data = assessments()
    evidence_data = evidence()

    upstream_before = copy.deepcopy(upstream)
    assessments_before = copy.deepcopy(assessment_data)
    evidence_before = copy.deepcopy(evidence_data)

    build_evidence_backed_portfolio_fit_research_artifact(
        upstream,
        assessments=assessment_data,
        evidence=evidence_data,
    )

    assert upstream == upstream_before
    assert assessment_data == assessments_before
    assert evidence_data == evidence_before
