from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from services.portfolio_security_decision_contract import (
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
)
from services.turkiye_fund_allocation_integration import (
    FundAllocationIntegrationContractError,
    INPUT_SCHEMA,
    INPUT_STATUS,
    OUTPUT_SCHEMA,
    OUTPUT_STATUS,
    STATE_ALLOCATED,
    STATE_BLOCKED,
    STATE_NOT_ALLOCATED,
    STATE_NOT_ELIGIBLE,
    build_fund_allocation_integration_artifact,
)
from services.wealth_new_money_allocation import (
    AllocationPlan,
    AllocationRecommendation,
    AllocationSkip,
)
from tests.test_nabi_adviser_8f import _psd
from tests.test_wealth_new_money_allocation import _policy, _view


def _row(
    code: str,
    *,
    action: str = DECISION_CONSIDER_NEW_POSITION,
    state: str = "DEPLOYMENT_ELIGIBLE",
    eligible: bool = True,
    rank: int = 1,
    exposure: bool = True,
) -> dict:
    return {
        "fund_code": code,
        "decision_rank": rank,
        "decision_evaluation_source_rank": rank,
        "canonical_decision_source_rank": rank,
        "recommendation_source_rank": rank,
        "deployment_source_rank": rank,
        "canonical_decision": action,
        "canonical_decision_payload": {
            "decision": action,
            "exposure_increase_allowed": exposure,
        },
        "recommendation_state": "RECOMMENDATION_READY",
        "recommendation_action": action,
        "recommendation_source": "CANONICAL_8E_DECISION",
        "deployment_state": state,
        "deployment_eligible": eligible,
        "deployment_action": action if eligible else None,
        "deployment_source": (
            "FUND23_RECOMMENDATION" if eligible else None
        ),
    }


def _artifact(*rows: dict) -> dict:
    return {
        "schema_version": INPUT_SCHEMA,
        "deployment_eligibility_status": INPUT_STATUS,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "candidates": list(rows),
    }


def _candidate(code: str) -> dict:
    return {
        "symbol": code,
        "participation_status": "Uygun",
        "research_allowed": True,
        "status": "GÜÇLÜ ADAY",
        "current_price": 10,
        "currency": "TRY",
        "market": "TR",
        "asset_type": "fund",
    }


def _empty_view():
    return _view([])


def _plan(
    *,
    recommendations=(),
    skipped=(),
    amount="1000",
    allocated="0",
    residual="1000",
    limitations=(),
):
    return AllocationPlan(
        input_amount=Decimal(amount),
        currency="TRY",
        recommendations=tuple(recommendations),
        total_allocated=Decimal(allocated),
        residual_cash=Decimal(residual),
        skipped=tuple(skipped),
        limitations=tuple(limitations),
    )


