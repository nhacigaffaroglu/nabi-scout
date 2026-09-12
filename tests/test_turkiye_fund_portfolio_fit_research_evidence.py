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


def test_supported_evidence_without_derivation_maps_to_unknown():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=evidence(),
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert row["economic_overlap"] == "UNKNOWN"
    assert row["diversification_contribution"] == "UNKNOWN"
    assert row["concentration_risk"] == "UNKNOWN"


@pytest.mark.parametrize(
    "state",
    ["INSUFFICIENT", "CONTRADICTORY"],
)
def test_non_supported_evidence_forces_unknown(state):
    data = evidence()
    data["IAT"]["dimensions"]["role_fit"] = dimension(state)

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=data,
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert row["economic_overlap"] == "UNKNOWN"


def test_output_carries_normalized_evidence_and_policy():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
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
            evidence={},
        )


def test_firewall_remains_zero():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
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
        evidence=data,
        generated_at="2026-09-11T18:00:00Z",
        freshness_policy=policy,
    )

    assert (
        result["candidates"][0]["role_fit"]
        == "UNKNOWN"
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
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert (
        row["evidence"]["dimensions"]["role_fit"]["state"]
        == "CONTRADICTORY"
    )


def test_non_conflicting_non_assessment_claims_do_not_derive_assessment():
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
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
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
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert (
        row["evidence"]["dimensions"]["role_fit"]["state"]
        == "CONTRADICTORY"
    )


def test_enriched_different_units_remain_supported_but_do_not_derive():
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
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert (
        row["evidence"]["dimensions"]["role_fit"]["state"]
        == "SUPPORTED"
    )



def test_explicit_structured_assessment_overrides_external_value():
    data = evidence()
    assessment_data = assessments()
    assessment_data["IAT"]["role_fit"] = "WEAK"

    data["IAT"]["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["role_fit"]["sources"][0]["claim"] = {
        "field": "role_fit",
        "value": "STRONG",
        "method": "human_approved_explicit_assessment",
        "evidence_id": "ROLE-IAT-001",
    }

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    assert result["candidates"][0]["role_fit"] == "STRONG"


def test_non_assessment_claim_does_not_derive_assessment():
    data = evidence()
    assessment_data = assessments()
    assessment_data["IAT"]["role_fit"] = "PARTIAL"

    data["IAT"]["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["role_fit"]["sources"][0]["claim"] = {
        "field": "portfolio_weight",
        "value": 35,
        "unit": "percent",
    }

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    assert result["candidates"][0]["role_fit"] == "UNKNOWN"


def test_explicit_assessment_claim_requires_valid_dimension_enum():
    data = evidence()

    data["IAT"]["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["role_fit"]["sources"][0]["claim"] = {
        "field": "role_fit",
        "value": "BUY",
    }

    with pytest.raises(
        PortfolioFitResearchContractError,
        match="invalid_derived_assessment:IAT:role_fit",
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17(),
            evidence=data,
            generated_at="2026-09-11T20:00:00Z",
        )


def test_assessment_claim_cannot_target_another_dimension():
    data = evidence()

    data["IAT"]["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["role_fit"]["sources"][0]["claim"] = {
        "field": "economic_overlap",
        "value": "LOW",
    }

    with pytest.raises(
        PortfolioFitResearchContractError,
        match=(
            "assessment_claim_dimension_mismatch:"
            "IAT:role_fit:economic_overlap"
        ),
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17(),
            evidence=data,
            generated_at="2026-09-11T20:00:00Z",
        )


def test_insufficient_evidence_cannot_activate_explicit_assessment():
    data = evidence()
    assessment_data = assessments()
    assessment_data["IAT"]["role_fit"] = "WEAK"

    data["IAT"]["dimensions"]["role_fit"]["state"] = "INSUFFICIENT"
    data["IAT"]["dimensions"]["role_fit"]["sources"][0]["claim"] = {
        "field": "role_fit",
        "value": "STRONG",
    }

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    assert result["candidates"][0]["role_fit"] == "UNKNOWN"


def test_explicit_assessment_claim_is_dimension_specific():
    data = evidence()
    assessment_data = assessments()
    assessment_data["IAT"]["economic_overlap"] = "HIGH"

    data["IAT"]["dimensions"]["economic_overlap"]["state"] = "SUPPORTED"
    data["IAT"]["dimensions"]["economic_overlap"]["sources"][0]["claim"] = {
        "field": "economic_overlap",
        "value": "LOW",
        "method": "human_approved_explicit_assessment",
        "evidence_id": "OVERLAP-IAT-001",
    }

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=data,
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["economic_overlap"] == "LOW"
    assert row["role_fit"] == "UNKNOWN"


def _metric_policy_for_builder_test():
    return {
        "schema_version": "fund18_metric_assessment_policy_1",
        "human_approved": True,
        "locked": True,
        "policy_id": "FUND18-METRIC-BUILDER-TEST-1",
        "rules": [
            {
                "rule_id": "R1",
                "dimension": "concentration_risk",
                "claim_field": "portfolio_weight",
                "unit": "percent",
                "operator": "gte",
                "threshold": 25,
                "assessment": "HIGH",
            }
        ],
    }


def test_evidence_builder_carries_validated_metric_assessment_policy():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=evidence(),
        generated_at="2026-09-11T20:00:00Z",
        metric_assessment_policy=_metric_policy_for_builder_test(),
    )

    assert result["metric_assessment_policy"] == (
        _metric_policy_for_builder_test()
    )
    assert (
        result["evidence_policy"]["metric_assessment_policy_applied"]
        is True
    )


