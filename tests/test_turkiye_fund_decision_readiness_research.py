from copy import deepcopy

import pytest

from services.turkiye_fund_decision_readiness_research import (
    DecisionReadinessContractError,
    OUTPUT_SCHEMA,
    READINESS_NOT_READY,
    READINESS_READY,
    REASON_UNKNOWN_DESCRIPTIVE_DIMENSION,
    REASON_UPSTREAM_EVIDENCE_INVALID,
    REASON_UPSTREAM_EVIDENCE_MISSING,
    build_decision_readiness_artifact,
)


ZERO_WRITE_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "eight_e_calls": 0,
    "new_money_calls": 0,
}


def evidence():
    return {
        "schema_version": "fund18_portfolio_fit_evidence_1",
        "fund_code": "IAT",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "dimensions": {},
    }


def fund18():
    return {
        "schema_version":
            "fund18_portfolio_fit_research_artifact_1",
        "source": {
            "fund17_schema_version":
                "fund17_portfolio_fit_artifact_1",
            "source": {},
        },
        "generated_at": "2026-09-13T12:00:00Z",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "portfolio_context": {
            "schema_version": "fund17_portfolio_context_1",
        },
        "portfolio_fit_status":
            "DESCRIPTIVE_RESEARCH_COMPLETE",
        "portfolio_fit_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
        "counts": {
            "candidates": 1,
            "descriptive_assessments": 1,
        },
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
                "role_fit": "STRONG",
                "economic_overlap": "LOW",
                "diversification_contribution": "HIGH",
                "concentration_risk": "LOW",
                "rationale": ["Synthetic test fixture."],
                "evidence": evidence(),
                "portfolio_fit_composite_score": None,
                "portfolio_fit_rank": None,
                "recommendation": None,
            }
        ],
        "write_proof": dict(ZERO_WRITE_PROOF),
    }


def build(payload=None):
    return build_decision_readiness_artifact(
        payload or fund18(),
        generated_at="2026-09-13T13:00:00Z",
    )


def test_complete_evidence_is_ready():
    result = build()

    assert result["schema_version"] == OUTPUT_SCHEMA
    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["production_persist"] is False

    assert (
        result["decision_readiness_status"]
        == "DECISION_READINESS_RESEARCH_COMPLETE"
    )

    assert result["counts"] == {
        "candidates": 1,
        "ready": 1,
        "not_ready": 0,
    }

    row = result["candidates"][0]

    assert row["decision_readiness"] == READINESS_READY
    assert row["decision_readiness_reasons"] == []


def test_unknown_dimension_is_not_ready():
    payload = fund18()
    payload["candidates"][0]["role_fit"] = "UNKNOWN"

    result = build(payload)
    row = result["candidates"][0]

    assert row["decision_readiness"] == READINESS_NOT_READY
    assert (
        f"{REASON_UNKNOWN_DESCRIPTIVE_DIMENSION}:role_fit"
        in row["decision_readiness_reasons"]
    )


def test_missing_evidence_is_not_ready():
    payload = fund18()
    payload["candidates"][0].pop("evidence")

    result = build(payload)
    row = result["candidates"][0]

    assert row["decision_readiness"] == READINESS_NOT_READY
    assert (
        REASON_UPSTREAM_EVIDENCE_MISSING
        in row["decision_readiness_reasons"]
    )


@pytest.mark.parametrize(
    "bad_evidence",
    [
        [],
        {},
        {"schema_version": "wrong_schema"},
    ],
)
def test_invalid_evidence_is_not_ready(bad_evidence):
    payload = fund18()
    payload["candidates"][0]["evidence"] = bad_evidence

    result = build(payload)
    row = result["candidates"][0]

    assert row["decision_readiness"] == READINESS_NOT_READY
    assert (
        REASON_UPSTREAM_EVIDENCE_INVALID
        in row["decision_readiness_reasons"]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "wrong_schema"),
        ("research_only", False),
        ("execution_authority", True),
        ("production_persist", True),
        ("portfolio_fit_status", "WRONG"),
        ("portfolio_fit_winner", "IAT"),
        ("portfolio_fit_composite_score", 99.0),
        ("recommendation", "BUY"),
    ],
)
def test_fund18_firewall_fails_closed(field, value):
    payload = fund18()
    payload[field] = value

    with pytest.raises(DecisionReadinessContractError):
        build(payload)


def test_nonzero_write_proof_fails_closed():
    payload = fund18()
    payload["write_proof"]["eight_e_calls"] = 1

    with pytest.raises(
        DecisionReadinessContractError,
        match="upstream_write_proof_not_zero",
    ):
        build(payload)


def test_duplicate_candidate_fails_closed():
    payload = fund18()
    payload["candidates"].append(
        deepcopy(payload["candidates"][0])
    )

    with pytest.raises(
        DecisionReadinessContractError,
        match="duplicate_candidate:IAT",
    ):
        build(payload)


def test_decision_firewall_remains_zero_authority():
    result = build()
    row = result["candidates"][0]

    assert result["portfolio_fit_winner"] is None
    assert result["portfolio_fit_composite_score"] is None
    assert result["recommendation"] is None

    assert row["portfolio_fit_composite_score"] is None
    assert row["portfolio_fit_rank"] is None
    assert row["recommendation"] is None

    assert result["write_proof"] == ZERO_WRITE_PROOF


def test_ready_does_not_create_decision_or_execution_fields():
    result = build()
    row = result["candidates"][0]

    forbidden = {
        "allocation",
        "trade",
        "order",
        "eight_e_action",
        "new_money_action",
        "buy",
        "sell",
    }

    assert forbidden.isdisjoint(result)
    assert forbidden.isdisjoint(row)
