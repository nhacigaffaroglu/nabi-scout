import pytest

from services.turkiye_fund_portfolio_fit_assessment_engine import (
    MODE_EFFECTIVE,
    MODE_SIMULATION,
    PortfolioFitAssessmentEngineError,
    evaluate_portfolio_fit_assessments,
)
from services.turkiye_fund_portfolio_fit_assessment_facts import (
    build_portfolio_fit_assessment_facts,
)
from services.turkiye_fund_portfolio_fit_assessment_policy import (
    draft_fund18_assessment_policy_v1,
    normalize_fund18_assessment_policy,
)


def evidence(states=None):
    states = states or {}
    return {
        "schema_version":
            "fund18_portfolio_fit_evidence_1",
        "dimensions": {
            name: {
                "state": states.get(
                    name,
                    "SUPPORTED",
                )
            }
            for name in (
                "role_fit",
                "economic_overlap",
                "diversification_contribution",
                "concentration_risk",
            )
        },
    }


def facts(
    *,
    code="GKV",
    exposure="equity",
    buckets=None,
    unknown=11.1529,
    weight=0.0,
    completeness="PARTIAL_EXPOSURE",
    roles=("core_growth", "diversification"),
    states=None,
):
    if buckets is None:
        buckets = {
            "equity": 88.8471,
        }

    portfolio_buckets = dict(buckets)
    if unknown is not None:
        portfolio_buckets["unknown"] = unknown

    return build_portfolio_fit_assessment_facts(
        fund_code=code,
        evidence=evidence(states),
        candidate_exposure={
            "primary_exposure": exposure,
            "as_of": "2026-08-31T23:59:59Z",
            "confidence": "MEDIUM",
        },
        portfolio_exposure={
            "completeness": completeness,
            "buckets": portfolio_buckets,
        },
        current_weight_pct=weight,
        desired_roles=roles,
    )


def policy():
    return normalize_fund18_assessment_policy(
        draft_fund18_assessment_policy_v1()
    )


def test_gkv_draft_simulation_matches_expected_policy():
    result = evaluate_portfolio_fit_assessments(
        facts(),
        policy(),
        mode=MODE_SIMULATION,
    )

    assert result.role_fit.assessment == "STRONG"
    assert (
        result.role_fit.rule_id
        == "ROLE-EQUITY-CORE-GROWTH-01"
    )

    assert result.economic_overlap.assessment == "HIGH"
    assert (
        result.economic_overlap.rule_id
        == "OVERLAP-HIGH-01"
    )
    assert result.economic_overlap.confidence == "MEDIUM"

    assert (
        result.diversification_contribution.assessment
        == "LOW"
    )
    assert (
        result.diversification_contribution.rule_id
        == "DIVERSIFICATION-LOW-01"
    )

    assert result.concentration_risk.assessment == "LOW"
    assert (
        result.concentration_risk.rule_id
        == "CONCENTRATION-LOW-01"
    )

    assert result.production_effective is False


def test_unmeasured_sukuk_bucket_is_unknown_not_zero():
    result = evaluate_portfolio_fit_assessments(
        facts(
            code="IAT",
            exposure="sukuk",
            buckets={"equity": 88.8471},
        ),
        policy(),
    )

    assert result.role_fit.assessment == "STRONG"

    assert result.economic_overlap.assessment == "UNKNOWN"
    assert (
        result.economic_overlap.reason_code
        == "PORTFOLIO_BUCKET_UNMEASURED"
    )
    assert (
        result.economic_overlap.rule_id
        == "OVERLAP-UNKNOWN-UNMEASURED-01"
    )

    assert (
        result.diversification_contribution.assessment
        == "UNKNOWN"
    )


def test_overlap_cross_band_interval_fails_closed():
    result = evaluate_portfolio_fit_assessments(
        facts(
            buckets={"equity": 30.0},
            unknown=12.0,
        ),
        policy(),
    )

    assert result.economic_overlap.assessment == "UNKNOWN"
    assert (
        result.economic_overlap.reason_code
        == "UNCERTAINTY_CROSSES_POLICY_BOUNDARY"
    )
    assert (
        result.economic_overlap.rule_id
        == "OVERLAP-UNKNOWN-CROSS-BAND-01"
    )


