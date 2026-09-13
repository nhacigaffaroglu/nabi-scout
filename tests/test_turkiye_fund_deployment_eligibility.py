import copy
import unittest

from services.portfolio_security_decision_contract import (
    DECISION_AVOID,
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REDUCE,
    DECISION_REVIEW,
    DECISION_WATCH,
)
from services.turkiye_fund_deployment_eligibility import (
    INPUT_SCHEMA,
    OUTPUT_SCHEMA,
    OUTPUT_STATUS,
    STATE_BLOCKED,
    STATE_ELIGIBLE,
    STATE_NOT_ELIGIBLE,
    FundDeploymentEligibilityContractError,
    build_fund_deployment_eligibility_artifact,
)


def _candidate(
    code="AAA",
    *,
    action=DECISION_CONSIDER_NEW_POSITION,
    state="RECOMMENDATION_READY",
    rank=1,
):
    return {
        "fund_code": code,
        "canonical_decision": action,
        "canonical_decision_payload": {
            "decision": action,
            "exposure_increase_allowed": True,
        },
        "canonical_decision_source_rank": rank,
        "decision_evaluation_source_rank": rank,
        "decision_rank": rank,
        "recommendation_state": state,
        "recommendation_action": (
            action if state == "RECOMMENDATION_READY" else None
        ),
        "recommendation_reasons": ["R1"],
        "recommendation_source_rank": rank,
        "recommendation_source": (
            "CANONICAL_8E_DECISION"
            if state == "RECOMMENDATION_READY"
            else None
        ),
        "recommended_symbol": None,
        "decision_winner": None,
        "allocation": None,
        "target_weight": None,
        "quantity": None,
        "trade": None,
        "order": None,
    }


def _artifact(*candidates):
    return {
        "schema_version": INPUT_SCHEMA,
        "recommendation_layer_status": "RECOMMENDATION_LAYER_COMPLETE",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "decision_winner": None,
        "recommended_symbol": None,
        "allocation": None,
        "target_weight": None,
        "quantity": None,
        "trade": None,
        "order": None,
        "candidates": list(candidates),
    }