def test_metric_policy_without_matching_metric_claims_does_not_derive():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=evidence(),
        generated_at="2026-09-11T20:00:00Z",
        metric_assessment_policy=_metric_policy_for_builder_test(),
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert row["economic_overlap"] == "UNKNOWN"
    assert row["diversification_contribution"] == "UNKNOWN"
    assert row["concentration_risk"] == "UNKNOWN"


def test_evidence_builder_rejects_invalid_metric_assessment_policy():
    policy = _metric_policy_for_builder_test()
    policy["human_approved"] = False

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="metric_assessment_policy_not_human_approved",
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17(),
            evidence=evidence(),
            generated_at="2026-09-11T20:00:00Z",
            metric_assessment_policy=policy,
        )


def test_evidence_builder_marks_metric_policy_not_applied_when_absent():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=evidence(),
        generated_at="2026-09-11T20:00:00Z",
    )

    assert "metric_assessment_policy" not in result
    assert (
        result["evidence_policy"]["metric_assessment_policy_applied"]
        is False
    )


def _evidence_with_portfolio_weight(
    value,
    *,
    unit="percent",
    dimension_name="concentration_risk",
):
    data = evidence()
    data["IAT"]["dimensions"][dimension_name]["sources"][0]["claim"] = {
        "field": "portfolio_weight",
        "value": value,
        "unit": unit,
    }
    return data


def test_metric_policy_derives_assessment_from_explicit_numeric_claim():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=_evidence_with_portfolio_weight(30),
        generated_at="2026-09-11T20:00:00Z",
        metric_assessment_policy=_metric_policy_for_builder_test(),
    )

    row = result["candidates"][0]

    assert row["concentration_risk"] == "HIGH"


def test_metric_policy_compares_percent_and_basis_points_canonically():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=_evidence_with_portfolio_weight(
            3000,
            unit="basis_points",
        ),
        generated_at="2026-09-11T20:00:00Z",
        metric_assessment_policy=_metric_policy_for_builder_test(),
    )

    row = result["candidates"][0]

    assert row["concentration_risk"] == "HIGH"


def test_metric_policy_no_match_does_not_use_external_assessment():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=_evidence_with_portfolio_weight(10),
        generated_at="2026-09-11T20:00:00Z",
        metric_assessment_policy=_metric_policy_for_builder_test(),
    )

    row = result["candidates"][0]

    assert row["concentration_risk"] == "UNKNOWN"


def test_metric_policy_requires_metric_claim_unit():
    data = _evidence_with_portfolio_weight(30)
    del data["IAT"]["dimensions"]["concentration_risk"]["sources"][0][
        "claim"
    ]["unit"]

    with pytest.raises(
        PortfolioFitResearchContractError,
        match="metric_claim_unit_required:IAT:concentration_risk",
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17(),
            evidence=data,
            generated_at="2026-09-11T20:00:00Z",
            metric_assessment_policy=_metric_policy_for_builder_test(),
        )


def test_metric_policy_rejects_non_numeric_metric_claim():
    data = _evidence_with_portfolio_weight("30")

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="invalid_metric_claim_value:portfolio_weight",
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17(),
            evidence=data,
            generated_at="2026-09-11T20:00:00Z",
            metric_assessment_policy=_metric_policy_for_builder_test(),
        )


def test_metric_policy_multiple_matching_assessments_fail_closed():
    policy = _metric_policy_for_builder_test()
    policy["rules"].append(
        {
            "rule_id": "R2",
            "dimension": "concentration_risk",
            "claim_field": "portfolio_weight",
            "unit": "percent",
            "operator": "gte",
            "threshold": 20,
            "assessment": "LOW",
        }
    )

    with pytest.raises(
        PortfolioFitResearchContractError,
        match=(
            "contradictory_metric_policy_assessment:"
            "IAT:concentration_risk"
        ),
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17(),
            evidence=_evidence_with_portfolio_weight(30),
            generated_at="2026-09-11T20:00:00Z",
            metric_assessment_policy=policy,
        )


def test_explicit_and_metric_assessment_disagreement_fails_closed():
    data = _evidence_with_portfolio_weight(30)

    data["IAT"]["dimensions"]["concentration_risk"]["sources"].append(
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "explicit-assessment-1",
            "observed_fact": "Synthetic explicit assessment.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "concentration_risk",
                "value": "LOW",
            },
        }
    )

    with pytest.raises(
        PortfolioFitResearchContractError,
        match="contradictory_derived_assessment:IAT:concentration_risk",
    ):
        build_evidence_backed_portfolio_fit_research_artifact(
            fund17(),
            evidence=data,
            generated_at="2026-09-11T20:00:00Z",
            metric_assessment_policy=_metric_policy_for_builder_test(),
        )


def test_external_assessment_is_not_used_as_fallback():
    supplied = assessments()
    supplied["IAT"]["concentration_risk"] = "HIGH"

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=evidence(),
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["concentration_risk"] == "UNKNOWN"
    assert (
        result["evidence_policy"][
            "external_assessment_fallback_used"
        ]
        is False
    )


def test_metric_policy_no_match_maps_to_unknown_without_external_fallback():
    supplied = assessments()
    supplied["IAT"]["concentration_risk"] = "HIGH"

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=_evidence_with_portfolio_weight(10),
        generated_at="2026-09-11T20:00:00Z",
        metric_assessment_policy=_metric_policy_for_builder_test(),
    )

    row = result["candidates"][0]

    assert row["concentration_risk"] == "UNKNOWN"


def test_external_assessment_candidate_set_is_no_longer_authoritative():
    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17(),
        evidence=evidence(),
        generated_at="2026-09-11T20:00:00Z",
    )

    row = result["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert row["economic_overlap"] == "UNKNOWN"
    assert row["diversification_contribution"] == "UNKNOWN"
    assert row["concentration_risk"] == "UNKNOWN"
