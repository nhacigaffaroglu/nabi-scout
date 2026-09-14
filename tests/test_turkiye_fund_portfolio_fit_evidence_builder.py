from services.turkiye_fund_portfolio_fit_evidence_builder import (
    PortfolioFitEvidenceBuilderError,
    build_portfolio_fit_evidence,
)


def _fund16():
    return {
        "schema_version": "fund16_category_comparison_artifact_1",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "categories": [
            {
                "category": "equity",
                "candidates": [
                    {
                        "fund_code": "GKV",
                        "category": "equity",
                        "fi_score": 82.33,
                    }
                ],
            }
        ],
    }


def _fund17():
    return {
        "schema_version": "fund17_portfolio_fit_artifact_1",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "portfolio_context_available": True,
        "portfolio_context": {
            "schema_version": "fund17_portfolio_context_1",
            "human_supplied": True,
            "research_only": True,
            "execution_authority": False,
            "desired_roles": ["core_growth", "diversification"],
            "existing_exposures": ["equity", "sukuk", "cash_like"],
            "constraints": ["participation_compliant"],
        },
        "candidates": [{"fund_code": "GKV"}],
    }


def test_builder_emits_contract_valid_fact_only_evidence():
    result = build_portfolio_fit_evidence(
        _fund16(),
        _fund17(),
        candidate_exposures={
            "GKV": {
                "primary_exposure": "equity",
                "as_of": "2026-09-13T00:00:00Z",
            }
        },
        portfolio_exposure={
            "completeness": "COMPLETE_EXPOSURE",
            "buckets": [
                {
                    "bucket_id": "equity",
                    "observable_weight_pct": 60.0,
                },
                {
                    "bucket_id": "sukuk",
                    "observable_weight_pct": 40.0,
                },
            ],
        },
        portfolio_weights={"GKV": 0.0},
        generated_at="2026-09-13T12:00:00Z",
    )

    row = result["GKV"]
    assert row["schema_version"] == "fund18_portfolio_fit_evidence_1"
    assert row["research_only"] is True
    assert row["execution_authority"] is False
    assert row["production_persist"] is False
    assert set(row["dimensions"]) == {
        "role_fit",
        "economic_overlap",
        "diversification_contribution",
        "concentration_risk",
    }

    assert row["dimensions"]["role_fit"]["state"] == "SUPPORTED"
    assert row["dimensions"]["economic_overlap"]["state"] == "SUPPORTED"
    assert (
        row["dimensions"]["diversification_contribution"]["state"]
        == "SUPPORTED"
    )
    assert row["dimensions"]["concentration_risk"]["state"] == "SUPPORTED"

    weight_claim = row["dimensions"]["concentration_risk"]["sources"][0]["claim"]
    assert weight_claim == {
        "field": "portfolio_weight",
        "value": 0.0,
        "unit": "percent",
    }


def test_missing_real_exposure_fails_closed_per_dimension():
    result = build_portfolio_fit_evidence(
        _fund16(),
        _fund17(),
        generated_at="2026-09-13T12:00:00Z",
    )

    row = result["GKV"]
    assert row["dimensions"]["role_fit"]["state"] == "SUPPORTED"
    assert row["dimensions"]["economic_overlap"]["state"] == "INSUFFICIENT"
    assert (
        row["dimensions"]["diversification_contribution"]["state"]
        == "INSUFFICIENT"
    )
    assert row["dimensions"]["concentration_risk"]["state"] == "INSUFFICIENT"


def test_candidate_sets_must_match_exactly():
    fund17 = _fund17()
    fund17["candidates"].append({"fund_code": "IAT"})

    try:
        build_portfolio_fit_evidence(
            _fund16(),
            fund17,
            generated_at="2026-09-13T12:00:00Z",
        )
    except PortfolioFitEvidenceBuilderError as exc:
        assert str(exc) == "fund16_fund17_candidate_set_mismatch"
    else:
        raise AssertionError("candidate-set mismatch must fail closed")


def test_candidate_exposure_alone_does_not_support_overlap_or_diversification():
    result = build_portfolio_fit_evidence(
        _fund16(),
        _fund17(),
        candidate_exposures={
            "GKV": {
                "primary_exposure": "equity",
                "as_of": "2026-08",
            }
        },
        generated_at="2026-09-13T12:00:00Z",
    )

    row = result["GKV"]

    assert row["dimensions"]["role_fit"]["state"] == "SUPPORTED"
    assert row["dimensions"]["economic_overlap"]["state"] == "INSUFFICIENT"
    assert (
        row["dimensions"]["diversification_contribution"]["state"]
        == "INSUFFICIENT"
    )
    assert row["dimensions"]["concentration_risk"]["state"] == "INSUFFICIENT"


def test_portfolio_exposure_requires_observable_bucket_facts():
    result = build_portfolio_fit_evidence(
        _fund16(),
        _fund17(),
        candidate_exposures={
            "GKV": {
                "primary_exposure": "equity",
                "as_of": "2026-08",
            }
        },
        portfolio_exposure={
            "completeness": "COMPLETE_EXPOSURE",
            "buckets": [],
        },
        generated_at="2026-09-13T12:00:00Z",
    )

    row = result["GKV"]

    assert row["dimensions"]["economic_overlap"]["state"] == "INSUFFICIENT"
    assert (
        row["dimensions"]["diversification_contribution"]["state"]
        == "INSUFFICIENT"
    )


def test_canonical_portfolio_exposure_is_not_labeled_human_research():
    result = build_portfolio_fit_evidence(
        _fund16(),
        _fund17(),
        candidate_exposures={
            "GKV": {
                "primary_exposure": "equity",
                "as_of": "2026-08",
            }
        },
        portfolio_exposure={
            "completeness": "COMPLETE_EXPOSURE",
            "buckets": [
                {
                    "bucket_id": "equity",
                    "observable_weight_pct": 100.0,
                }
            ],
        },
        generated_at="2026-09-13T12:00:00Z",
    )

    sources = result["GKV"]["dimensions"]["economic_overlap"]["sources"]

    assert any(
        source["source_id"] == "portfolio-economic-exposure"
        and source["source_type"] == "PORTFOLIO_CANONICAL"
        for source in sources
    )
    assert not any(
        source["source_id"] == "portfolio-economic-exposure"
        and source["source_type"] == "HUMAN_APPROVED_RESEARCH"
        for source in sources
    )
