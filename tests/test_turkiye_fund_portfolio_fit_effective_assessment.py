from copy import deepcopy

import pytest

from services.turkiye_fund_portfolio_fit_assessment_policy import (
    draft_fund18_assessment_policy_v1,
)
from services.turkiye_fund_portfolio_fit_effective_assessment import (
    Fund18EffectiveAssessmentIntegrationError,
    apply_effective_portfolio_fit_assessment_policy,
)


def _evidence(code: str):
    return {
        "schema_version": "fund18_portfolio_fit_evidence_1",
        "fund_code": code,
        "dimensions": {
            "role_fit": {"state": "SUPPORTED"},
            "economic_overlap": {"state": "SUPPORTED"},
            "diversification_contribution": {"state": "SUPPORTED"},
            "concentration_risk": {"state": "SUPPORTED"},
        },
    }


def _artifact():
    return {
        "schema_version": "fund18_portfolio_fit_research_artifact_1",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "evidence_policy": {},
        "limitations": [],
        "candidates": [
            {
                "fund_code": "GKV",
                "role_fit": "UNKNOWN",
                "economic_overlap": "UNKNOWN",
                "diversification_contribution": "UNKNOWN",
                "concentration_risk": "UNKNOWN",
                "evidence": _evidence("GKV"),
            }
        ],
    }


def _inputs():
    return {
        "candidate_exposures": {
            "GKV": {
                "primary_exposure": "equity",
                "as_of": "2026-08-31T23:59:59Z",
                "confidence": "MEDIUM",
            }
        },
        "portfolio_exposure": {
            "completeness": "PARTIAL_EXPOSURE",
            "buckets": {
                "equity": 88.8471,
                "unknown": 11.1529,
            },
        },
        "portfolio_weights": {
            "GKV": 0.0,
        },
        "desired_roles": [
            "core_growth",
            "diversification",
        ],
    }


def _effective_policy():
    policy = draft_fund18_assessment_policy_v1()
    policy["human_approved"] = True
    policy["locked"] = True
    policy["production_effective"] = True
    return policy


def test_effective_policy_populates_descriptive_assessments_without_authority():
    source = _artifact()
    original = deepcopy(source)

    result = apply_effective_portfolio_fit_assessment_policy(
        source,
        assessment_inputs=_inputs(),
        assessment_policy=_effective_policy(),
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "STRONG"
    assert row["economic_overlap"] == "HIGH"
    assert row["diversification_contribution"] == "LOW"
    assert row["concentration_risk"] == "LOW"

    assert row["effective_assessment"]["mode"] == "EFFECTIVE"
    assert row["effective_assessment"]["production_effective"] is True

    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["production_persist"] is False

    assert result["assessment_policy"]["human_approved"] is True
    assert result["assessment_policy"]["locked"] is True
    assert result["assessment_policy"]["production_effective"] is True

    assert (
        result["evidence_policy"]["effective_assessment_policy_applied"]
        is True
    )

    # Integration must not mutate the upstream FUND18 artifact.
    assert source == original


def test_draft_policy_cannot_be_applied_as_effective_policy():
    with pytest.raises(
        Exception,
        match="effective_policy_requires_human_approval",
    ):
        apply_effective_portfolio_fit_assessment_policy(
            _artifact(),
            assessment_inputs=_inputs(),
            assessment_policy=draft_fund18_assessment_policy_v1(),
        )


def test_effective_integration_rejects_artifact_with_execution_authority():
    bad = _artifact()
    bad["execution_authority"] = True

    with pytest.raises(
        Fund18EffectiveAssessmentIntegrationError,
        match="fund18_execution_authority_not_false",
    ):
        apply_effective_portfolio_fit_assessment_policy(
            bad,
            assessment_inputs=_inputs(),
            assessment_policy=_effective_policy(),
        )