class Fund25ContractTests(unittest.TestCase):
    def _build(
        self,
        artifact,
        *,
        candidate_inputs=None,
        security_decisions=(),
    ):
        return build_fund_allocation_integration_artifact(
            artifact,
            available_amount=Decimal("1000"),
            amount_currency="TRY",
            portfolio_view=_empty_view(),
            policy=_policy(equity=100, etf=0),
            candidate_inputs=candidate_inputs or {},
            security_decisions=security_decisions,
            generated_at="2026-09-13T00:00:00+00:00",
        )

    def test_rejects_wrong_upstream_schema(self):
        artifact = _artifact()
        artifact["schema_version"] = "wrong"

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "fund24_schema_version_invalid",
        ):
            self._build(artifact)

    def test_rejects_wrong_upstream_status(self):
        artifact = _artifact()
        artifact["deployment_eligibility_status"] = "wrong"

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "fund24_status_invalid",
        ):
            self._build(artifact)

    def test_rejects_upstream_execution_authority(self):
        artifact = _artifact()
        artifact["execution_authority"] = True

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "fund24_execution_authority_must_be_false",
        ):
            self._build(artifact)

    def test_rejects_rank_provenance_mismatch(self):
        row = _row("AAA")
        row["deployment_source_rank"] = 2

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "allocation_rank_provenance_mismatch:AAA",
        ):
            self._build(
                _artifact(row),
                candidate_inputs={"AAA": _candidate("AAA")},
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                ),
            )

    def test_rejects_canonical_payload_decision_mismatch(self):
        row = _row("AAA")
        row["canonical_decision_payload"]["decision"] = (
            DECISION_CONSIDER_TOP_UP
        )

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "canonical_payload_decision_mismatch:AAA",
        ):
            self._build(
                _artifact(row),
                candidate_inputs={"AAA": _candidate("AAA")},
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                ),
            )

    def test_rejects_fund24_eligible_row_when_exposure_gate_false(self):
        row = _row("AAA", exposure=False)

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "canonical_exposure_gate_not_allowed:AAA",
        ):
            self._build(
                _artifact(row),
                candidate_inputs={"AAA": _candidate("AAA")},
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                ),
            )

    def test_requires_candidate_input_for_eligible_candidate(self):
        row = _row("AAA")

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "allocation_candidate_input_missing:AAA",
        ):
            self._build(
                _artifact(row),
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                ),
            )

    def test_requires_canonical_security_decision(self):
        row = _row("AAA")

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "canonical_security_decision_missing:AAA",
        ):
            self._build(
                _artifact(row),
                candidate_inputs={"AAA": _candidate("AAA")},
            )

    def test_rejects_security_decision_action_mismatch(self):
        row = _row("AAA")

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "canonical_security_decision_action_mismatch:AAA",
        ):
            self._build(
                _artifact(row),
                candidate_inputs={"AAA": _candidate("AAA")},
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_TOP_UP,
                        increase=True,
                    ),
                ),
            )

    def test_rejects_security_decision_exposure_block(self):
        row = _row("AAA")

        with self.assertRaisesRegex(
            FundAllocationIntegrationContractError,
            "canonical_security_decision_exposure_blocked:AAA",
        ):
            self._build(
                _artifact(row),
                candidate_inputs={"AAA": _candidate("AAA")},
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=False,
                    ),
                ),
            )

    def test_only_deployment_eligible_rows_enter_allocator(self):
        eligible = _row("AAA")
        not_eligible = _row(
            "BBB",
            state="NOT_ELIGIBLE_FOR_DEPLOYMENT",
            eligible=False,
            rank=2,
        )
        blocked = _row(
            "CCC",
            state="DEPLOYMENT_INPUT_BLOCKED",
            eligible=False,
            rank=3,
        )

        with patch(
            "services.turkiye_fund_allocation_integration.allocate_new_money",
            return_value=_plan(),
        ) as allocator:
            result = self._build(
                _artifact(eligible, not_eligible, blocked),
                candidate_inputs={
                    "AAA": _candidate("AAA"),
                    "BBB": _candidate("BBB"),
                    "CCC": _candidate("CCC"),
                },
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                ),
            )

        kwargs = allocator.call_args.kwargs
        self.assertEqual(
            [row["symbol"] for row in kwargs["candidates"]],
            ["AAA"],
        )
        self.assertEqual(
            [row.symbol for row in kwargs["security_decisions"]],
            ["AAA"],
        )

        by_code = {
            row["fund_code"]: row
            for row in result["candidates"]
        }
        self.assertEqual(
            by_code["BBB"]["allocation_state"],
            STATE_NOT_ELIGIBLE,
        )
        self.assertEqual(
            by_code["CCC"]["allocation_state"],
            STATE_BLOCKED,
        )

    def test_allocator_preserves_legacy_decision_and_carries_canonical_action(self):
        row = _row("AAA")
        candidate = _candidate("AAA")
        candidate["decision"] = "AVOID"

        with patch(
            "services.turkiye_fund_allocation_integration.allocate_new_money",
            return_value=_plan(),
        ) as allocator:
            self._build(
                _artifact(row),
                candidate_inputs={"AAA": candidate},
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                ),
            )

        forwarded = allocator.call_args.kwargs["candidates"][0]

        # Legacy opportunity classification is preserved for allocator
        # compatibility; canonical FUND24/8E authority travels separately.
        self.assertEqual(forwarded["decision"], "AVOID")
        self.assertEqual(
            forwarded["fund25_canonical_action"],
            DECISION_CONSIDER_NEW_POSITION,
        )
        self.assertEqual(forwarded["fund25_source_rank"], 1)

    def test_projects_real_allocation_amount_and_quantity(self):
        row = _row("AAA")

        recommendation = AllocationRecommendation(
            symbol="AAA",
            layer="fund",
            existing_or_new="new",
            decision=DECISION_CONSIDER_NEW_POSITION,
            price=Decimal("10"),
            price_currency="TRY",
            quantity=Decimal("25.5"),
            allocated_amount=Decimal("255"),
            reason_code="STRONG_CANDIDATE",
            reason_text="test allocation",
        )

        with patch(
            "services.turkiye_fund_allocation_integration.allocate_new_money",
            return_value=_plan(
                recommendations=(recommendation,),
                amount="1000",
                allocated="255",
                residual="745",
            ),
        ):
            result = self._build(
                _artifact(row),
                candidate_inputs={"AAA": _candidate("AAA")},
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                ),
            )

        self.assertEqual(result["schema_version"], OUTPUT_SCHEMA)
        self.assertEqual(
            result["allocation_integration_status"],
            OUTPUT_STATUS,
        )
        self.assertEqual(result["total_allocated"], "255")
        self.assertEqual(result["residual_cash"], "745")

        candidate = result["candidates"][0]
        self.assertEqual(candidate["allocation_state"], STATE_ALLOCATED)
        self.assertEqual(candidate["allocated_amount"], "255")
        self.assertEqual(candidate["quantity"], "25.5")
        self.assertEqual(candidate["allocation_source_rank"], 1)

    def test_eligible_but_unallocated_preserves_allocator_skip(self):
        row = _row("AAA")

        skip = AllocationSkip(
            symbol="AAA",
            reason_code="CONCENTRATION_LIMIT",
            reason_text="test skip",
        )

        with patch(
            "services.turkiye_fund_allocation_integration.allocate_new_money",
            return_value=_plan(skipped=(skip,)),
        ):
            result = self._build(
                _artifact(row),
                candidate_inputs={"AAA": _candidate("AAA")},
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                ),
            )

        candidate = result["candidates"][0]
        self.assertEqual(
            candidate["allocation_state"],
            STATE_NOT_ALLOCATED,
        )
        self.assertEqual(candidate["allocated_amount"], "0")
        self.assertEqual(candidate["quantity"], "0")
        self.assertEqual(
            candidate["allocation_skips"][0]["reason_code"],
            "CONCENTRATION_LIMIT",
        )

    def test_output_remains_planning_only(self):
        with patch(
            "services.turkiye_fund_allocation_integration.allocate_new_money",
            return_value=_plan(),
        ):
            result = self._build(_artifact())

        self.assertTrue(result["research_only"])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["production_persist"])
        self.assertIsNone(result["decision_winner"])
        self.assertIsNone(result["recommended_symbol"])
        self.assertIsNone(result["trade"])
        self.assertIsNone(result["order"])

        self.assertEqual(
            result["write_proof"],
            {
                "production_writes": 0,
                "trade_actions": 0,
                "orders": 0,
                "portfolio_writes": 0,
                "recommendation_history_writes": 0,
            },
        )




