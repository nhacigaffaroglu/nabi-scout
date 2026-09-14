from dataclasses import dataclass

import pytest

import services.turkiye_fund_portfolio_fit_official_exposure as module
from services.turkiye_fund_portfolio_fit_official_exposure import (
    PortfolioFitOfficialExposureError,
    load_official_candidate_exposures,
)


@dataclass
class _Classification:
    primary_exposure: str
    as_of: str
    source: str = "kap_fund"
    ready: bool = True


class _Provider:
    def __init__(self, rows):
        self.rows = rows

    def supports(self, code):
        return code in self.rows

    def economic_classification(self, code):
        value = self.rows[code]
        if isinstance(value, Exception):
            raise value
        return value


def test_requires_explicit_current_evidence_packs():
    with pytest.raises(
        PortfolioFitOfficialExposureError,
        match="current_evidence_packs_required",
    ):
        load_official_candidate_exposures(["GKV"])


def test_uses_caller_supplied_evidence_packs(monkeypatch):
    supplied = {"GKV": {"marker": "current"}}
    observed = {}

    def factory(*, evidence_packs):
        observed["packs"] = evidence_packs
        return _Provider(
            {
                "GKV": _Classification(
                    primary_exposure="equity",
                    as_of="2026-08",
                )
            }
        )

    monkeypatch.setattr(
        module,
        "default_tefas_fund_provider",
        factory,
    )

    result = load_official_candidate_exposures(
        ["gkv", "GKV"],
        evidence_packs=supplied,
    )

    assert observed["packs"] == supplied
    assert set(result) == {"GKV"}
    assert result["GKV"]["primary_exposure"] == "equity"
    assert result["GKV"]["source"] == "kap_fund"
    assert result["GKV"]["ready"] is True


@pytest.mark.parametrize(
    "classification",
    [
        _Classification(
            primary_exposure="equity",
            as_of="2026-08",
            ready=False,
        ),
        _Classification(
            primary_exposure="equity",
            as_of="2026-08",
            source="other",
        ),
        _Classification(
            primary_exposure="",
            as_of="2026-08",
        ),
        _Classification(
            primary_exposure="equity",
            as_of="",
        ),
        None,
        ValueError("classification failed"),
        RuntimeError("classification failed"),
    ],
)
def test_invalid_or_unready_classification_is_omitted(
    monkeypatch,
    classification,
):
    monkeypatch.setattr(
        module,
        "default_tefas_fund_provider",
        lambda *, evidence_packs: _Provider(
            {"GKV": classification}
        ),
    )

    result = load_official_candidate_exposures(
        ["GKV"],
        evidence_packs={"GKV": {"marker": "current"}},
    )

    assert result == {}


def test_unsupported_candidate_is_omitted(monkeypatch):
    monkeypatch.setattr(
        module,
        "default_tefas_fund_provider",
        lambda *, evidence_packs: _Provider({}),
    )

    assert (
        load_official_candidate_exposures(
            ["GKV"],
            evidence_packs={"GKV": {"marker": "current"}},
        )
        == {}
    )
