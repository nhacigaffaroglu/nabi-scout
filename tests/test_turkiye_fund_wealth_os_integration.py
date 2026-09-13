import unittest

from services.turkiye_fund_wealth_os_integration import (
    INPUT_SCHEMA,
    INPUT_STATUS,
    OUTPUT_SCHEMA,
    OUTPUT_STATUS,
    STATE_INPUT_BLOCKED,
    STATE_NOT_ALLOCATED,
    STATE_NOT_ELIGIBLE,
    STATE_READY,
    FundWealthOsIntegrationContractError,
    build_fund_wealth_os_integration_artifact,
)


def allocated_row(
    symbol="AAA",
    *,
    rank=1,
    quantity=12.5,
    amount=2500.0,
    price=200.0,
):
    return {
        "fund_code": symbol,
        "allocation_state": "ALLOCATED",
        "quantity": quantity,
        "allocated_amount": amount,
        "price": price,
        "currency": "TRY",
        "decision_rank": rank,
        "decision_evaluation_source_rank": rank,
        "canonical_decision_source_rank": rank,
        "recommendation_source_rank": rank,
        "deployment_source_rank": rank,
        "allocation_source_rank": rank,
    }


def artifact(rows):
    return {
        "schema": INPUT_SCHEMA,
        "status": INPUT_STATUS,
        "rows": rows,
        "currency": "TRY",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
    }


class Fund26WealthOsIntegrationTests(unittest.TestCase):
    def test_ready_allocated_row_builds_lossless_buy_intent(self):
        result = build_fund_wealth_os_integration_artifact(
            artifact([allocated_row()]),
            account_id="account-1",
            asset_ids_by_symbol={"AAA": "asset-1"},
            executed_at="2026-09-13T18:00:00+03:00",
        )

        self.assertEqual(result["schema"], OUTPUT_SCHEMA)
        self.assertEqual(result["status"], OUTPUT_STATUS)

        self.assertEqual(len(result["transaction_intents"]), 1)
        intent = result["transaction_intents"][0]

        self.assertEqual(intent["symbol"], "AAA")
        self.assertEqual(intent["txn_type"], "BUY")
        self.assertEqual(intent["account_id"], "account-1")
        self.assertEqual(intent["asset_id"], "asset-1")
        self.assertEqual(intent["quantity"], 12.5)
        self.assertEqual(intent["amount"], 2500.0)
        self.assertEqual(intent["currency"], "TRY")
        self.assertEqual(intent["price"], 200.0)
        self.assertEqual(intent["source_rank"], 1)
        self.assertTrue(intent["execution_ready"])

        self.assertEqual(result["rows"][0]["wealth_os_state"], STATE_READY)

    def test_allocated_row_without_account_is_blocked_not_executed(self):
        result = build_fund_wealth_os_integration_artifact(
            artifact([allocated_row()]),
            asset_ids_by_symbol={"AAA": "asset-1"},
        )

        intent = result["transaction_intents"][0]
        self.assertFalse(intent["execution_ready"])
        self.assertIsNone(intent["account_id"])
        self.assertEqual(
            result["rows"][0]["wealth_os_state"],
            STATE_INPUT_BLOCKED,
        )

    def test_allocated_row_without_asset_mapping_is_blocked(self):
        result = build_fund_wealth_os_integration_artifact(
            artifact([allocated_row()]),
            account_id="account-1",
        )

        intent = result["transaction_intents"][0]
        self.assertFalse(intent["execution_ready"])
        self.assertIsNone(intent["asset_id"])
        self.assertEqual(
            result["rows"][0]["wealth_os_state"],
            STATE_INPUT_BLOCKED,
        )

    def test_not_allocated_row_never_creates_transaction_intent(self):
        row = allocated_row()
        row["allocation_state"] = "NOT_ALLOCATED"
        row["quantity"] = 0
        row["allocated_amount"] = 0

        result = build_fund_wealth_os_integration_artifact(
            artifact([row]),
            account_id="account-1",
            asset_ids_by_symbol={"AAA": "asset-1"},
        )

        self.assertEqual(result["transaction_intents"], [])
        self.assertEqual(
            result["rows"][0]["wealth_os_state"],
            STATE_NOT_ALLOCATED,
        )
        self.assertIsNone(
            result["rows"][0]["wealth_os_transaction_intent"]
        )

    def test_non_allocated_ineligible_state_is_preserved_as_not_eligible(self):
        row = allocated_row()
        row["allocation_state"] = "NOT_ELIGIBLE_FOR_ALLOCATION"
        row["quantity"] = 0
        row["allocated_amount"] = 0

        result = build_fund_wealth_os_integration_artifact(
            artifact([row])
        )

        self.assertEqual(result["transaction_intents"], [])
        self.assertEqual(
            result["rows"][0]["wealth_os_state"],
            STATE_NOT_ELIGIBLE,
        )

    def test_upstream_blocked_state_remains_blocked(self):
        row = allocated_row()
        row["allocation_state"] = "ALLOCATION_INPUT_BLOCKED"
        row["quantity"] = 0
        row["allocated_amount"] = 0

        result = build_fund_wealth_os_integration_artifact(
            artifact([row])
        )

        self.assertEqual(result["transaction_intents"], [])
        self.assertEqual(
            result["rows"][0]["wealth_os_state"],
            STATE_INPUT_BLOCKED,
        )

    def test_zero_quantity_allocated_row_fails_closed(self):
        with self.assertRaises(FundWealthOsIntegrationContractError):
            build_fund_wealth_os_integration_artifact(
                artifact([allocated_row(quantity=0)])
            )

    def test_zero_amount_allocated_row_fails_closed(self):
        with self.assertRaises(FundWealthOsIntegrationContractError):
            build_fund_wealth_os_integration_artifact(
                artifact([allocated_row(amount=0)])
            )

    def test_rank_provenance_mismatch_fails_closed(self):
        row = allocated_row(rank=1)
        row["allocation_source_rank"] = 2

        with self.assertRaises(FundWealthOsIntegrationContractError):
            build_fund_wealth_os_integration_artifact(
                artifact([row])
            )

    def test_wrong_schema_fails_closed(self):
        source = artifact([allocated_row()])
        source["schema"] = "wrong_schema"

        with self.assertRaises(FundWealthOsIntegrationContractError):
            build_fund_wealth_os_integration_artifact(source)

    def test_wrong_status_fails_closed(self):
        source = artifact([allocated_row()])
        source["status"] = "WRONG"

        with self.assertRaises(FundWealthOsIntegrationContractError):
            build_fund_wealth_os_integration_artifact(source)

    def test_upstream_execution_authority_true_fails_closed(self):
        source = artifact([allocated_row()])
        source["execution_authority"] = True

        with self.assertRaises(FundWealthOsIntegrationContractError):
            build_fund_wealth_os_integration_artifact(source)

    def test_upstream_production_persist_true_fails_closed(self):
        source = artifact([allocated_row()])
        source["production_persist"] = True

        with self.assertRaises(FundWealthOsIntegrationContractError):
            build_fund_wealth_os_integration_artifact(source)

    def test_fund26_preserves_execution_firewall(self):
        result = build_fund_wealth_os_integration_artifact(
            artifact([allocated_row()]),
            account_id="account-1",
            asset_ids_by_symbol={"AAA": "asset-1"},
        )

        self.assertTrue(result["research_only"])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["production_persist"])
        self.assertFalse(result["wealth_transactions_written"])
        self.assertFalse(result["wealth_positions_written"])
        self.assertFalse(result["orders_created"])
        self.assertFalse(result["trades_executed"])

    def test_multiple_allocations_preserve_canonical_source_ranks(self):
        source = artifact([
            allocated_row("ZZZ", rank=1, quantity=5, amount=1500, price=300),
            allocated_row("AAA", rank=2, quantity=10, amount=1000, price=100),
        ])

        result = build_fund_wealth_os_integration_artifact(
            source,
            account_id="account-1",
            asset_ids_by_symbol={
                "ZZZ": "asset-z",
                "AAA": "asset-a",
            },
        )

        intents = result["transaction_intents"]

        self.assertEqual(
            [(row["symbol"], row["source_rank"]) for row in intents],
            [("ZZZ", 1), ("AAA", 2)],
        )
        self.assertEqual(intents[0]["amount"], 1500.0)
        self.assertEqual(intents[1]["amount"], 1000.0)


