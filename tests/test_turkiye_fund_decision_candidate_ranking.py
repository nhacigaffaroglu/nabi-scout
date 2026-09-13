import pytest

from services.turkiye_fund_decision_candidate_ranking import (
    DecisionCandidateRankingContractError,
    OUTPUT_SCHEMA,
    OUTPUT_STATUS,
    RANKING_BASIS,
    build_decision_candidate_ranking_artifact,
)


ZERO_WRITE_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "eight_e_calls": 0,
    "new_money_calls": 0,
}


def candidate(
    code,
    *,
    readiness="READY",
    readiness_reasons=None,
    role_fit="STRONG",
    concentration_risk="LOW",
    diversification_contribution="HIGH",
    economic_overlap="LOW",
    fi_score=80.0,
    data_completeness=0.90,
    confidence=0.80,
):
    return {
        "fund_code": code,
        "fund_name": f"{code} Fund",
        "category": "sukuk",
        "fi_score": fi_score,
        "fi_state": "ATTRACTIVE",
        "data_completeness": data_completeness,
        "confidence": confidence,
        "return_1y": 40.0,
        "max_drawdown": -0.10,
        "role_fit": role_fit,
        "economic_overlap": economic_overlap,
        "diversification_contribution":
            diversification_contribution,
        "concentration_risk": concentration_risk,
        "rationale": ["Synthetic test fixture."],
        "evidence": {
            "schema_version":
                "fund18_portfolio_fit_evidence_1",
        },
        "decision_readiness": readiness,
        "decision_readiness_reasons":
            list(readiness_reasons or []),
        "portfolio_fit_composite_score": None,
        "portfolio_fit_rank": None,
        "recommendation": None,
    }


def fund19(rows=None):
    rows = list(
        rows
        if rows is not None
        else [
            candidate("AAA"),
            candidate(
                "BBB",
                readiness="NOT_READY",
                readiness_reasons=[
                    "UNKNOWN_DESCRIPTIVE_DIMENSION:role_fit"
                ],
                role_fit="UNKNOWN",
            ),
        ]
    )

    return {
        "schema_version":
            "fund19_decision_readiness_artifact_1",
        "source": {
            "fund18_schema_version":
                "fund18_portfolio_fit_research_artifact_1",
            "source": {},
        },
        "generated_at": "2026-09-13T13:00:00Z",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "decision_readiness_status":
            "DECISION_READINESS_RESEARCH_COMPLETE",
        "portfolio_fit_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
        "counts": {
            "candidates": len(rows),
            "ready": sum(
                row["decision_readiness"] == "READY"
                for row in rows
            ),
            "not_ready": sum(
                row["decision_readiness"] == "NOT_READY"
                for row in rows
            ),
        },
        "candidates": rows,
        "write_proof": dict(ZERO_WRITE_PROOF),
    }


def build(payload=None):
    return build_decision_candidate_ranking_artifact(
        payload or fund19(),
        generated_at="2026-09-13T14:00:00Z",
    )


def by_code(result):
    return {
        row["fund_code"]: row
        for row in result["candidates"]
    }


def test_builds_research_only_fund20_artifact():
    result = build()

    assert result["schema_version"] == OUTPUT_SCHEMA
    assert result["decision_ranking_status"] == OUTPUT_STATUS

    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["production_persist"] is False

    assert result["decision_ranking_basis"] == list(
        RANKING_BASIS
    )

    assert result["decision_winner"] is None
    assert result["portfolio_fit_composite_score"] is None
    assert result["recommendation"] is None
    assert result["allocation"] is None

    assert result["write_proof"] == ZERO_WRITE_PROOF


def test_only_ready_candidates_are_ranked():
    result = build()
    rows = by_code(result)

    assert rows["AAA"]["decision_ranking_eligible"] is True
    assert rows["AAA"]["decision_rank"] == 1

    assert rows["BBB"]["decision_ranking_eligible"] is False
    assert rows["BBB"]["decision_rank"] is None
    assert rows["BBB"]["decision_ranking_reasons"] == [
        "UNKNOWN_DESCRIPTIVE_DIMENSION:role_fit"
    ]

    assert result["counts"] == {
        "candidates": 2,
        "ready": 1,
        "ranked": 1,
        "not_ready": 1,
    }


