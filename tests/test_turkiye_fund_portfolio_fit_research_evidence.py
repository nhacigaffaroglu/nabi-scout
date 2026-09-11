import copy

import pytest

from services.turkiye_fund_portfolio_fit_evidence import (
    PortfolioFitEvidenceContractError,
)

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


def test_evidence_backed_builder_rejects_future_evidence():
    fund17_data = fund17()
    assessment_data = assessments()
    evidence_data = evidence()

    evidence_data["IAT"]["dimensions"]["role_fit"]["sources"][0]["as_of"] = (
        "2026-09-11T18:00:01Z"
    )

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="evidence_as_of_in_future",
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17_data,
            assessments=assessment_data,
            evidence=evidence_data,
            generated_at="2026-09-11T18:00:00Z",
        )


def freshness_policy(max_age_days=1):
    return {
        "schema_version":
            "fund18_portfolio_fit_freshness_policy_1",
        "human_approved": True,
        "policy_id": "FUND18-FRESHNESS-INTEGRATION-1",
        "source_max_age_days": {
            "FUND17_PORTFOLIO_CONTEXT": max_age_days,
        },
    }


def test_freshness_policy_rejects_stale_evidence():
    data = evidence()

    for item in data["IAT"]["dimensions"].values():
        item["sources"][0]["as_of"] = (
            "2026-09-09T18:00:00Z"
        )

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match=(
            "evidence_stale:IAT:"
            "concentration_risk:"
            "FUND17_PORTFOLIO_CONTEXT"
        ),
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17(),
            assessments=assessments(),
            evidence=data,
            generated_at="2026-09-11T18:00:00Z",
            freshness_policy=freshness_policy(1),
        )


def test_freshness_policy_accepts_evidence_at_exact_boundary():
    data = evidence()

    for item in data["IAT"]["dimensions"].values():
        item["sources"][0]["as_of"] = (
            "2026-09-10T18:00:00Z"
        )

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=data,
        generated_at="2026-09-11T18:00:00Z",
        freshness_policy=freshness_policy(1),
    )

    assert (
        result["evidence_policy"]["freshness_policy_applied"]
        is True
    )
    assert (
        result["freshness_policy"]["policy_id"]
        == "FUND18-FRESHNESS-INTEGRATION-1"
    )


def test_no_freshness_policy_preserves_previous_behavior():
    data = evidence()

    for item in data["IAT"]["dimensions"].values():
        item["sources"][0]["as_of"] = (
            "2020-01-01T00:00:00Z"
        )

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=data,
        generated_at="2026-09-11T18:00:00Z",
    )

    assert (
        result["evidence_policy"]["freshness_policy_applied"]
        is False
    )
    assert "freshness_policy" not in result


def test_unlisted_source_type_has_no_age_limit():
    data = evidence()

    for item in data["IAT"]["dimensions"].values():
        item["sources"][0]["as_of"] = (
            "2020-01-01T00:00:00Z"
        )

    policy = {
        "schema_version":
            "fund18_portfolio_fit_freshness_policy_1",
        "human_approved": True,
        "policy_id": "FUND18-FRESHNESS-KAP-ONLY",
        "source_max_age_days": {
            "KAP_OFFICIAL": 1,
        },
    }

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=data,
        generated_at="2026-09-11T18:00:00Z",
        freshness_policy=policy,
    )

    assert (
        result["candidates"][0]["role_fit"]
        == "STRONG"
    )



def test_automatic_structured_claim_contradiction_forces_unknown():
    data = evidence()

    data["IAT"]["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-ROLE-1",
            "observed_fact": "Role classified as defensive.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_role",
                "value": "defensive",
            },
        },
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-ROLE-2",
            "observed_fact": "Role classified as growth.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_role",
                "value": "growth",
            },
        },
    ]

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert (
        row["evidence"]["dimensions"]["role_fit"]["state"]
        == "CONTRADICTORY"
    )


def test_non_conflicting_structured_claims_preserve_assessment():
    data = evidence()

    data["IAT"]["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-ROLE-1",
            "observed_fact": "Role classified as defensive.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_role",
                "value": "defensive",
            },
        },
        {
            "source_type": "FUND17_PORTFOLIO_CONTEXT",
            "source_id": "SRC-ROLE-2",
            "observed_fact": "Role classified as defensive.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_role",
                "value": "defensive",
            },
        },
    ]

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "STRONG"
    assert (
        row["evidence"]["dimensions"]["role_fit"]["state"]
        == "SUPPORTED"
    )



def test_enriched_claim_is_preserved_in_builder_output():
    data = evidence()

    data["IAT"]["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "KAP_OFFICIAL",
            "source_id": "KAP-IAT-ROLE-1",
            "observed_fact": "Portfolio weight is 35 percent.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 35,
                "unit": "percent",
                "method": "official_portfolio_breakdown",
                "evidence_id": "KAP-IAT-20260911-001",
            },
        },
    ]

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    claim = (
        result["candidates"][0]["evidence"]
        ["dimensions"]["role_fit"]["sources"][0]["claim"]
    )

    assert claim == {
        "field": "portfolio_weight",
        "value": 35,
        "unit": "percent",
        "method": "official_portfolio_breakdown",
        "evidence_id": "KAP-IAT-20260911-001",
    }


def test_enriched_same_unit_conflict_forces_unknown():
    data = evidence()

    data["IAT"]["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "KAP_OFFICIAL",
            "source_id": "SRC-1",
            "observed_fact": "Portfolio weight is 35 percent.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 35,
                "unit": "percent",
                "method": "official_breakdown_a",
                "evidence_id": "E-1",
            },
        },
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-2",
            "observed_fact": "Portfolio weight is 40 percent.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 40,
                "unit": "percent",
                "method": "approved_research_b",
                "evidence_id": "E-2",
            },
        },
    ]

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert (
        row["evidence"]["dimensions"]["role_fit"]["state"]
        == "CONTRADICTORY"
    )


def test_enriched_different_units_do_not_create_false_conflict():
    data = evidence()

    data["IAT"]["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "KAP_OFFICIAL",
            "source_id": "SRC-1",
            "observed_fact": "Portfolio weight is 35 percent.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 35,
                "unit": "percent",
            },
        },
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-2",
            "observed_fact": "Portfolio weight is 3500 basis points.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 3500,
                "unit": "basis_points",
            },
        },
    ]

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        assessments=assessments(),
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "STRONG"
    assert (
        row["evidence"]["dimensions"]["role_fit"]["state"]
        == "SUPPORTED"
    )
