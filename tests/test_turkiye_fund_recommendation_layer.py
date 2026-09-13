from __future__ import annotations

import copy
import unittest

from services.portfolio_security_decision_contract import (
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_WATCH,
)
from services.turkiye_fund_recommendation_layer import (
    FundRecommendationLayerContractError,
    INPUT_SCHEMA,
    INPUT_STATUS,
    OUTPUT_SCHEMA,
    OUTPUT_STATUS,
    STATE_BLOCKED,
    STATE_NOT_ELIGIBLE,
    STATE_READY,
    ZERO_WRITE_PROOF,
    build_fund_recommendation_layer_artifact,
)


def _candidate(
    *,
    code: str = "AAA",
    state: str = "CANONICAL_DECISION_EVALUATED",
    decision: str | None = DECISION_CONSIDER_NEW_POSITION,
    rank: int = 1,
) -> dict:
    payload = None
    reasons = []
    provenance = None

    if state == "CANONICAL_DECISION_EVALUATED":
        payload = {
            "symbol": code,
            "decision": decision,
            "confidence": "HIGH",
            "reason_codes": ["ELIGIBLE_TO_INCREASE"],
        }
        reasons = ["ELIGIBLE_TO_INCREASE"]
        provenance = {
            "participation_row_id": "p-1",
            "participation_methodology_id": "m-1",
            "participation_methodology_version": "v1",
            "participation_semantic_identity": "sem-1",
            "fi_row_id": "fi-1",
            "fi_as_of_key": "2026-09-13",
            "fi_facts_version": "facts-v1",
            "fi_engine_version": "engine-v1",
        }

    return {
        "fund_code": code,
        "decision_rank": rank,
        "decision_evaluation_source_rank": rank,
        "canonical_decision_source_rank": rank,
        "canonical_decision_integration_state": state,
        "canonical_decision": decision,
        "canonical_decision_payload": payload,
        "canonical_decision_reasons": reasons,
        "canonical_snapshot_provenance": provenance,
        "decision_winner": None,
        "recommendation": None,
        "allocation": None,
    }


def _artifact(candidates=None) -> dict:
    if candidates is None:
        candidates = [_candidate()]

    return {
        "schema_version": INPUT_SCHEMA,
        "source_schema_version": "fund21_decision_evaluation_readiness_artifact_1",
        "generated_at": "2026-09-13T12:00:00+00:00",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "canonical_decision_integration_status": INPUT_STATUS,
        "decision_winner": None,
        "recommendation": None,
        "allocation": None,
        "counts": {},
        "candidates": candidates,
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_persistence_writes": 0,
            "new_money_calls": 0,
        },
    }


