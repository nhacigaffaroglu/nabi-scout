from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from services.portfolio_security_decision_contract import (
    DECISION_CONSIDER_NEW_POSITION,
)
from services.turkiye_fund_canonical_decision_integration import (
    INPUT_SCHEMA,
    INPUT_STATUS,
    OUTPUT_SCHEMA,
    OUTPUT_STATUS,
    STATE_BLOCKED,
    STATE_EVALUATED,
    STATE_NOT_ELIGIBLE,
    ZERO_WRITE_PROOF,
    CanonicalDecisionIntegrationContractError,
    build_canonical_decision_integration_artifact,
)
from services.turkiye_fund_snapshot_reader import SnapshotReadError


def _candidate(
    code: str,
    *,
    eligible: bool = True,
    rank: int | None = 1,
) -> dict:
    return {
        "fund_code": code,
        "decision_readiness": "READY" if eligible else "NOT_READY",
        "decision_readiness_reasons": [] if eligible else ["UPSTREAM_BLOCKED"],
        "decision_rank": rank if eligible else None,
        "decision_ranking_eligible": eligible,
        "decision_evaluation_readiness": (
            "READY_FOR_DECISION_EVALUATION"
            if eligible
            else "NOT_READY_FOR_DECISION_EVALUATION"
        ),
        "decision_evaluation_eligible": eligible,
        "decision_evaluation_reasons": [] if eligible else ["UPSTREAM_NOT_RANKING_ELIGIBLE"],
        "decision_evaluation_source_rank": rank if eligible else None,
        "decision_action": None,
        "decision_winner": None,
        "recommendation": None,
        "allocation": None,
    }


def _artifact(candidates: list[dict]) -> dict:
    return {
        "schema_version": INPUT_SCHEMA,
        "source_schema_version": "fund20_decision_candidate_ranking_artifact_1",
        "generated_at": "2026-09-13T00:00:00+00:00",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "decision_evaluation_readiness_status": INPUT_STATUS,
        "decision_winner": None,
        "recommendation": None,
        "allocation": None,
        "counts": {
            "candidates": len(candidates),
            "ready_for_decision_evaluation": sum(
                1 for row in candidates if row["decision_evaluation_eligible"]
            ),
            "not_ready_for_decision_evaluation": sum(
                1 for row in candidates if not row["decision_evaluation_eligible"]
            ),
        },
        "candidates": candidates,
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
        },
    }


class _Decision:
    def __init__(self, code: str):
        self.code = code

    def to_dict(self) -> dict:
        return {
            "symbol": "AAA",
            "decision": self.code,
            "confidence": "HIGH",
            "exposure_increase_allowed": True,
            "participation_status": "Uygun",
            "research_allowed": True,
            "security_intelligence_state": "ATTRACTIVE",
            "security_intelligence_score": 82.5,
            "security_intelligence_confidence": 0.91,
            "security_intelligence_data_quality": "HIGH",
            "security_intelligence_as_of": "2026-09-13T00:00:00+00:00",
            "primary_reasons": ["ELIGIBLE_TO_INCREASE"],
            "blocking_reasons": [],
            "risk_flags": [],
            "reason_codes": ["ELIGIBLE_TO_INCREASE"],
            "as_of": "2026-09-13T00:00:00+00:00",
            "engine_version": "portfolio_security_decision_8e.1",
            "research_status": None,
        }


def _canonical(code: str, decision: str = DECISION_CONSIDER_NEW_POSITION):
    return SimpleNamespace(
        fund_code=code,
        participation=SimpleNamespace(
            row_id="p1",
            methodology_id="turkiye_fund_participation",
            methodology_version="1",
            semantic_identity=f"{code}:participation",
        ),
        fund_intelligence=SimpleNamespace(
            row_id="fi1",
            as_of_key="2026-09-13",
            facts_version="fund_facts_1",
            engine_version="fund_eval_1",
        ),
        decision=_Decision(decision),
    )


def test_ready_candidate_is_evaluated_and_rank_preserved(monkeypatch):
    payload = _artifact([_candidate("AAA", eligible=True, rank=1)])

    seen = {}

    def fake_read(**kwargs):
        seen.update(kwargs)
        return _canonical("AAA")

    monkeypatch.setattr(
        "services.turkiye_fund_canonical_decision_integration.read_turkiye_fund_canonical",
        fake_read,
    )

    result = build_canonical_decision_integration_artifact(
        payload,
        participation_repo=object(),
        snapshot_repo=object(),
        portfolio_contexts={"AAA": {"is_holding": False}},
    )

    assert result["schema_version"] == OUTPUT_SCHEMA
    assert result["canonical_decision_integration_status"] == OUTPUT_STATUS
    assert result["counts"]["canonical_decisions_evaluated"] == 1
    assert result["write_proof"] == ZERO_WRITE_PROOF

    row = result["candidates"][0]
    assert row["canonical_decision_integration_state"] == STATE_EVALUATED
    assert row["canonical_decision"] == DECISION_CONSIDER_NEW_POSITION
    assert row["canonical_decision_source_rank"] == 1
    assert row["decision_rank"] == 1
    assert row["decision_evaluation_source_rank"] == 1
    assert row["decision_winner"] is None
    assert row["recommendation"] is None
    assert row["allocation"] is None

    assert seen["fund_code"] == "AAA"
    assert seen["is_holding"] is False
    assert seen["portfolio_weight"] is None


