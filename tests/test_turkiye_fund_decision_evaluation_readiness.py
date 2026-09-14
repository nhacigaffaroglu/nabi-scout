from __future__ import annotations

import copy

import pytest

from services.turkiye_fund_decision_evaluation_readiness import (
    DecisionEvaluationReadinessContractError,
    EVAL_NOT_READY,
    EVAL_READY,
    INPUT_SCHEMA,
    INPUT_STATUS,
    OUTPUT_SCHEMA,
    OUTPUT_STATUS,
    ZERO_WRITE_PROOF,
    build_decision_evaluation_readiness_artifact,
)


def candidate(
    code: str,
    *,
    rank: int | None,
    ranking_eligible: bool,
    readiness: str = "READY",
    readiness_reasons=(),
    role_fit: str = "STRONG",
    concentration_risk: str = "LOW",
    diversification_contribution: str = "HIGH",
    economic_overlap: str = "LOW",
    fi_score: float = 80.0,
):
    return {
        "fund_code": code,
        "decision_readiness": readiness,
        "decision_readiness_reasons": list(readiness_reasons),
        "decision_rank": rank,
        "decision_ranking_eligible": ranking_eligible,
        "role_fit": role_fit,
        "concentration_risk": concentration_risk,
        "diversification_contribution": diversification_contribution,
        "economic_overlap": economic_overlap,
        "fi_score": fi_score,
        "data_completeness": 95.0,
        "confidence": 90.0,
    }


def artifact(*rows):
    return {
        "schema_version": INPUT_SCHEMA,
        "decision_candidate_ranking_status": INPUT_STATUS,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "decision_winner": None,
        "recommendation": None,
        "allocation": None,
        "candidates": list(rows),
        "write_proof": dict(ZERO_WRITE_PROOF),
    }



def test_canonical_decision_ranking_status_is_accepted():
    payload = artifact(candidate("AAA", rank=1, ranking_eligible=True))
    payload["decision_ranking_status"] = INPUT_STATUS
    payload.pop("decision_candidate_ranking_status")

    result = build_decision_evaluation_readiness_artifact(payload)

    assert result["decision_evaluation_readiness_status"] == OUTPUT_STATUS


def test_legacy_decision_candidate_ranking_status_remains_accepted():
    payload = artifact(candidate("AAA", rank=1, ranking_eligible=True))

    result = build_decision_evaluation_readiness_artifact(payload)

    assert result["decision_evaluation_readiness_status"] == OUTPUT_STATUS


def test_canonical_status_takes_precedence_over_legacy_status():
    payload = artifact(candidate("AAA", rank=1, ranking_eligible=True))
    payload["decision_ranking_status"] = "wrong"

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="upstream_fund20_status_invalid",
    ):
        build_decision_evaluation_readiness_artifact(payload)


def test_ready_ranked_candidate_advances_without_decision_authority():
    result = build_decision_evaluation_readiness_artifact(
        artifact(
            candidate("AAA", rank=1, ranking_eligible=True),
            candidate(
                "BBB",
                rank=None,
                ranking_eligible=False,
                readiness="NOT_READY",
                readiness_reasons=("FI_INSUFFICIENT_DATA",),
            ),
        ),
        generated_at="2026-09-13T00:00:00+00:00",
    )

    assert result["schema_version"] == OUTPUT_SCHEMA
    assert result["source_schema_version"] == INPUT_SCHEMA
    assert result["decision_evaluation_readiness_status"] == OUTPUT_STATUS
    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["production_persist"] is False
    assert result["decision_winner"] is None
    assert result["recommendation"] is None
    assert result["allocation"] is None
    assert result["write_proof"] == ZERO_WRITE_PROOF

    aaa, bbb = result["candidates"]

    assert aaa["decision_evaluation_readiness"] == EVAL_READY
    assert aaa["decision_evaluation_eligible"] is True
    assert aaa["decision_evaluation_reasons"] == []
    assert aaa["decision_evaluation_source_rank"] == 1

    assert bbb["decision_evaluation_readiness"] == EVAL_NOT_READY
    assert bbb["decision_evaluation_eligible"] is False
    assert "UPSTREAM_NOT_RANKING_ELIGIBLE" in bbb["decision_evaluation_reasons"]

    for row in result["candidates"]:
        assert row["decision_action"] is None
        assert row["decision_winner"] is None
        assert row["recommendation"] is None
        assert row["allocation"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "wrong"),
        ("decision_candidate_ranking_status", "wrong"),
        ("research_only", False),
        ("execution_authority", True),
        ("production_persist", True),
        ("decision_winner", "AAA"),
        ("recommendation", "BUY"),
        ("allocation", {"AAA": 1}),
    ],
)
def test_top_level_firewall_fails_closed(field, value):
    payload = artifact(candidate("AAA", rank=1, ranking_eligible=True))
    payload[field] = value

    with pytest.raises(DecisionEvaluationReadinessContractError):
        build_decision_evaluation_readiness_artifact(payload)


