import services.turkiye_fund_portfolio_fit_production_evidence as module
from services.turkiye_fund_portfolio_fit_production_evidence import (
    ProductionPortfolioFitEvidenceError,
    build_production_portfolio_fit_evidence,
)


def _fund14a():
    return {
        "schema_version": "fund14a_research_snapshot_3",
        "research_only": True,
        "scanner": {
            "persist": False,
            "eight_e_calls": 0,
            "new_money_calls": 0,
            "trades": 0,
            "portfolio_writes": 0,
            "identities": [
                {
                    "fund_code": "GKV",
                    "kap_disclosure_index": 12,
                }
            ],
        },
    }


def _fund16():
    return {
        "categories": [
            {
                "category": "equity",
                "candidates": [
                    {"fund_code": "GKV"},
                ],
            }
        ]
    }


def test_assembly_uses_current_pack_and_read_only_sources(monkeypatch):
    monkeypatch.setattr(
        module,
        "load_official_candidate_exposures",
        lambda codes, evidence_packs: {
            "GKV": {
                "primary_exposure": "equity",
                "as_of": "2026-08",
                "source": "kap_fund",
            }
        },
    )

    monkeypatch.setattr(
        module,
        "build_canonical_portfolio_fit_inputs",
        lambda view, codes: {
            "portfolio_exposure": {
                "completeness": "PARTIAL_EXPOSURE",
                "buckets": [
                    {
                        "bucket_id": "equity",
                        "observable_weight_pct": 88.0,
                    },
                    {
                        "bucket_id": "unknown",
                        "observable_weight_pct": 12.0,
                    },
                ],
            },
            "portfolio_weights": {"GKV": 0.0},
        },
    )

    captured = {}

    def fake_builder(
        fund16,
        fund17,
        *,
        candidate_exposures,
        portfolio_exposure,
        portfolio_weights,
        generated_at,
    ):
        captured["candidate_exposures"] = candidate_exposures
        captured["portfolio_exposure"] = portfolio_exposure
        captured["portfolio_weights"] = portfolio_weights
        return {"GKV": {"schema_version": "fund18_portfolio_fit_evidence_1"}}

    monkeypatch.setattr(
        module,
        "build_portfolio_fit_evidence",
        fake_builder,
    )

    result = build_production_portfolio_fit_evidence(
        _fund14a(),
        _fund16(),
        {},
        object(),
        evidence_packs={
            "GKV": {
                "kap_disclosure_index": 12,
            }
        },
        generated_at="2026-09-13T12:00:00Z",
    )

    assert captured["portfolio_weights"] == {"GKV": 0.0}
    assert captured["portfolio_exposure"]["completeness"] == "PARTIAL_EXPOSURE"
    assert result["diagnostics"]["candidate_codes"] == ["GKV"]
    assert result["diagnostics"]["quarantined_codes"] == []
    assert result["diagnostics"]["network_calls"] == 0
    assert result["diagnostics"]["capture_calls"] == 0
    assert result["diagnostics"]["production_writes"] == 0


def test_stale_pack_is_quarantined_before_official_adapter(monkeypatch):
    seen = {}

    def official(codes, evidence_packs):
        seen["packs"] = evidence_packs
        return {}

    monkeypatch.setattr(
        module,
        "load_official_candidate_exposures",
        official,
    )
    monkeypatch.setattr(
        module,
        "build_canonical_portfolio_fit_inputs",
        lambda view, codes: {
            "portfolio_exposure": {
                "completeness": "PARTIAL_EXPOSURE",
                "buckets": [],
            },
            "portfolio_weights": {},
        },
    )
    monkeypatch.setattr(
        module,
        "build_portfolio_fit_evidence",
        lambda *args, **kwargs: {"GKV": {}},
    )

    result = build_production_portfolio_fit_evidence(
        _fund14a(),
        _fund16(),
        {},
        object(),
        evidence_packs={
            "GKV": {
                "kap_disclosure_index": 11,
            }
        },
    )

    assert seen["packs"] == {}
    assert result["diagnostics"]["quarantined_codes"] == ["GKV"]


def test_fund14a_execution_firewall_fails_closed():
    artifact = _fund14a()
    artifact["scanner"]["eight_e_calls"] = 1

    try:
        build_production_portfolio_fit_evidence(
            artifact,
            _fund16(),
            {},
            object(),
            evidence_packs={},
        )
    except ProductionPortfolioFitEvidenceError as exc:
        assert str(exc) == "fund14a_execution_firewall_failed:eight_e_calls"
    else:
        raise AssertionError("unsafe FUND14A artifact must fail closed")


def test_unsupported_fund14a_schema_fails_closed():
    artifact = _fund14a()
    artifact["schema_version"] = "wrong"

    try:
        build_production_portfolio_fit_evidence(
            artifact,
            _fund16(),
            {},
            object(),
            evidence_packs={},
        )
    except ProductionPortfolioFitEvidenceError as exc:
        assert str(exc) == "unsupported_fund14a_schema"
    else:
        raise AssertionError("unsupported schema must fail closed")
