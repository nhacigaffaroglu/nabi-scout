import copy

import pytest

from services.turkiye_fund_portfolio_fit_evidence import (
    EVIDENCE_SCHEMA,
    FRESHNESS_POLICY_SCHEMA,
    PortfolioFitEvidenceContractError,
    normalize_candidate_evidence,
    normalize_freshness_policy,
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


def _freshness_policy():
    return {
        "schema_version": FRESHNESS_POLICY_SCHEMA,
        "human_approved": True,
        "policy_id": "FUND18-FRESHNESS-TEST-1",
        "source_max_age_days": {
            "KAP_OFFICIAL": 30,
            "FUND17_PORTFOLIO_CONTEXT": 7,
        },
    }


def test_normalizes_human_approved_freshness_policy():
    result = normalize_freshness_policy(
        _freshness_policy(),
    )

    assert result == {
        "schema_version": FRESHNESS_POLICY_SCHEMA,
        "human_approved": True,
        "policy_id": "FUND18-FRESHNESS-TEST-1",
        "source_max_age_days": {
            "FUND17_PORTFOLIO_CONTEXT": 7,
            "KAP_OFFICIAL": 30,
        },
    }


def test_freshness_policy_requires_human_approval():
    policy = _freshness_policy()
    policy["human_approved"] = False

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="freshness_policy_not_human_approved",
    ):
        normalize_freshness_policy(policy)


def test_freshness_policy_requires_policy_id():
    policy = _freshness_policy()
    policy["policy_id"] = ""

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="freshness_policy_id_must_be_nonempty_string",
    ):
        normalize_freshness_policy(policy)


def test_freshness_policy_requires_at_least_one_source_limit():
    policy = _freshness_policy()
    policy["source_max_age_days"] = {}

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="freshness_policy_requires_source_limit",
    ):
        normalize_freshness_policy(policy)


def test_freshness_policy_rejects_unknown_source_type():
    policy = _freshness_policy()
    policy["source_max_age_days"]["INTERNET_RUMOR"] = 10

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match=(
            "freshness_policy_invalid_source_type:"
            "INTERNET_RUMOR"
        ),
    ):
        normalize_freshness_policy(policy)


@pytest.mark.parametrize(
    "value",
    [0, -1, 1.5, True, "30", None],
)
def test_freshness_policy_rejects_invalid_max_age_days(value):
    policy = _freshness_policy()
    policy["source_max_age_days"]["KAP_OFFICIAL"] = value

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match=(
            "freshness_policy_invalid_max_age_days:"
            "KAP_OFFICIAL"
        ),
    ):
        normalize_freshness_policy(policy)


def test_freshness_policy_rejects_wrong_schema():
    policy = _freshness_policy()
    policy["schema_version"] = "wrong"

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="unsupported_freshness_policy_schema",
    ):
        normalize_freshness_policy(policy)



def test_normalizes_optional_structured_claim():
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "economic_exposure",
        "value": "sukuk",
    }

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["sources"][0]["claim"]
        == {
            "field": "economic_exposure",
            "value": "sukuk",
        }
    )


def test_source_without_structured_claim_remains_valid():
    result = normalize_candidate_evidence(
        _evidence(),
        expected_code="IAT",
    )

    assert (
        "claim"
        not in result["dimensions"]["role_fit"]["sources"][0]
    )


def test_structured_claim_requires_exact_field_set():
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "economic_exposure",
        "value": "sukuk",
        "confidence": 0.9,
    }

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="claim_field_set_mismatch",
    ):
        normalize_candidate_evidence(
            data,
            expected_code="IAT",
        )


@pytest.mark.parametrize(
    "value",
    [None, {}, [], ""],
)
def test_structured_claim_rejects_invalid_value(value):
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "economic_exposure",
        "value": value,
    }

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="claim_value_",
    ):
        normalize_candidate_evidence(
            data,
            expected_code="IAT",
        )


def test_structured_claim_requires_nonempty_field():
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": " ",
        "value": "sukuk",
    }

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="claim_field_must_be_nonempty_string",
    ):
        normalize_candidate_evidence(
            data,
            expected_code="IAT",
        )