class Fund24DeploymentEligibilityTests(unittest.TestCase):
    def test_deployable_actions_are_eligible(self):
        artifact = _artifact(
            _candidate(
                "AAA",
                action=DECISION_CONSIDER_NEW_POSITION,
                rank=1,
            ),
            _candidate(
                "BBB",
                action=DECISION_CONSIDER_TOP_UP,
                rank=2,
            ),
        )

        result = build_fund_deployment_eligibility_artifact(
            artifact,
            generated_at="2026-09-13T00:00:00+00:00",
        )

        self.assertEqual(result["schema_version"], OUTPUT_SCHEMA)
        self.assertEqual(
            result["deployment_eligibility_status"],
            OUTPUT_STATUS,
        )

        rows = {row["fund_code"]: row for row in result["candidates"]}

        for code in ("AAA", "BBB"):
            self.assertEqual(
                rows[code]["deployment_state"],
                STATE_ELIGIBLE,
            )
            self.assertTrue(rows[code]["deployment_eligible"])
            self.assertEqual(
                rows[code]["deployment_action"],
                rows[code]["recommendation_action"],
            )

    def test_deployable_action_fails_closed_when_exposure_increase_denied(self):
        row = _candidate(
            "AAA",
            action=DECISION_CONSIDER_NEW_POSITION,
        )
        row["canonical_decision_payload"][
            "exposure_increase_allowed"
        ] = False

        result = build_fund_deployment_eligibility_artifact(
            _artifact(row)
        )
        out = result["candidates"][0]

        self.assertEqual(
            out["deployment_state"],
            STATE_NOT_ELIGIBLE,
        )
        self.assertFalse(out["deployment_eligible"])
        self.assertIsNone(out["deployment_action"])

    def test_deployable_action_fails_closed_when_exposure_gate_missing(self):
        row = _candidate(
            "AAA",
            action=DECISION_CONSIDER_TOP_UP,
        )
        row["canonical_decision_payload"].pop(
            "exposure_increase_allowed"
        )

        result = build_fund_deployment_eligibility_artifact(
            _artifact(row)
        )
        out = result["candidates"][0]

        self.assertEqual(
            out["deployment_state"],
            STATE_NOT_ELIGIBLE,
        )
        self.assertFalse(out["deployment_eligible"])
        self.assertIsNone(out["deployment_action"])

    def test_non_deployable_canonical_actions_remain_not_eligible(self):
        decisions = (
            DECISION_HOLD,
            DECISION_WATCH,
            DECISION_REVIEW,
            DECISION_REDUCE,
            DECISION_AVOID,
            DECISION_INSUFFICIENT_DATA,
        )

        artifact = _artifact(
            *[
                _candidate(
                    f"F{i}",
                    action=decision,
                    rank=i,
                )
                for i, decision in enumerate(decisions, 1)
            ]
        )

        result = build_fund_deployment_eligibility_artifact(artifact)

        for row in result["candidates"]:
            self.assertEqual(
                row["deployment_state"],
                STATE_NOT_ELIGIBLE,
            )
            self.assertFalse(row["deployment_eligible"])
            self.assertIsNone(row["deployment_action"])

    def test_blocked_upstream_remains_blocked(self):
        artifact = _artifact(
            _candidate(
                "AAA",
                state="RECOMMENDATION_INPUT_BLOCKED",
            )
        )

        result = build_fund_deployment_eligibility_artifact(artifact)
        row = result["candidates"][0]

        self.assertEqual(row["deployment_state"], STATE_BLOCKED)
        self.assertFalse(row["deployment_eligible"])
        self.assertIsNone(row["deployment_action"])

    def test_not_eligible_upstream_remains_not_eligible(self):
        artifact = _artifact(
            _candidate(
                "AAA",
                state="NOT_ELIGIBLE_FOR_RECOMMENDATION",
            )
        )

        result = build_fund_deployment_eligibility_artifact(artifact)
        row = result["candidates"][0]

        self.assertEqual(
            row["deployment_state"],
            STATE_NOT_ELIGIBLE,
        )
        self.assertFalse(row["deployment_eligible"])
        self.assertIsNone(row["deployment_action"])

    def test_rank_provenance_is_preserved_without_rerank(self):
        artifact = _artifact(
            _candidate("BBB", rank=2),
            _candidate("AAA", rank=1),
        )

        result = build_fund_deployment_eligibility_artifact(artifact)

        self.assertEqual(
            [row["fund_code"] for row in result["candidates"]],
            ["BBB", "AAA"],
        )
        self.assertEqual(
            [row["deployment_source_rank"] for row in result["candidates"]],
            [2, 1],
        )

    def test_rank_mismatch_fails_closed(self):
        row = _candidate("AAA", rank=1)
        row["decision_rank"] = 2

        with self.assertRaises(FundDeploymentEligibilityContractError):
            build_fund_deployment_eligibility_artifact(
                _artifact(row)
            )

    def test_recommendation_action_must_match_canonical_decision(self):
        row = _candidate(
            "AAA",
            action=DECISION_CONSIDER_NEW_POSITION,
        )
        row["recommendation_action"] = DECISION_CONSIDER_TOP_UP

        with self.assertRaises(FundDeploymentEligibilityContractError):
            build_fund_deployment_eligibility_artifact(
                _artifact(row)
            )

    def test_invalid_recommendation_source_fails_closed(self):
        row = _candidate("AAA")
        row["recommendation_source"] = "OTHER_SOURCE"

        with self.assertRaises(FundDeploymentEligibilityContractError):
            build_fund_deployment_eligibility_artifact(
                _artifact(row)
            )

    def test_top_level_execution_fields_are_none(self):
        result = build_fund_deployment_eligibility_artifact(
            _artifact(_candidate("AAA"))
        )

        for field in (
            "decision_winner",
            "recommended_symbol",
            "deployment_target",
            "deployment_amount",
            "allocation",
            "allocation_pct",
            "target_weight",
            "quantity",
            "trade",
            "order",
        ):
            self.assertIsNone(result[field])

    def test_candidate_execution_fields_are_none(self):
        result = build_fund_deployment_eligibility_artifact(
            _artifact(_candidate("AAA"))
        )
        row = result["candidates"][0]

        for field in (
            "deployment_target",
            "deployment_amount",
            "allocation",
            "allocation_pct",
            "target_weight",
            "quantity",
            "trade",
            "order",
        ):
            self.assertIsNone(row[field])

    def test_research_firewall_is_preserved(self):
        result = build_fund_deployment_eligibility_artifact(
            _artifact(_candidate("AAA"))
        )

        self.assertTrue(result["research_only"])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["production_persist"])

        self.assertEqual(
            result["write_proof"],
            {
                "production_writes": 0,
                "trade_actions": 0,
                "orders": 0,
                "portfolio_writes": 0,
                "recommendation_history_writes": 0,
                "new_money_calls": 0,
                "allocation_calls": 0,
            },
        )

    def test_upstream_firewall_rejects_execution_fields(self):
        for field in (
            "decision_winner",
            "recommended_symbol",
            "allocation",
            "target_weight",
            "quantity",
            "trade",
            "order",
        ):
            artifact = _artifact(_candidate("AAA"))
            artifact[field] = "unexpected"

            with self.subTest(field=field):
                with self.assertRaises(
                    FundDeploymentEligibilityContractError
                ):
                    build_fund_deployment_eligibility_artifact(
                        artifact
                    )

    def test_wrong_schema_fails_closed(self):
        artifact = _artifact(_candidate("AAA"))
        artifact["schema_version"] = "wrong"

        with self.assertRaises(FundDeploymentEligibilityContractError):
            build_fund_deployment_eligibility_artifact(artifact)

    def test_duplicate_fund_code_fails_closed(self):
        artifact = _artifact(
            _candidate("AAA", rank=1),
            _candidate("AAA", rank=2),
        )

        with self.assertRaises(FundDeploymentEligibilityContractError):
            build_fund_deployment_eligibility_artifact(artifact)

    def test_input_artifact_is_not_mutated(self):
        artifact = _artifact(
            _candidate("AAA"),
            _candidate(
                "BBB",
                action=DECISION_WATCH,
                rank=2,
            ),
        )
        original = copy.deepcopy(artifact)

        build_fund_deployment_eligibility_artifact(artifact)

        self.assertEqual(artifact, original)


if __name__ == "__main__":
    unittest.main()