def test_role_fit_precedes_fi_score():
    payload = fund19(
        [
            candidate(
                "AAA",
                role_fit="PARTIAL",
                fi_score=99.0,
            ),
            candidate(
                "BBB",
                role_fit="STRONG",
                fi_score=70.0,
            ),
        ]
    )

    result = build(payload)
    rows = by_code(result)

    assert rows["BBB"]["decision_rank"] == 1
    assert rows["AAA"]["decision_rank"] == 2


def test_concentration_risk_precedes_fi_score():
    payload = fund19(
        [
            candidate(
                "AAA",
                concentration_risk="HIGH",
                fi_score=99.0,
            ),
            candidate(
                "BBB",
                concentration_risk="LOW",
                fi_score=70.0,
            ),
        ]
    )

    result = build(payload)
    rows = by_code(result)

    assert rows["BBB"]["decision_rank"] == 1
    assert rows["AAA"]["decision_rank"] == 2


def test_diversification_precedes_fi_score():
    payload = fund19(
        [
            candidate(
                "AAA",
                diversification_contribution="LOW",
                fi_score=99.0,
            ),
            candidate(
                "BBB",
                diversification_contribution="HIGH",
                fi_score=70.0,
            ),
        ]
    )

    result = build(payload)
    rows = by_code(result)

    assert rows["BBB"]["decision_rank"] == 1
    assert rows["AAA"]["decision_rank"] == 2


def test_economic_overlap_precedes_fi_score():
    payload = fund19(
        [
            candidate(
                "AAA",
                economic_overlap="HIGH",
                fi_score=99.0,
            ),
            candidate(
                "BBB",
                economic_overlap="LOW",
                fi_score=70.0,
            ),
        ]
    )

    result = build(payload)
    rows = by_code(result)

    assert rows["BBB"]["decision_rank"] == 1
    assert rows["AAA"]["decision_rank"] == 2


def test_fi_score_breaks_equal_portfolio_fit():
    payload = fund19(
        [
            candidate("AAA", fi_score=70.0),
            candidate("BBB", fi_score=80.0),
        ]
    )

    result = build(payload)
    rows = by_code(result)

    assert rows["BBB"]["decision_rank"] == 1
    assert rows["AAA"]["decision_rank"] == 2


def test_completeness_then_confidence_then_code_tiebreak():
    payload = fund19(
        [
            candidate(
                "DDD",
                fi_score=80.0,
                data_completeness=0.80,
                confidence=0.99,
            ),
            candidate(
                "CCC",
                fi_score=80.0,
                data_completeness=0.90,
                confidence=0.80,
            ),
            candidate(
                "BBB",
                fi_score=80.0,
                data_completeness=0.90,
                confidence=0.90,
            ),
            candidate(
                "AAA",
                fi_score=80.0,
                data_completeness=0.90,
                confidence=0.90,
            ),
        ]
    )

    result = build(payload)
    rows = by_code(result)

    assert rows["AAA"]["decision_rank"] == 1
    assert rows["BBB"]["decision_rank"] == 2
    assert rows["CCC"]["decision_rank"] == 3
    assert rows["DDD"]["decision_rank"] == 4


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "wrong"),
        ("research_only", False),
        ("execution_authority", True),
        ("production_persist", True),
        ("decision_readiness_status", "WRONG"),
        ("portfolio_fit_winner", "AAA"),
        ("portfolio_fit_composite_score", 1.0),
        ("recommendation", "BUY"),
    ],
)
def test_fund19_firewall_fails_closed(field, value):
    payload = fund19()
    payload[field] = value

    with pytest.raises(
        DecisionCandidateRankingContractError
    ):
        build(payload)