def _claim_source(
    *,
    source_id,
    field,
    value,
):
    return {
        "source_type": "HUMAN_APPROVED_RESEARCH",
        "source_id": source_id,
        "observed_fact": f"{field}={value}",
        "as_of": "2026-09-11T18:00:00Z",
        "claim": {
            "field": field,
            "value": value,
        },
    }


def test_structured_claim_conflict_becomes_contradictory():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        _claim_source(
            source_id="SRC-1",
            field="economic_exposure",
            value="sukuk",
        ),
        _claim_source(
            source_id="SRC-2",
            field="economic_exposure",
            value="equity",
        ),
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "CONTRADICTORY"
    )


def test_same_structured_claim_value_is_not_contradictory():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        _claim_source(
            source_id="SRC-1",
            field="economic_exposure",
            value="sukuk",
        ),
        _claim_source(
            source_id="SRC-2",
            field="economic_exposure",
            value="sukuk",
        ),
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "SUPPORTED"
    )


def test_different_claim_fields_are_not_contradictory():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        _claim_source(
            source_id="SRC-1",
            field="economic_exposure",
            value="sukuk",
        ),
        _claim_source(
            source_id="SRC-2",
            field="liquidity_profile",
            value="daily",
        ),
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "SUPPORTED"
    )


def test_conflict_overrides_insufficient_to_contradictory():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "INSUFFICIENT"
    data["dimensions"]["role_fit"]["sources"] = [
        _claim_source(
            source_id="SRC-1",
            field="economic_exposure",
            value="sukuk",
        ),
        _claim_source(
            source_id="SRC-2",
            field="economic_exposure",
            value="equity",
        ),
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "CONTRADICTORY"
    )


def test_bool_and_int_claim_values_do_not_collapse():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        _claim_source(
            source_id="SRC-1",
            field="portfolio_weight",
            value=True,
        ),
        _claim_source(
            source_id="SRC-2",
            field="portfolio_weight",
            value=1,
        ),
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "CONTRADICTORY"
    )


def test_free_text_difference_alone_is_not_contradiction():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-1",
            "observed_fact": "Exposure looks sukuk-heavy.",
            "as_of": "2026-09-11T18:00:00Z",
        },
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-2",
            "observed_fact": "Exposure looks equity-heavy.",
            "as_of": "2026-09-11T18:00:00Z",
        },
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "SUPPORTED"
    )



def test_structured_claim_enrichment_is_normalized():
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "portfolio_weight",
        "value": 35.5,
        "unit": "percent",
        "method": "official_portfolio_breakdown",
        "evidence_id": "KAP-IAT-20260911-001",
    }

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["sources"][0]["claim"]
        == {
            "field": "portfolio_weight",
            "value": 35.5,
            "unit": "percent",
            "method": "official_portfolio_breakdown",
            "evidence_id": "KAP-IAT-20260911-001",
        }
    )


def test_legacy_field_value_claim_remains_valid():
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "economic_exposure",
        "value": "sukuk",
    }

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["sources"][0]["claim"]
        == {
            "field": "economic_exposure",
            "value": "sukuk",
        }
    )


@pytest.mark.parametrize(
    "optional_field",
    ["unit", "method", "evidence_id"],
)
def test_enriched_claim_rejects_empty_optional_string(
    optional_field,
):
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "portfolio_weight",
        "value": 35.5,
        optional_field: " ",
    }

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match=f"claim_{optional_field}_must_be_nonempty_string",
    ):
        normalize_candidate_evidence(
            data,
            expected_code="IAT",
        )


def test_enriched_claim_rejects_unknown_field():
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "portfolio_weight",
        "value": 35.5,
        "confidence": 0.95,
    }

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="claim_field_set_mismatch",
    ):
        normalize_candidate_evidence(
            data,
            expected_code="IAT",
        )


def test_enriched_claim_requires_field_and_value():
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "portfolio_weight",
        "unit": "percent",
    }

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="claim_required_field_missing",
    ):
        normalize_candidate_evidence(
            data,
            expected_code="IAT",
        )


def test_same_field_same_unit_different_values_is_contradiction():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-1",
            "observed_fact": "Weight is 35 percent.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 35,
                "unit": "percent",
                "method": "source_a",
                "evidence_id": "E-1",
            },
        },
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-2",
            "observed_fact": "Weight is 40 percent.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 40,
                "unit": "percent",
                "method": "source_b",
                "evidence_id": "E-2",
            },
        },
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "CONTRADICTORY"
    )