def test_nonzero_write_proof_fails_closed():
    payload = artifact(candidate("AAA", rank=1, ranking_eligible=True))
    payload["write_proof"]["eight_e_calls"] = 1

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="upstream_write_proof_not_zero",
    ):
        build_decision_evaluation_readiness_artifact(payload)


def test_duplicate_fund_code_fails_closed():
    payload = artifact(
        candidate("AAA", rank=1, ranking_eligible=True),
        candidate("AAA", rank=2, ranking_eligible=True),
    )

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="duplicate_candidate",
    ):
        build_decision_evaluation_readiness_artifact(payload)


@pytest.mark.parametrize(
    "bad_code",
    [
        "aaa",
        " AAA",
        "AAA ",
        "AA A",
        "AAA!",
        "ABCDEFGHIJKLMNOPQ",
    ],
)
def test_noncanonical_fund_code_fails_closed(bad_code):
    payload = artifact(
        candidate(bad_code, rank=1, ranking_eligible=True),
    )

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="candidate_fund_code_invalid",
    ):
        build_decision_evaluation_readiness_artifact(payload)


def test_rank_sequence_must_be_contiguous():
    payload = artifact(
        candidate("AAA", rank=1, ranking_eligible=True),
        candidate("BBB", rank=3, ranking_eligible=True),
    )

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="decision_rank_sequence_invalid",
    ):
        build_decision_evaluation_readiness_artifact(payload)


def test_duplicate_rank_fails_closed():
    payload = artifact(
        candidate("AAA", rank=1, ranking_eligible=True),
        candidate("BBB", rank=1, ranking_eligible=True),
    )

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="duplicate_decision_rank",
    ):
        build_decision_evaluation_readiness_artifact(payload)


def test_ineligible_candidate_cannot_have_rank():
    payload = artifact(
        candidate("AAA", rank=1, ranking_eligible=True),
        candidate(
            "BBB",
            rank=2,
            ranking_eligible=False,
            readiness="NOT_READY",
            readiness_reasons=("X",),
        ),
    )

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="ineligible_candidate_has_decision_rank",
    ):
        build_decision_evaluation_readiness_artifact(payload)


@pytest.mark.parametrize(
    "changes,expected_reason",
    [
        ({"decision_readiness": "NOT_READY"}, "UPSTREAM_READINESS_NOT_READY"),
        (
            {"decision_readiness_reasons": ["SOME_REASON"]},
            "UPSTREAM_READINESS_REASONS_PRESENT",
        ),
        ({"role_fit": "UNKNOWN"}, "ROLE_FIT_INVALID"),
        ({"concentration_risk": "UNKNOWN"}, "CONCENTRATION_RISK_INVALID"),
        (
            {"diversification_contribution": "UNKNOWN"},
            "DIVERSIFICATION_CONTRIBUTION_INVALID",
        ),
        ({"economic_overlap": "UNKNOWN"}, "ECONOMIC_OVERLAP_INVALID"),
        ({"fi_score": None}, "FI_SCORE_INVALID"),
        ({"fi_score": float("nan")}, "FI_SCORE_INVALID"),
    ],
)
def test_ranked_candidate_with_bad_upstream_evidence_is_not_ready(
    changes,
    expected_reason,
):
    row = candidate("AAA", rank=1, ranking_eligible=True)
    row.update(changes)

    result = build_decision_evaluation_readiness_artifact(
        artifact(row)
    )

    out = result["candidates"][0]
    assert out["decision_evaluation_readiness"] == EVAL_NOT_READY
    assert out["decision_evaluation_eligible"] is False
    assert expected_reason in out["decision_evaluation_reasons"]


def test_fund21_preserves_fund20_rank_and_input_order():
    payload = artifact(
        candidate("BBB", rank=2, ranking_eligible=True),
        candidate("AAA", rank=1, ranking_eligible=True),
    )

    result = build_decision_evaluation_readiness_artifact(payload)

    assert [row["fund_code"] for row in result["candidates"]] == [
        "BBB",
        "AAA",
    ]
    assert [
        row["decision_evaluation_source_rank"]
        for row in result["candidates"]
    ] == [2, 1]


def test_no_execution_or_allocation_fields_are_created():
    result = build_decision_evaluation_readiness_artifact(
        artifact(candidate("AAA", rank=1, ranking_eligible=True))
    )
    row = result["candidates"][0]

    forbidden = {
        "trade",
        "order",
        "buy",
        "sell",
        "quantity",
        "target_weight",
        "position_size",
        "eight_e_action",
        "new_money_action",
    }

    assert forbidden.isdisjoint(row)
    assert result["write_proof"] == ZERO_WRITE_PROOF