class Fund25RealAllocationEngineTests(unittest.TestCase):
    def test_real_allocator_receives_deployment_eligible_fund(self):
        """
        FUND24 eligible fund must reach the real canonical allocation engine.

        This is intentionally not mocked. It verifies the FUND25 adapter
        against the actual allocate_new_money contract.
        """
        from tests.test_wealth_new_money_allocation import (
            _candidate as base_candidate,
            _plan as base_plan,
            _policy as base_policy,
            _row as base_row,
            _view as base_view,
        )

        code = "F25X"

        portfolio_view = base_view(
            [
                base_row(
                    "SPUS",
                    market_value=10000,
                    weight_pct=100,
                    price=100,
                    asset_class="etf",
                )
            ]
        )

        candidate = base_candidate(
            code,
            "GÜÇLÜ ADAY",
            price=10,
            market="TR",
            currency="TRY",
            asset_type="fund",
        )

        decision = _psd(
            code,
            DECISION_CONSIDER_NEW_POSITION,
            increase=True,
            si_state="ATTRACTIVE",
        )

        artifact = _artifact(
            _row(
                code,
                action=DECISION_CONSIDER_NEW_POSITION,
                state="DEPLOYMENT_ELIGIBLE",
                eligible=True,
                rank=1,
                exposure=True,
            )
        )

        result = build_fund_allocation_integration_artifact(
            artifact,
            available_amount=Decimal("1000"),
            amount_currency="TRY",
            portfolio_view=portfolio_view,
            policy=base_policy(equity=0, etf=100),
            candidate_inputs={code: candidate},
            security_decisions=(decision,),
            generated_at="2026-09-13T00:00:00+00:00",
        )

        self.assertEqual(
            result["allocation_integration_status"],
            OUTPUT_STATUS,
        )
        self.assertEqual(result["counts"]["deployment_eligible"], 1)

        row = result["candidates"][0]

        # The candidate must have entered real allocation evaluation.
        self.assertTrue(row["allocation_eligible"])
        self.assertIn(
            row["allocation_state"],
            {STATE_ALLOCATED, STATE_NOT_ALLOCATED},
        )

        # FUND25 must preserve canonical provenance regardless of whether
        # portfolio policy ultimately allocates cash.
        self.assertEqual(
            row["canonical_decision"],
            DECISION_CONSIDER_NEW_POSITION,
        )
        self.assertEqual(row["allocation_source_rank"], 1)

        # Planning-only firewall remains intact.
        self.assertTrue(result["research_only"])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["production_persist"])
        self.assertIsNone(result["trade"])
        self.assertIsNone(result["order"])


