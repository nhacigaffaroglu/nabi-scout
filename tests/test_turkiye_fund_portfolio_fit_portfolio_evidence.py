import services.turkiye_fund_portfolio_fit_portfolio_evidence as module
from services.turkiye_fund_portfolio_fit_portfolio_evidence import (
    PortfolioFitPortfolioEvidenceError,
    build_canonical_portfolio_fit_inputs,
)


class _Exposure:
    def to_dict(self):
        return {
            "completeness": "PARTIAL_EXPOSURE",
            "valuation_coverage_pct": 100.0,
            "exposure_classification_coverage_pct": 88.0,
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
        }


def test_requires_canonical_portfolio_view():
    try:
        build_canonical_portfolio_fit_inputs(None, ["GKV"])
    except PortfolioFitPortfolioEvidenceError as exc:
        assert str(exc) == "canonical_portfolio_view_required"
    else:
        raise AssertionError("missing canonical view must fail closed")


def test_preserves_canonical_exposure_and_explicit_not_held_zero(monkeypatch):
    monkeypatch.setattr(
        module,
        "build_economic_exposure",
        lambda view: _Exposure(),
    )
    monkeypatch.setattr(
        module,
        "build_wealth_exposure_context",
        lambda view, code: {
            "held": False,
            "current_weight_pct": None,
        },
    )

    result = build_canonical_portfolio_fit_inputs(
        object(),
        ["gkv", "GKV"],
    )

    assert result["portfolio_exposure"]["completeness"] == "PARTIAL_EXPOSURE"
    assert (
        result["portfolio_exposure"]["exposure_classification_coverage_pct"]
        == 88.0
    )
    assert result["portfolio_weights"] == {"GKV": 0.0}
    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["production_persist"] is False


def test_held_candidate_uses_canonical_current_weight(monkeypatch):
    monkeypatch.setattr(
        module,
        "build_economic_exposure",
        lambda view: _Exposure(),
    )
    monkeypatch.setattr(
        module,
        "build_wealth_exposure_context",
        lambda view, code: {
            "held": True,
            "current_weight_pct": 3.25,
        },
    )

    result = build_canonical_portfolio_fit_inputs(
        object(),
        ["GKV"],
    )

    assert result["portfolio_weights"] == {"GKV": 3.25}


def test_ambiguous_weight_is_omitted_fail_closed(monkeypatch):
    monkeypatch.setattr(
        module,
        "build_economic_exposure",
        lambda view: _Exposure(),
    )
    monkeypatch.setattr(
        module,
        "build_wealth_exposure_context",
        lambda view, code: {
            "held": True,
            "current_weight_pct": None,
        },
    )

    result = build_canonical_portfolio_fit_inputs(
        object(),
        ["GKV"],
    )

    assert result["portfolio_weights"] == {}


def test_bridge_failure_omits_weight_fail_closed(monkeypatch):
    monkeypatch.setattr(
        module,
        "build_economic_exposure",
        lambda view: _Exposure(),
    )

    def fail(view, code):
        raise ValueError("unavailable")

    monkeypatch.setattr(
        module,
        "build_wealth_exposure_context",
        fail,
    )

    result = build_canonical_portfolio_fit_inputs(
        object(),
        ["GKV"],
    )

    assert result["portfolio_weights"] == {}


def test_invalid_exposure_contract_fails_closed(monkeypatch):
    monkeypatch.setattr(
        module,
        "build_economic_exposure",
        lambda view: {
            "completeness": "",
            "buckets": [],
        },
    )

    try:
        build_canonical_portfolio_fit_inputs(
            object(),
            ["GKV"],
        )
    except PortfolioFitPortfolioEvidenceError as exc:
        assert str(exc) == "portfolio_exposure_completeness_missing"
    else:
        raise AssertionError("invalid exposure must fail closed")