def test_equivalent_percent_and_basis_points_are_not_contradictory():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-1",
            "observed_fact": "Weight is 35 percent.",
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
            "observed_fact": "Weight is 3500 basis points.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 3500,
                "unit": "basis_points",
            },
        },
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "SUPPORTED"
    )


def test_method_and_evidence_id_do_not_change_claim_identity():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-1",
            "observed_fact": "Weight is 35 percent.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 35,
                "unit": "percent",
                "method": "method_a",
                "evidence_id": "E-1",
            },
        },
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-2",
            "observed_fact": "Weight is 35 percent.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 35,
                "unit": "percent",
                "method": "method_b",
                "evidence_id": "E-2",
            },
        },
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "SUPPORTED"
    )



@pytest.mark.parametrize(
    "claim_value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_structured_claim_rejects_non_finite_float(
    claim_value,
):
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "portfolio_weight",
        "value": claim_value,
        "unit": "percent",
    }

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="claim_value_must_be_finite",
    ):
        normalize_candidate_evidence(
            data,
            expected_code="IAT",
        )



def test_structured_claim_rejects_unknown_vocabulary_field():
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "weight_pct",
        "value": 35,
        "unit": "percent",
    }

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="claim_unsupported_claim_field:weight_pct",
    ):
        normalize_candidate_evidence(
            data,
            expected_code="IAT",
        )


@pytest.mark.parametrize(
    "unit",
    ["pct", "%", "Percent", "bps"],
)
def test_structured_claim_rejects_noncanonical_unit(unit):
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "portfolio_weight",
        "value": 35,
        "unit": unit,
    }

    with pytest.raises(
        PortfolioFitEvidenceContractError,
        match="claim_unsupported_claim_unit:",
    ):
        normalize_candidate_evidence(
            data,
            expected_code="IAT",
        )


@pytest.mark.parametrize(
    "field",
    [
        "role_fit",
        "economic_overlap",
        "diversification_contribution",
        "concentration_risk",
        "portfolio_weight",
        "economic_exposure",
        "portfolio_role",
        "liquidity_profile",
    ],
)
def test_structured_claim_accepts_canonical_field_vocabulary(field):
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": field,
        "value": "UNKNOWN",
    }

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["sources"][0]["claim"]["field"]
        == field
    )


@pytest.mark.parametrize(
    "unit",
    ["percent", "basis_points"],
)
def test_structured_claim_accepts_canonical_unit_vocabulary(unit):
    data = _evidence()
    source = data["dimensions"]["role_fit"]["sources"][0]
    source["claim"] = {
        "field": "portfolio_weight",
        "value": 35,
        "unit": unit,
    }

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["sources"][0]["claim"]["unit"]
        == unit
    )



def test_percent_and_basis_points_difference_is_contradiction():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-1",
            "observed_fact": "Weight is 35 percent.",
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
            "observed_fact": "Weight is 3600 basis points.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 3600,
                "unit": "basis_points",
            },
        },
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    assert (
        result["dimensions"]["role_fit"]["state"]
        == "CONTRADICTORY"
    )


def test_unit_comparison_does_not_rewrite_evidence_provenance():
    data = _evidence()
    data["dimensions"]["role_fit"]["state"] = "SUPPORTED"
    data["dimensions"]["role_fit"]["sources"] = [
        {
            "source_type": "HUMAN_APPROVED_RESEARCH",
            "source_id": "SRC-1",
            "observed_fact": "Weight is 35 percent.",
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
            "observed_fact": "Weight is 3500 basis points.",
            "as_of": "2026-09-11T18:00:00Z",
            "claim": {
                "field": "portfolio_weight",
                "value": 3500,
                "unit": "basis_points",
            },
        },
    ]

    result = normalize_candidate_evidence(
        data,
        expected_code="IAT",
    )

    claims = [
        source["claim"]
        for source in result["dimensions"]["role_fit"]["sources"]
    ]

    assert claims == [
        {
            "field": "portfolio_weight",
            "value": 35,
            "unit": "percent",
        },
        {
            "field": "portfolio_weight",
            "value": 3500,
            "unit": "basis_points",
        },
    ]