def test_not_eligible_candidate_never_calls_canonical_reader(monkeypatch):
    payload = _artifact([_candidate("BBB", eligible=False, rank=None)])

    def fail_read(**_kwargs):
        raise AssertionError("canonical reader must not be called")

    monkeypatch.setattr(
        "services.turkiye_fund_canonical_decision_integration.read_turkiye_fund_canonical",
        fail_read,
    )

    result = build_canonical_decision_integration_artifact(
        payload,
        participation_repo=object(),
        snapshot_repo=object(),
    )

    row = result["candidates"][0]
    assert row["canonical_decision_integration_state"] == STATE_NOT_ELIGIBLE
    assert row["canonical_decision"] is None
    assert row["canonical_decision_payload"] is None
    assert result["counts"]["not_eligible_for_canonical_decision"] == 1


def test_snapshot_failure_is_fail_closed(monkeypatch):
    payload = _artifact([_candidate("AAA", eligible=True, rank=1)])

    def blocked(**_kwargs):
        raise SnapshotReadError("STALE_FI_SNAPSHOT", fund_code="AAA")

    monkeypatch.setattr(
        "services.turkiye_fund_canonical_decision_integration.read_turkiye_fund_canonical",
        blocked,
    )

    result = build_canonical_decision_integration_artifact(
        payload,
        participation_repo=object(),
        snapshot_repo=object(),
        portfolio_contexts={"AAA": {"is_holding": False}},
    )

    row = result["candidates"][0]
    assert row["canonical_decision_integration_state"] == STATE_BLOCKED
    assert row["canonical_decision"] is None
    assert row["canonical_decision_payload"] is None
    assert row["canonical_decision_reasons"] == [
        "CANONICAL_SNAPSHOT_BLOCKED",
        "STALE_FI_SNAPSHOT",
    ]
    assert result["counts"]["canonical_inputs_blocked"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "wrong"),
        ("decision_evaluation_readiness_status", "wrong"),
        ("research_only", False),
        ("execution_authority", True),
        ("production_persist", True),
        ("decision_winner", "AAA"),
        ("recommendation", {}),
        ("allocation", {}),
    ],
)
def test_top_level_firewall(field, value):
    payload = _artifact([_candidate("AAA")])
    payload[field] = value

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            payload,
            participation_repo=object(),
            snapshot_repo=object(),
        )


def test_nonzero_upstream_write_proof_fails_closed():
    payload = _artifact([_candidate("AAA")])
    payload["write_proof"]["portfolio_writes"] = 1

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            payload,
            participation_repo=object(),
            snapshot_repo=object(),
        )


def test_write_proof_shape_must_be_exact():
    payload = _artifact([_candidate("AAA")])
    payload["write_proof"]["unexpected"] = 0

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            payload,
            participation_repo=object(),
            snapshot_repo=object(),
        )


def test_duplicate_candidate_fails_closed():
    payload = _artifact([
        _candidate("AAA", rank=1),
        _candidate("AAA", rank=2),
    ])

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            payload,
            participation_repo=object(),
            snapshot_repo=object(),
        )


@pytest.mark.parametrize(
    "code",
    [
        "aaa",
        " AAA",
        "AAA ",
        "AA A",
        "!AAA",
        "ABCDEFGHIJKLMNOPQ",
    ],
)
def test_noncanonical_fund_code_rejected(code):
    payload = _artifact([_candidate(code)])

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            payload,
            participation_repo=object(),
            snapshot_repo=object(),
        )


@pytest.mark.parametrize("bad", [None, "true", 1, 0])
def test_decision_evaluation_eligible_must_be_bool(bad):
    row = _candidate("AAA")
    row["decision_evaluation_eligible"] = bad
    payload = _artifact([row])

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            payload,
            participation_repo=object(),
            snapshot_repo=object(),
        )


def test_eligible_candidate_requires_ready_state():
    row = _candidate("AAA")
    row["decision_evaluation_readiness"] = "NOT_READY_FOR_DECISION_EVALUATION"

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            _artifact([row]),
            participation_repo=object(),
            snapshot_repo=object(),
        )