class Fund23RecommendationLayerTests(unittest.TestCase):
    def test_ready_candidate_projects_canonical_decision_without_override(self) -> None:
        result = build_fund_recommendation_layer_artifact(
            _artifact(
                [
                    _candidate(
                        decision=DECISION_CONSIDER_NEW_POSITION,
                    )
                ]
            ),
            generated_at="2026-09-13T13:00:00+00:00",
        )

        self.assertEqual(result["schema_version"], OUTPUT_SCHEMA)
        self.assertEqual(result["recommendation_layer_status"], OUTPUT_STATUS)

        row = result["candidates"][0]
        self.assertEqual(row["recommendation_state"], STATE_READY)
        self.assertEqual(
            row["recommendation_action"],
            DECISION_CONSIDER_NEW_POSITION,
        )
        self.assertEqual(
            row["recommendation_source"],
            "CANONICAL_8E_DECISION",
        )
        self.assertEqual(row["recommendation_source_rank"], 1)

    def test_each_canonical_decision_is_preserved_verbatim(self) -> None:
        decisions = (
            DECISION_CONSIDER_NEW_POSITION,
            DECISION_CONSIDER_TOP_UP,
            DECISION_HOLD,
            DECISION_WATCH,
        )

        for index, decision in enumerate(decisions, start=1):
            with self.subTest(decision=decision):
                result = build_fund_recommendation_layer_artifact(
                    _artifact(
                        [
                            _candidate(
                                code=f"F{index}",
                                decision=decision,
                                rank=index,
                            )
                        ]
                    )
                )
                row = result["candidates"][0]
                self.assertEqual(row["recommendation_action"], decision)

    def test_blocked_candidate_never_gets_recommendation_action(self) -> None:
        row = _candidate(
            state="CANONICAL_DECISION_INPUT_BLOCKED",
            decision=None,
        )
        row["canonical_decision_reasons"] = [
            "CANONICAL_SNAPSHOT_BLOCKED",
            "FI_STALE",
        ]

        result = build_fund_recommendation_layer_artifact(
            _artifact([row])
        )

        out = result["candidates"][0]
        self.assertEqual(out["recommendation_state"], STATE_BLOCKED)
        self.assertIsNone(out["recommendation_action"])
        self.assertIn(
            "UPSTREAM_CANONICAL_DECISION_BLOCKED",
            out["recommendation_reasons"],
        )

    def test_not_eligible_candidate_never_gets_recommendation_action(self) -> None:
        row = _candidate(
            state="NOT_ELIGIBLE_FOR_CANONICAL_DECISION",
            decision=None,
        )

        result = build_fund_recommendation_layer_artifact(
            _artifact([row])
        )

        out = result["candidates"][0]
        self.assertEqual(
            out["recommendation_state"],
            STATE_NOT_ELIGIBLE,
        )
        self.assertIsNone(out["recommendation_action"])

    def test_top_level_research_firewall_is_zero_authority(self) -> None:
        result = build_fund_recommendation_layer_artifact(
            _artifact()
        )

        self.assertIs(result["research_only"], True)
        self.assertIs(result["execution_authority"], False)
        self.assertIs(result["production_persist"], False)

        self.assertIsNone(result["decision_winner"])
        self.assertIsNone(result["recommended_symbol"])
        self.assertIsNone(result["allocation"])
        self.assertIsNone(result["target_weight"])
        self.assertIsNone(result["quantity"])
        self.assertIsNone(result["trade"])
        self.assertIsNone(result["order"])

        self.assertEqual(result["write_proof"], ZERO_WRITE_PROOF)

    def test_candidate_execution_fields_are_always_none(self) -> None:
        result = build_fund_recommendation_layer_artifact(
            _artifact()
        )
        row = result["candidates"][0]

        for field in (
            "recommended_symbol",
            "decision_winner",
            "allocation",
            "target_weight",
            "quantity",
            "trade",
            "order",
        ):
            self.assertIsNone(row[field])

    def test_rank_provenance_is_preserved_and_no_rerank_occurs(self) -> None:
        candidates = [
            _candidate(code="BBB", rank=2),
            _candidate(code="AAA", rank=1),
        ]

        result = build_fund_recommendation_layer_artifact(
            _artifact(candidates)
        )

        self.assertEqual(
            [row["fund_code"] for row in result["candidates"]],
            ["BBB", "AAA"],
        )
        self.assertEqual(
            [
                row["recommendation_source_rank"]
                for row in result["candidates"]
            ],
            [2, 1],
        )

    def test_rank_provenance_mismatch_fails_closed(self) -> None:
        row = _candidate()
        row["decision_rank"] = 2

        with self.assertRaisesRegex(
            FundRecommendationLayerContractError,
            "recommendation_rank_provenance_mismatch",
        ):
            build_fund_recommendation_layer_artifact(
                _artifact([row])
            )

    def test_invalid_canonical_decision_fails_closed(self) -> None:
        row = _candidate(decision="BUY")
        row["canonical_decision_payload"]["decision"] = "BUY"

        with self.assertRaisesRegex(
            FundRecommendationLayerContractError,
            "canonical_decision_invalid",
        ):
            build_fund_recommendation_layer_artifact(
                _artifact([row])
            )

    def test_payload_decision_mismatch_fails_closed(self) -> None:
        row = _candidate(
            decision=DECISION_CONSIDER_NEW_POSITION
        )
        row["canonical_decision_payload"]["decision"] = DECISION_HOLD

        with self.assertRaisesRegex(
            FundRecommendationLayerContractError,
            "canonical_decision_payload_mismatch",
        ):
            build_fund_recommendation_layer_artifact(
                _artifact([row])
            )

    def test_missing_snapshot_provenance_fails_closed(self) -> None:
        row = _candidate()
        row["canonical_snapshot_provenance"] = None

        with self.assertRaisesRegex(
            FundRecommendationLayerContractError,
            "canonical_snapshot_provenance_missing",
        ):
            build_fund_recommendation_layer_artifact(
                _artifact([row])
            )

    def test_duplicate_candidate_code_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            FundRecommendationLayerContractError,
            "duplicate_candidate:AAA",
        ):
            build_fund_recommendation_layer_artifact(
                _artifact(
                    [
                        _candidate(code="AAA", rank=1),
                        _candidate(code="AAA", rank=2),
                    ]
                )
            )

    def test_upstream_schema_must_match_fund22(self) -> None:
        artifact = _artifact()
        artifact["schema_version"] = "wrong"

        with self.assertRaisesRegex(
            FundRecommendationLayerContractError,
            "unsupported_fund22_schema",
        ):
            build_fund_recommendation_layer_artifact(
                artifact
            )

    def test_upstream_firewall_must_remain_research_only(self) -> None:
        for field, value, error in (
            (
                "research_only",
                False,
                "upstream_research_only_not_true",
            ),
            (
                "execution_authority",
                True,
                "upstream_execution_authority_not_false",
            ),
            (
                "production_persist",
                True,
                "upstream_production_persist_not_false",
            ),
        ):
            with self.subTest(field=field):
                artifact = _artifact()
                artifact[field] = value

                with self.assertRaisesRegex(
                    FundRecommendationLayerContractError,
                    error,
                ):
                    build_fund_recommendation_layer_artifact(
                        artifact
                    )

    def test_upstream_must_not_already_have_recommendation_authority(self) -> None:
        for field, value, error in (
            (
                "decision_winner",
                "AAA",
                "upstream_decision_winner_present",
            ),
            (
                "recommendation",
                {"action": "X"},
                "upstream_recommendation_present",
            ),
            (
                "allocation",
                {"AAA": 10},
                "upstream_allocation_present",
            ),
        ):
            with self.subTest(field=field):
                artifact = _artifact()
                artifact[field] = value

                with self.assertRaisesRegex(
                    FundRecommendationLayerContractError,
                    error,
                ):
                    build_fund_recommendation_layer_artifact(
                        artifact
                    )

    def test_input_artifact_is_not_mutated(self) -> None:
        artifact = _artifact()
        before = copy.deepcopy(artifact)

        build_fund_recommendation_layer_artifact(
            artifact
        )

        self.assertEqual(artifact, before)


if __name__ == "__main__":
    unittest.main()