def test_nonzero_write_proof_fails_closed():
    payload = fund19()
    payload["write_proof"]["new_money_calls"] = 1

    with pytest.raises(
        DecisionCandidateRankingContractError,
        match="upstream_write_proof_not_zero",
    ):
        build(payload)


def test_duplicate_candidate_fails_closed():
    payload = fund19(
        [
            candidate("AAA"),
            candidate("AAA"),
        ]
    )

    with pytest.raises(
        DecisionCandidateRankingContractError,
        match="duplicate_candidate:AAA",
    ):
        build(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role_fit", "UNKNOWN"),
        ("role_fit", None),
        ("concentration_risk", "UNKNOWN"),
        ("diversification_contribution", "UNKNOWN"),
        ("economic_overlap", "UNKNOWN"),
        ("fi_score", None),
        ("fi_score", float("nan")),
    ],
)
def test_malformed_ready_candidate_fails_closed(
    field,
    value,
):
    row = candidate("AAA")
    row[field] = value

    payload = fund19([row])

    with pytest.raises(
        DecisionCandidateRankingContractError
    ):
        build(payload)


def test_ready_candidate_cannot_have_readiness_reasons():
    row = candidate(
        "AAA",
        readiness_reasons=[
            "UPSTREAM_EVIDENCE_INVALID"
        ],
    )

    payload = fund19([row])

    with pytest.raises(
        DecisionCandidateRankingContractError,
        match="ready_candidate_has_readiness_reasons:AAA",
    ):
        build(payload)


def test_rank_one_is_not_winner_or_execution():
    result = build(
        fund19(
            [
                candidate("AAA", fi_score=90.0),
                candidate("BBB", fi_score=80.0),
            ]
        )
    )

    leader = by_code(result)["AAA"]

    assert leader["decision_rank"] == 1
    assert leader["decision_winner"] is None
    assert leader["recommendation"] is None
    assert leader["allocation"] is None

    forbidden = {
        "trade",
        "order",
        "eight_e_action",
        "new_money_action",
        "buy",
        "sell",
        "target_weight",
        "quantity",
    }

    assert forbidden.isdisjoint(result)
    assert forbidden.isdisjoint(leader)


def test_input_candidate_order_does_not_change_ranking():
    rows = [
        candidate("CCC", fi_score=70.0),
        candidate("AAA", fi_score=90.0),
        candidate("BBB", fi_score=80.0),
    ]

    forward = build(fund19(rows))
    reverse = build(fund19(list(reversed(rows))))

    forward_ranks = {
        row["fund_code"]: row["decision_rank"]
        for row in forward["candidates"]
    }

    reverse_ranks = {
        row["fund_code"]: row["decision_rank"]
        for row in reverse["candidates"]
    }

    assert forward_ranks == reverse_ranks == {
        "AAA": 1,
        "BBB": 2,
        "CCC": 3,
    }


@pytest.mark.parametrize(
    "code",
    [
        "aaa",
        " AAA",
        "AAA ",
        "AA A",
        "AAA!",
        "ABCDEFGHIJKLMNOPQ",
    ],
)
def test_noncanonical_fund_code_fails_closed(code):
    payload = fund19([candidate(code)])

    with pytest.raises(
        DecisionCandidateRankingContractError,
        match="candidate_fund_code_invalid",
    ):
        build(payload)


def test_not_ready_candidate_requires_reason():
    row = candidate(
        "AAA",
        readiness="NOT_READY",
        readiness_reasons=[],
    )

    payload = fund19([row])

    with pytest.raises(
        DecisionCandidateRankingContractError,
        match=(
            "not_ready_candidate_missing_"
            "readiness_reasons:AAA"
        ),
    ):
        build(payload)


@pytest.mark.parametrize(
    "reasons",
    [
        None,
        "reason",
        {"reason": "x"},
    ],
)
def test_readiness_reasons_must_be_sequence(reasons):
    row = candidate("AAA")
    row["decision_readiness_reasons"] = reasons

    payload = fund19([row])

    with pytest.raises(
        DecisionCandidateRankingContractError,
        match="candidate_readiness_reasons_invalid:AAA",
    ):
        build(payload)
