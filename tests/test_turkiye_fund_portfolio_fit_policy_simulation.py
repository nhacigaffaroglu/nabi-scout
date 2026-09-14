import pytest

from services.turkiye_fund_portfolio_fit_assessment_policy import (
    draft_fund18_assessment_policy_v1,
    normalize_fund18_assessment_policy,
)
from services.turkiye_fund_portfolio_fit_policy_simulation import (
    Fund18PolicySimulationError,
    OUTPUT_SCHEMA,
    build_fund18_policy_simulation_artifact,
)


def evidence(code):
    return {
        "schema_version": "fund18_portfolio_fit_evidence_1",
        "fund_code": code,
        "dimensions": {
            "role_fit": {"state": "SUPPORTED"},
            "economic_overlap": {"state": "SUPPORTED"},
            "diversification_contribution": {
                "state": "SUPPORTED"
            },
            "concentration_risk": {"state": "SUPPORTED"},
        },
    }


def production():
    return {
        "schema_version":
            "fund18_portfolio_fit_research_artifact_1",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "candidates": [
            {
                "fund_code": "GKV",
                "role_fit": "UNKNOWN",
                "economic_overlap": "UNKNOWN",
                "diversification_contribution": "UNKNOWN",
                "concentration_risk": "UNKNOWN",
                "evidence": evidence("GKV"),
            },
            {
                "fund_code": "IAT",
                "role_fit": "UNKNOWN",
                "economic_overlap": "UNKNOWN",
                "diversification_contribution": "UNKNOWN",
                "concentration_risk": "UNKNOWN",
                "evidence": evidence("IAT"),
            },
        ],
    }


def inputs():
    return {
        "candidate_exposures": {
            "GKV": {
                "primary_exposure": "equity",
                "as_of": "2026-08-31T23:59:59Z",
                "confidence": "MEDIUM",
            },
            "IAT": {
                "primary_exposure": "sukuk",
                "as_of": "2026-07-31T23:59:59Z",
                "confidence": "MEDIUM",
            },
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
            "IAT": 0.0,
        },
        "desired_roles": [
            "core_growth",
            "diversification",
        ],
    }


def policy():
    return normalize_fund18_assessment_policy(
        draft_fund18_assessment_policy_v1()
    )


def test_simulation_does_not_modify_production_assessments():
    original = production()

    result = build_fund18_policy_simulation_artifact(
        production_fund18_artifact=original,
        assessment_inputs=inputs(),
        policy=policy(),
        generated_at="2026-09-14T12:00:00Z",
    )

    assert result["schema_version"] == OUTPUT_SCHEMA
    assert result["mode"] == "SIMULATION"
    assert (
        result["production_assessments_unchanged"]
        is True
    )
    assert result["candidate_count"] == 2

    assert original["candidates"][0]["role_fit"] == "UNKNOWN"
    assert (
        original["candidates"][0]["economic_overlap"]
        == "UNKNOWN"
    )


def test_gkv_simulation_expected_values():
    result = build_fund18_policy_simulation_artifact(
        production_fund18_artifact=production(),
        assessment_inputs=inputs(),
        policy=policy(),
    )

    gkv = result["simulated_assessments"][0]

    assert gkv["role_fit"]["assessment"] == "STRONG"
    assert gkv["economic_overlap"]["assessment"] == "HIGH"
    assert (
        gkv["diversification_contribution"]["assessment"]
        == "LOW"
    )
    assert gkv["concentration_risk"]["assessment"] == "LOW"


def test_iat_missing_portfolio_bucket_stays_unknown():
    result = build_fund18_policy_simulation_artifact(
        production_fund18_artifact=production(),
        assessment_inputs=inputs(),
        policy=policy(),
    )

    iat = result["simulated_assessments"][1]

    assert iat["role_fit"]["assessment"] == "STRONG"
    assert iat["economic_overlap"]["assessment"] == "UNKNOWN"
    assert (
        iat["economic_overlap"]["reason_code"]
        == "PORTFOLIO_BUCKET_UNMEASURED"
    )
    assert (
        iat["diversification_contribution"]["assessment"]
        == "UNKNOWN"
    )
    assert iat["concentration_risk"]["assessment"] == "LOW"


def test_simulation_firewall_zero_authority():
    result = build_fund18_policy_simulation_artifact(
        production_fund18_artifact=production(),
        assessment_inputs=inputs(),
        policy=policy(),
    )

    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["production_persist"] is False
    assert result["write_proof"] == {
        "production_writes": 0,
        "portfolio_writes": 0,
        "eight_e_calls": 0,
        "new_money_calls": 0,
        "trade_actions": 0,
        "orders": 0,
    }


def test_effective_policy_cannot_be_used_in_simulation():
    raw = draft_fund18_assessment_policy_v1()
    raw["human_approved"] = True
    raw["locked"] = True
    raw["production_effective"] = True

    effective = normalize_fund18_assessment_policy(raw)

    with pytest.raises(
        Fund18PolicySimulationError,
        match="simulation_requires_non_effective_policy",
    ):
        build_fund18_policy_simulation_artifact(
            production_fund18_artifact=production(),
            assessment_inputs=inputs(),
            policy=effective,
        )


def test_bad_production_schema_fails_closed():
    bad = production()
    bad["schema_version"] = "wrong"

    with pytest.raises(
        Fund18PolicySimulationError,
        match="unsupported_production_fund18_schema",
    ):
        build_fund18_policy_simulation_artifact(
            production_fund18_artifact=bad,
            assessment_inputs=inputs(),
            policy=policy(),
        )
