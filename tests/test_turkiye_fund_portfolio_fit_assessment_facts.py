import pytest

from services.turkiye_fund_portfolio_fit_assessment_facts import (
    PortfolioFitAssessmentFactsError,
    build_portfolio_fit_assessment_facts,
)


def evidence():
    return {
        "schema_version": "fund18_portfolio_fit_evidence_1",
        "dimensions": {
            "role_fit": {"state": "SUPPORTED"},
            "economic_overlap": {"state": "SUPPORTED"},
            "diversification_contribution": {"state": "SUPPORTED"},
            "concentration_risk": {"state": "SUPPORTED"},
        },
    }


def test_builds_structured_facts_without_text_parsing():
    result = build_portfolio_fit_assessment_facts(
        fund_code="gkv",
        evidence=evidence(),
        candidate_exposure={
            "primary_exposure": "equity",
            "as_of": "2026-08-31T23:59:59Z",
            "confidence": "MEDIUM",
        },
        portfolio_exposure={
            "completeness": "PARTIAL_EXPOSURE",
            "buckets": [
                {
                    "bucket_id": "equity",
                    "observable_weight_pct": 88.8471,
                },
                {
                    "bucket_id": "unknown",
                    "observable_weight_pct": 11.1529,
                },
            ],
        },
        current_weight_pct=0.0,
        desired_roles=["core_growth", "diversification"],
    )

    assert result.fund_code == "GKV"
    assert result.candidate_primary_exposure == "equity"
    assert result.portfolio_bucket_weights == {
        "equity": 88.8471
    }
    assert result.portfolio_unknown_pct == 11.1529
    assert result.current_candidate_weight_pct == 0.0
    assert result.desired_roles == (
        "core_growth",
        "diversification",
    )


def test_missing_bucket_is_not_invented_as_zero():
    result = build_portfolio_fit_assessment_facts(
        fund_code="IAT",
        evidence=evidence(),
        candidate_exposure={
            "primary_exposure": "sukuk",
        },
        portfolio_exposure={
            "completeness": "PARTIAL_EXPOSURE",
            "buckets": {
                "equity": 88.8471,
                "unknown": 11.1529,
            },
        },
        current_weight_pct=0.0,
        desired_roles=["diversification"],
    )

    assert "sukuk" not in result.portfolio_bucket_weights


def test_invalid_evidence_state_fails_closed():
    bad = evidence()
    bad["dimensions"]["role_fit"]["state"] = "READY"

    with pytest.raises(
        PortfolioFitAssessmentFactsError,
        match="evidence_state_invalid:role_fit",
    ):
        build_portfolio_fit_assessment_facts(
            fund_code="GKV",
            evidence=bad,
            candidate_exposure=None,
            portfolio_exposure=None,
            current_weight_pct=None,
            desired_roles=[],
        )


def test_weight_over_100_fails_closed():
    with pytest.raises(
        PortfolioFitAssessmentFactsError,
        match="current_candidate_weight_pct_out_of_range",
    ):
        build_portfolio_fit_assessment_facts(
            fund_code="GKV",
            evidence=evidence(),
            candidate_exposure=None,
            portfolio_exposure=None,
            current_weight_pct=101,
            desired_roles=[],
        )