class Fund25RankFirewallProbeTests(unittest.TestCase):
    def test_allocator_input_preserves_fund24_rank_order(self):
        rank_1 = _row("ZZZ", rank=1)
        rank_2 = _row("AAA", rank=2)

        with patch(
            "services.turkiye_fund_allocation_integration.allocate_new_money",
            return_value=_plan(),
        ) as allocator:
            build_fund_allocation_integration_artifact(
                _artifact(rank_2, rank_1),
                available_amount=Decimal("1000"),
                amount_currency="TRY",
                portfolio_view=_empty_view(),
                policy=_policy(equity=100, etf=0),
                candidate_inputs={
                    "AAA": _candidate("AAA"),
                    "ZZZ": _candidate("ZZZ"),
                },
                security_decisions=(
                    _psd(
                        "AAA",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                    _psd(
                        "ZZZ",
                        DECISION_CONSIDER_NEW_POSITION,
                        increase=True,
                    ),
                ),
                generated_at="2026-09-13T00:00:00+00:00",
            )

        forwarded = allocator.call_args.kwargs["candidates"]

        self.assertEqual(
            [(row["symbol"], row["fund25_source_rank"]) for row in forwarded],
            [("ZZZ", 1), ("AAA", 2)],
        )


class Fund25RealAllocatorRankRegressionTests(unittest.TestCase):
    def test_real_allocator_prefers_canonical_fund24_rank_over_symbol_order(self):
        """
        Two equally eligible FUND25 candidates compete for limited capital.

        ZZZ deliberately has FUND24 rank 1 while AAA has rank 2.
        Alphabetical/legacy ordering would prefer AAA. The canonical
        upstream rank must instead cause ZZZ to receive capital first.
        """
        from tests.test_wealth_new_money_allocation import (
            _candidate as base_candidate,
            _policy as base_policy,
            _row as base_portfolio_row,
            _view as base_view,
        )

        portfolio_view = base_view(
            [
                base_portfolio_row(
                    "SPUS",
                    market_value=10000,
                    weight_pct=100,
                    price=100,
                    asset_class="etf",
                )
            ]
        )

        candidates = {
            "AAA": base_candidate(
                "AAA",
                "GÜÇLÜ ADAY",
                price=100,
                market="IST",
                currency="TRY",
                asset_type="Hisse",
            ),
            "ZZZ": base_candidate(
                "ZZZ",
                "GÜÇLÜ ADAY",
                price=100,
                market="IST",
                currency="TRY",
                asset_type="Hisse",
            ),
        }

        decisions = (
            _psd(
                "AAA",
                DECISION_CONSIDER_NEW_POSITION,
                increase=True,
                si_state="ATTRACTIVE",
            ),
            _psd(
                "ZZZ",
                DECISION_CONSIDER_NEW_POSITION,
                increase=True,
                si_state="ATTRACTIVE",
            ),
        )

        # Deliberately supply artifact rows in the wrong order too:
        # AAA appears first but canonical FUND24 rank says ZZZ is first.
        artifact = _artifact(
            _row(
                "AAA",
                action=DECISION_CONSIDER_NEW_POSITION,
                state="DEPLOYMENT_ELIGIBLE",
                eligible=True,
                rank=2,
                exposure=True,
            ),
            _row(
                "ZZZ",
                action=DECISION_CONSIDER_NEW_POSITION,
                state="DEPLOYMENT_ELIGIBLE",
                eligible=True,
                rank=1,
                exposure=True,
            ),
        )

        result = build_fund_allocation_integration_artifact(
            artifact,
            available_amount=Decimal("6000"),
            amount_currency="TRY",
            portfolio_view=portfolio_view,
            policy=base_policy(equity=80, etf=20),
            candidate_inputs=candidates,
            security_decisions=decisions,
            generated_at="2026-09-13T00:00:00+00:00",
        )

        by_code = {
            row["fund_code"]: row
            for row in result["candidates"]
        }

        self.assertEqual(
            by_code["ZZZ"]["allocation_source_rank"],
            1,
        )
        self.assertEqual(
            by_code["AAA"]["allocation_source_rank"],
            2,
        )

        self.assertEqual(
            by_code["ZZZ"]["allocation_state"],
            STATE_ALLOCATED,
        )
        self.assertGreater(
            Decimal(str(by_code["ZZZ"]["allocated_amount"])),
            Decimal("0"),
        )

        # Real allocator integration must preserve canonical FUND24 rank
        # provenance while allowing the existing sizing engine to determine
        # amounts independently of rank.
        zzz_amount = Decimal(str(by_code["ZZZ"]["allocated_amount"]))
        aaa_amount = Decimal(str(by_code["AAA"]["allocated_amount"]))

        self.assertGreater(zzz_amount, Decimal("0"))
        self.assertGreater(aaa_amount, Decimal("0"))
        self.assertEqual(by_code["ZZZ"]["allocation_source_rank"], 1)
        self.assertEqual(by_code["AAA"]["allocation_source_rank"], 2)

        self.assertTrue(result["research_only"])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["production_persist"])


if __name__ == "__main__":
    unittest.main()