def test_diversification_cross_band_interval_fails_closed():
    result = evaluate_portfolio_fit_assessments(
        facts(
            buckets={"equity": 20.0},
            unknown=12.0,
        ),
        policy(),
    )

    assert (
        result.diversification_contribution.assessment
        == "UNKNOWN"
    )
    assert (
        result.diversification_contribution.reason_code
        == "UNCERTAINTY_CROSSES_POLICY_BOUNDARY"
    )


def test_unknown_portfolio_share_is_not_renormalized():
    result = evaluate_portfolio_fit_assessments(
        facts(
            buckets={"equity": 88.8471},
            unknown=11.1529,
        ),
        policy(),
    )

    interval = (
        result.economic_overlap
        .structured_facts[
            "possible_true_bucket_interval_pct"
        ]
    )

    assert interval == [88.8471, 100.0]


def test_unsupported_evidence_only_blocks_its_dimension():
    result = evaluate_portfolio_fit_assessments(
        facts(
            states={
                "economic_overlap": "INSUFFICIENT",
            }
        ),
        policy(),
    )

    assert result.role_fit.assessment == "STRONG"
    assert result.economic_overlap.assessment == "UNKNOWN"
    assert (
        result.economic_overlap.reason_code
        == "EVIDENCE_NOT_SUPPORTED"
    )
    assert (
        result.diversification_contribution.assessment
        == "LOW"
    )
    assert result.concentration_risk.assessment == "LOW"


@pytest.mark.parametrize(
    ("weight", "expected", "rule_id"),
    [
        (0.0, "LOW", "CONCENTRATION-LOW-01"),
        (5.0, "LOW", "CONCENTRATION-LOW-01"),
        (5.01, "MEDIUM", "CONCENTRATION-MEDIUM-01"),
        (10.0, "MEDIUM", "CONCENTRATION-MEDIUM-01"),
        (10.01, "HIGH", "CONCENTRATION-HIGH-01"),
    ],
)
def test_current_concentration_thresholds(
    weight,
    expected,
    rule_id,
):
    result = evaluate_portfolio_fit_assessments(
        facts(weight=weight),
        policy(),
    )

    assert result.concentration_risk.assessment == expected
    assert result.concentration_risk.rule_id == rule_id


def test_missing_current_weight_is_unknown():
    result = evaluate_portfolio_fit_assessments(
        facts(weight=None),
        policy(),
    )

    assert result.concentration_risk.assessment == "UNKNOWN"
    assert (
        result.concentration_risk.reason_code
        == "CURRENT_WEIGHT_UNAVAILABLE"
    )


def test_best_supported_role_match_wins():
    result = evaluate_portfolio_fit_assessments(
        facts(
            exposure="multi_asset",
            roles=("core_growth", "diversification"),
            buckets={"multi_asset": 5.0},
            unknown=0.0,
        ),
        policy(),
    )

    assert result.role_fit.assessment == "STRONG"
    assert (
        result.role_fit.rule_id
        == "ROLE-MULTI-ASSET-DIVERSIFICATION-01"
    )


def test_draft_policy_cannot_run_effective_mode():
    with pytest.raises(
        PortfolioFitAssessmentEngineError,
        match="effective_mode_requires_human_approval",
    ):
        evaluate_portfolio_fit_assessments(
            facts(),
            policy(),
            mode=MODE_EFFECTIVE,
        )


def test_fully_effective_policy_can_run_effective_mode():
    raw = draft_fund18_assessment_policy_v1()
    raw["human_approved"] = True
    raw["locked"] = True
    raw["production_effective"] = True

    effective_policy = (
        normalize_fund18_assessment_policy(
            raw,
            require_effective=True,
        )
    )

    result = evaluate_portfolio_fit_assessments(
        facts(),
        effective_policy,
        mode=MODE_EFFECTIVE,
    )

    assert result.production_effective is True
    assert result.mode == MODE_EFFECTIVE
