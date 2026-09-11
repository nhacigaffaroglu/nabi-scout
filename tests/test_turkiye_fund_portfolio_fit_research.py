import copy

import pytest

from services.turkiye_fund_portfolio_fit_research import (
    PortfolioFitResearchContractError,
    build_portfolio_fit_research_artifact,
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
            "fund16_schema_version": "fund16_category_comparison_artifact_1",
            "source": {},
        },
        "generated_at": "2026-09-11T18:00:00Z",
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
            "notes": None,
        },
        "portfolio_fit_status": "READY_FOR_PORTFOLIO_FIT_RESEARCH",
        "portfolio_fit_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
        "counts": {
            "candidates": 2,
            "context_ready": 2,
            "context_required": 0,
        },
        "candidates": [
            {
                "fund_code": "GKV",
                "fund_name": "GKV Fund",
                "category": "equity",
                "fi_score": 82.33,
                "fi_state": "ATTRACTIVE",
                "return_1y": 57.75,
                "return_1y_rank": 1,
                "max_drawdown": -8.66,
                "drawdown_resilience_rank": 1,
                "portfolio_fit_status": "READY_FOR_PORTFOLIO_FIT_RESEARCH",
                "role_fit": None,
                "economic_overlap": None,
                "diversification_contribution": None,
                "concentration_risk": None,
                "portfolio_fit_composite_score": None,
                "portfolio_fit_rank": None,
                "recommendation": None,
            },
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
                "portfolio_fit_status": "READY_FOR_PORTFOLIO_FIT_RESEARCH",
                "role_fit": None,
                "economic_overlap": None,
                "diversification_contribution": None,
                "concentration_risk": None,
                "portfolio_fit_composite_score": None,
                "portfolio_fit_rank": None,
                "recommendation": None,
            },
        ],
        "write_proof": dict(ZERO_PROOF),
    }


def assessments():
    return {
        "GKV": {
            "fund_code": "GKV",
            "role_fit": "PARTIAL",
            "economic_overlap": "HIGH",
            "diversification_contribution": "LOW",
            "concentration_risk": "MEDIUM",
            "rationale": [
                "Existing portfolio context already includes equity exposure."
            ],
        },
        "IAT": {
            "fund_code": "IAT",
            "role_fit": "STRONG",
            "economic_overlap": "LOW",
            "diversification_contribution": "HIGH",
            "concentration_risk": "LOW",
            "rationale": [
                "Sukuk exposure is distinct from the supplied equity exposure."
            ],
        },
    }


def test_builds_descriptive_research_artifact():
    result = build_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        generated_at="2026-09-11T19:30:00Z",
    )

    assert result["schema_version"] == "fund18_portfolio_fit_research_artifact_1"
    assert result["portfolio_fit_status"] == "DESCRIPTIVE_RESEARCH_COMPLETE"
    assert result["counts"]["candidates"] == 2
    assert result["counts"]["descriptive_assessments"] == 2


def test_preserves_research_only_firewall():
    result = build_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
    )

    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["production_persist"] is False
    assert result["write_proof"] == ZERO_PROOF


def test_no_composite_rank_winner_or_recommendation():
    result = build_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
    )

    assert result["portfolio_fit_winner"] is None
    assert result["portfolio_fit_composite_score"] is None
    assert result["recommendation"] is None

    for row in result["candidates"]:
        assert row["portfolio_fit_composite_score"] is None
        assert row["portfolio_fit_rank"] is None
        assert row["recommendation"] is None


def test_requires_context_ready_fund17():
    source = fund17()
    source["portfolio_context_available"] = False

    with pytest.raises(
        PortfolioFitResearchContractError,
        match="portfolio_context_not_available",
    ):
        build_portfolio_fit_research_artifact(
            source,
            assessments=assessments(),
        )


def test_requires_ready_status():
    source = fund17()
    source["portfolio_fit_status"] = "PORTFOLIO_CONTEXT_REQUIRED"

    with pytest.raises(
        PortfolioFitResearchContractError,
        match="portfolio_fit_not_ready_for_research",
    ):
        build_portfolio_fit_research_artifact(
            source,
            assessments=assessments(),
        )


def test_rejects_nonzero_upstream_write_proof():
    source = fund17()
    source["write_proof"]["orders"] = 1

    with pytest.raises(
        PortfolioFitResearchContractError,
        match="upstream_write_proof_not_zero",
    ):
        build_portfolio_fit_research_artifact(
            source,
            assessments=assessments(),
        )


def test_assessment_set_must_match_candidates_exactly():
    data = assessments()
    data.pop("IAT")

    with pytest.raises(
        PortfolioFitResearchContractError,
        match="assessment_candidate_set_mismatch",
    ):
        build_portfolio_fit_research_artifact(
            fund17(),
            assessments=data,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("role_fit", "BUY", "invalid_role_fit"),
        ("economic_overlap", "NONE", "invalid_economic_overlap"),
        (
            "diversification_contribution",
            "VERY_HIGH",
            "invalid_diversification_contribution",
        ),
        ("concentration_risk", "SAFE", "invalid_concentration_risk"),
    ],
)
def test_assessment_enums_fail_closed(field, value, error):
    data = assessments()
    data["GKV"][field] = value

    with pytest.raises(
        PortfolioFitResearchContractError,
        match=error,
    ):
        build_portfolio_fit_research_artifact(
            fund17(),
            assessments=data,
        )


def test_rationale_is_required():
    data = assessments()
    data["GKV"]["rationale"] = []

    with pytest.raises(
        PortfolioFitResearchContractError,
        match="assessment_rationale_required",
    ):
        build_portfolio_fit_research_artifact(
            fund17(),
            assessments=data,
        )


def test_does_not_mutate_inputs():
    source = fund17()
    data = assessments()
    source_before = copy.deepcopy(source)
    data_before = copy.deepcopy(data)

    build_portfolio_fit_research_artifact(
        source,
        assessments=data,
    )

    assert source == source_before
    assert data == data_before