def test_input_is_not_mutated():
    payload = artifact(
        candidate("AAA", rank=1, ranking_eligible=True)
    )
    before = copy.deepcopy(payload)

    build_decision_evaluation_readiness_artifact(payload)

    assert payload == before


@pytest.mark.parametrize("bad_value", [None, "true", 1, 0])
def test_ranking_eligible_must_be_real_boolean(bad_value):
    row = candidate("AAA", rank=1, ranking_eligible=True)
    row["decision_ranking_eligible"] = bad_value

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="decision_ranking_eligible_must_be_boolean",
    ):
        build_decision_evaluation_readiness_artifact(
            artifact(row)
        )


@pytest.mark.parametrize("bad_rank", [None, 0, -1, True, 1.5, "1"])
def test_eligible_candidate_rank_must_be_positive_integer(bad_rank):
    row = candidate("AAA", rank=1, ranking_eligible=True)
    row["decision_rank"] = bad_rank

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="eligible_candidate_decision_rank_invalid",
    ):
        build_decision_evaluation_readiness_artifact(
            artifact(row)
        )


@pytest.mark.parametrize(
    "bad_reasons",
    [
        "SOME_REASON",
        {"reason": "SOME_REASON"},
        123,
        None,
    ],
)
def test_decision_readiness_reasons_must_be_sequence(bad_reasons):
    row = candidate("AAA", rank=1, ranking_eligible=True)
    row["decision_readiness_reasons"] = bad_reasons

    with pytest.raises(
        DecisionEvaluationReadinessContractError,
        match="decision_readiness_reasons_must_be_sequence",
    ):
        build_decision_evaluation_readiness_artifact(
            artifact(row)
        )


def test_all_ranked_ready_candidates_can_advance_without_reranking():
    result = build_decision_evaluation_readiness_artifact(
        artifact(
            candidate(
                "AAA",
                rank=1,
                ranking_eligible=True,
                role_fit="STRONG",
                fi_score=70.0,
            ),
            candidate(
                "BBB",
                rank=2,
                ranking_eligible=True,
                role_fit="PARTIAL",
                fi_score=99.0,
            ),
        )
    )

    rows = result["candidates"]

    assert result["counts"] == {
        "candidates": 2,
        "ready_for_decision_evaluation": 2,
        "not_ready_for_decision_evaluation": 0,
    }

    assert [row["decision_evaluation_source_rank"] for row in rows] == [1, 2]
    assert all(
        row["decision_evaluation_readiness"] == EVAL_READY
        for row in rows
    )

    # FUND21 is a readiness gate, not a winner-selection stage.
    assert result["decision_winner"] is None
    assert all(row["decision_winner"] is None for row in rows)


def test_not_ready_candidate_remains_unranked_and_cannot_advance():
    result = build_decision_evaluation_readiness_artifact(
        artifact(
            candidate("AAA", rank=1, ranking_eligible=True),
            candidate(
                "BBB",
                rank=None,
                ranking_eligible=False,
                readiness="NOT_READY",
                readiness_reasons=("FI_INSUFFICIENT_DATA",),
            ),
        )
    )

    bbb = next(
        row for row in result["candidates"]
        if row["fund_code"] == "BBB"
    )

    assert bbb["decision_rank"] is None
    assert bbb["decision_evaluation_source_rank"] is None
    assert bbb["decision_evaluation_eligible"] is False
    assert (
        bbb["decision_evaluation_readiness"]
        == EVAL_NOT_READY
    )


def test_fund21_output_has_exact_zero_write_proof():
    result = build_decision_evaluation_readiness_artifact(
        artifact(candidate("AAA", rank=1, ranking_eligible=True))
    )

    assert result["write_proof"] == {
        "production_writes": 0,
        "trade_actions": 0,
        "orders": 0,
        "portfolio_writes": 0,
        "eight_e_calls": 0,
        "new_money_calls": 0,
    }


def test_ready_for_decision_evaluation_is_not_an_investment_action():
    result = build_decision_evaluation_readiness_artifact(
        artifact(candidate("AAA", rank=1, ranking_eligible=True))
    )

    row = result["candidates"][0]

    assert row["decision_evaluation_readiness"] == EVAL_READY
    assert row["decision_action"] is None
    assert row["recommendation"] is None
    assert row["allocation"] is None

    forbidden_values = {
        "BUY",
        "SELL",
        "ADD",
        "CONSIDER_NEW_POSITION",
        "CONSIDER_TOP_UP",
        "HOLD",
        "REDUCE",
        "AVOID",
    }

    assert row["decision_evaluation_readiness"] not in forbidden_values