@pytest.mark.parametrize("rank", [None, 0, -1, True, 1.5, "1"])
def test_eligible_candidate_source_rank_must_be_positive_int(rank):
    row = _candidate("AAA")
    row["decision_evaluation_source_rank"] = rank

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            _artifact([row]),
            participation_repo=object(),
            snapshot_repo=object(),
        )


def test_rank_provenance_mismatch_fails_closed():
    row = _candidate("AAA", rank=1)
    row["decision_rank"] = 2

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            _artifact([row]),
            participation_repo=object(),
            snapshot_repo=object(),
        )


def test_portfolio_holding_context_is_forwarded(monkeypatch):
    payload = _artifact([_candidate("AAA")])
    seen = {}

    def fake_read(**kwargs):
        seen.update(kwargs)
        return _canonical("AAA")

    monkeypatch.setattr(
        "services.turkiye_fund_canonical_decision_integration.read_turkiye_fund_canonical",
        fake_read,
    )

    build_canonical_decision_integration_artifact(
        payload,
        participation_repo=object(),
        snapshot_repo=object(),
        portfolio_contexts={
            "AAA": {
                "is_holding": True,
                "portfolio_weight": 4.25,
            }
        },
    )

    assert seen["is_holding"] is True
    assert seen["portfolio_weight"] == 4.25


@pytest.mark.parametrize(
    "ctx",
    [
        {"is_holding": "yes"},
        {"is_holding": False, "portfolio_weight": 1.0},
        {"is_holding": True, "portfolio_weight": "bad"},
        {"is_holding": True, "portfolio_weight": -1},
        {"is_holding": True, "portfolio_weight": 101},
        {"is_holding": True, "portfolio_weight": 1, "extra": 1},
    ],
)
def test_invalid_portfolio_context_fails_closed(ctx):
    payload = _artifact([_candidate("AAA")])

    with pytest.raises(CanonicalDecisionIntegrationContractError):
        build_canonical_decision_integration_artifact(
            payload,
            participation_repo=object(),
            snapshot_repo=object(),
            portfolio_contexts={"AAA": ctx},
        )


def test_input_is_not_mutated(monkeypatch):
    payload = _artifact([_candidate("AAA")])
    before = repr(payload)

    monkeypatch.setattr(
        "services.turkiye_fund_canonical_decision_integration.read_turkiye_fund_canonical",
        lambda **_kwargs: _canonical("AAA"),
    )

    build_canonical_decision_integration_artifact(
        payload,
        participation_repo=object(),
        snapshot_repo=object(),
        portfolio_contexts={"AAA": {"is_holding": False}},
    )

    assert repr(payload) == before


def test_output_has_no_recommendation_allocation_or_winner_authority(monkeypatch):
    payload = _artifact([_candidate("AAA")])

    monkeypatch.setattr(
        "services.turkiye_fund_canonical_decision_integration.read_turkiye_fund_canonical",
        lambda **_kwargs: _canonical("AAA"),
    )

    result = build_canonical_decision_integration_artifact(
        payload,
        participation_repo=object(),
        snapshot_repo=object(),
        portfolio_contexts={"AAA": {"is_holding": False}},
    )

    assert result["decision_winner"] is None
    assert result["recommendation"] is None
    assert result["allocation"] is None
    assert result["execution_authority"] is False
    assert result["production_persist"] is False
    assert result["research_only"] is True


def test_multiple_candidates_preserve_input_order_and_rank(monkeypatch):
    payload = _artifact([
        _candidate("BBB", rank=2),
        _candidate("AAA", rank=1),
    ])

    monkeypatch.setattr(
        "services.turkiye_fund_canonical_decision_integration.read_turkiye_fund_canonical",
        lambda fund_code, **_kwargs: _canonical(fund_code),
    )

    result = build_canonical_decision_integration_artifact(
        payload,
        participation_repo=object(),
        snapshot_repo=object(),
        portfolio_contexts={
            "BBB": {"is_holding": False},
            "AAA": {"is_holding": False},
        },
    )

    assert [row["fund_code"] for row in result["candidates"]] == ["BBB", "AAA"]
    assert [
        row["canonical_decision_source_rank"]
        for row in result["candidates"]
    ] == [2, 1]


def test_ready_candidate_requires_explicit_portfolio_context():
    payload = _artifact([_candidate("AAA")])

    with pytest.raises(
        CanonicalDecisionIntegrationContractError,
        match="portfolio_context_missing:AAA",
    ):
        build_canonical_decision_integration_artifact(
            payload,
            participation_repo=object(),
            snapshot_repo=object(),
        )


def test_ready_candidate_requires_explicit_is_holding():
    payload = _artifact([_candidate("AAA")])

    with pytest.raises(
        CanonicalDecisionIntegrationContractError,
        match="portfolio_context_is_holding_missing:AAA",
    ):
        build_canonical_decision_integration_artifact(
            payload,
            participation_repo=object(),
            snapshot_repo=object(),
            portfolio_contexts={"AAA": {}},
        )
