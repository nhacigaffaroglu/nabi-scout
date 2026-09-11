import copy

import pytest

from services.turkiye_fund_portfolio_fit_evidence import (
    EVIDENCE_SCHEMA,
    PortfolioFitEvidenceContractError,
    normalize_candidate_evidence,
)


def _source():
    return {
        "source_type": "FUND17_PORTFOLIO_CONTEXT",
        "source_id": "synthetic-context-1",
        "observed_fact": "Synthetic evidence fixture only.",
        "as_of": "2026-09-11T18:00:00Z",
    }


def _dimension(state="SUPPORTED"):
    return {
        "state": state,
        "sources": [_source()] if state == "SUPPORTED" else [],
        "rationale": [
            "Synthetic contract fixture; not investment advice."
        ],
    }


def _evidence():
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "fund_code": "IAT",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "dimensions": {
            "role_fit": _dimension(),
            "economic_overlap": _dimension(),
            "diversification_contribution": _dimension(),
            "concentration_risk": _dimension(),
        },
    }


def test_normalizes_complete_supported_evidence():
    result = normalize_candidate_evidence(
        _evidence(),
        expected_code="IAT",
    )

    assert result["fund_code"] == "IAT"
    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["production_persist"] is False

    assert set(result["dimensions"]) == {
        "role_fit",
        "economic_overlap",
        "diversification_contribution",
        "concentration_risk",
    }


def test_rejects_wrong_schema():
    evidence = _evidence()
    evidence["schema_version"] = "wrong"

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="unsupported_evidence_schema:IAT",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


def test_rejects_fund_code_mismatch():
    evidence = _evidence()
    evidence["fund_code"] = "GKV"

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="evidence_fund_code_mismatch:IAT",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "research_only",
            False,
            "evidence_research_only_not_true:IAT",
        ),
        (
            "execution_authority",
            True,
            "evidence_execution_authority_not_false:IAT",
        ),
        (
            "production_persist",
            True,
            "evidence_production_persist_not_false:IAT",
        ),
    ],
)
def test_rejects_firewall_violation(field, value, message):
    evidence = _evidence()
    evidence[field] = value

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match=message,
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


def test_requires_exact_dimension_set():
    evidence = _evidence()
    del evidence["dimensions"]["concentration_risk"]

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="evidence_dimension_set_mismatch:IAT",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


def test_supported_dimension_requires_source():
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["sources"] = []

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="supported_dimension_requires_source:IAT:role_fit",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


@pytest.mark.parametrize(
    "state",
    ["INSUFFICIENT", "CONTRADICTORY"],
)
def test_fail_closed_states_may_have_no_source(state):
    evidence = _evidence()
    evidence["dimensions"]["role_fit"] = _dimension(state)

    result = normalize_candidate_evidence(
        evidence,
        expected_code="IAT",
    )

    assert result["dimensions"]["role_fit"]["state"] == state
    assert result["dimensions"]["role_fit"]["sources"] == []


def test_rejects_invalid_evidence_state():
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["state"] = "GOOD"

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="invalid_evidence_state:IAT:role_fit",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


def test_rejects_unapproved_source_type():
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["sources"][0][
        "source_type"
    ] = "INTERNET_RUMOR"

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="invalid_source_type:IAT:role_fit",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


@pytest.mark.parametrize(
    "field",
    ["source_id", "observed_fact", "as_of"],
)
def test_requires_source_provenance_fields(field):
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["sources"][0][field] = ""

    with pytest.raises(PortfolioFitEvidenceContractError):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


def test_requires_dimension_rationale():
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["rationale"] = []

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="evidence_rationale_required:IAT:role_fit",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


def test_does_not_mutate_input():
    evidence = _evidence()
    before = copy.deepcopy(evidence)

    normalize_candidate_evidence(
        evidence,
        expected_code="IAT",
    )

    assert evidence == before


@pytest.mark.parametrize(
    "as_of",
    [
        "not-a-date",
        "2026-13-11T18:00:00Z",
        "2026-09-11 25:00:00+00:00",
    ],
)
def test_rejects_invalid_as_of_iso8601(as_of):
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["sources"][0]["as_of"] = as_of

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="as_of_must_be_iso8601",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


@pytest.mark.parametrize(
    "as_of",
    [
        "2026-09-11T18:00:00",
        "2026-09-11",
    ],
)
def test_rejects_as_of_without_timezone(as_of):
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["sources"][0]["as_of"] = as_of

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="as_of_must_include_timezone",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
        )


@pytest.mark.parametrize(
    "as_of",
    [
        "2026-09-11T18:00:00Z",
        "2026-09-11T21:00:00+03:00",
        "2026-09-11T18:00:00+00:00",
    ],
)
def test_accepts_timezone_aware_iso8601_as_of(as_of):
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["sources"][0]["as_of"] = as_of

    result = normalize_candidate_evidence(
        evidence,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["sources"][0]["as_of"]
        == as_of
    )


def test_rejects_evidence_after_not_after_timestamp():
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["sources"][0]["as_of"] = (
        "2026-09-11T18:00:01Z"
    )

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="evidence_as_of_in_future:IAT:role_fit",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
            not_after="2026-09-11T18:00:00Z",
        )


def test_accepts_evidence_equal_to_not_after_timestamp():
    result = normalize_candidate_evidence(
        _evidence(),
        expected_code="IAT",
        not_after="2026-09-11T18:00:00Z",
    )

    assert (
        result["dimensions"]["role_fit"]["sources"][0]["as_of"]
        == "2026-09-11T18:00:00Z"
    )


def test_compares_as_of_across_timezones():
    evidence = _evidence()
    evidence["dimensions"]["role_fit"]["sources"][0]["as_of"] = (
        "2026-09-11T21:00:01+03:00"
    )

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="evidence_as_of_in_future:IAT:role_fit",
    ):
        normalize_candidate_evidence(
            evidence,
            expected_code="IAT",
            not_after="2026-09-11T18:00:00Z",
        )