if __name__ == "__main__":
    unittest.main()


class Fund26ArchitectureFirewallTests(unittest.TestCase):
    def test_fund26_service_cannot_cross_execution_boundary(self):
        from pathlib import Path

        source = Path(
            "services/turkiye_fund_wealth_os_integration.py"
        ).read_text(encoding="utf-8")

        forbidden = (
            "WealthCoreService(",
            ".post_transaction(",
            '.table("wealth_transactions")',
            ".table('wealth_transactions')",
            '.table("wealth_positions")',
            ".table('wealth_positions')",
            "WealthTransactionRepository(",
            "WealthPositionRepository(",
        )

        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_fund26_does_not_import_execution_or_repository_authorities(self):
        from pathlib import Path

        source = Path(
            "services/turkiye_fund_wealth_os_integration.py"
        ).read_text(encoding="utf-8")

        forbidden_imports = (
            "services.wealth_core_service",
            "repositories.wealth_transaction_repository",
            "repositories.wealth_position_repository",
        )

        for token in forbidden_imports:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_fund26_declares_non_execution_contract(self):
        result = build_fund_wealth_os_integration_artifact(
            artifact([allocated_row()]),
            account_id="account-1",
            asset_ids_by_symbol={"AAA": "asset-1"},
        )

        self.assertTrue(result["research_only"])
        self.assertIs(result["execution_authority"], False)
        self.assertIs(result["production_persist"], False)
        self.assertIs(result["wealth_transactions_written"], False)
        self.assertIs(result["wealth_positions_written"], False)
        self.assertIs(result["orders_created"], False)
        self.assertIs(result["trades_executed"], False)
