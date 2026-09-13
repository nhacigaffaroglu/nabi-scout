import unittest
from unittest.mock import Mock

from services.turkiye_fund_controlled_execution import (
    INPUT_SCHEMA,
    INPUT_STATUS,
    MODE_DRY_RUN,
    MODE_EXECUTE,
    OUTPUT_SCHEMA,
    OUTPUT_STATUS,
    ControlledExecutionContractError,
    STATE_DRY_RUN,
    STATE_EXECUTED,
    build_controlled_execution_artifact,
)


def intent(
    symbol="AAA",
    *,
    rank=1,
    execution_ready=True,
):
    return {
        "symbol": symbol,
        "txn_type": "BUY",
        "account_id": "account-1",
        "asset_id": "asset-1",
        "quantity": 10.0,
        "amount": 2500.0,
        "currency": "TRY",
        "price": 250.0,
        "executed_at": "2026-09-13T18:00:00+03:00",
        "notes": "FUND26",
        "source_rank": rank,
        "source_schema": INPUT_SCHEMA,
        "source_status": INPUT_STATUS,
        "execution_ready": execution_ready,
        "idempotency_key": f"fund26:AAA:{rank}",
    }


def artifact(intents):
    return {
        "schema": INPUT_SCHEMA,
        "status": INPUT_STATUS,
        "transaction_intents": intents,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
    }


class Fund27BControlledExecutionTests(unittest.TestCase):
    def test_default_mode_is_dry_run_and_never_calls_wealth_core(self):
        wealth_core = Mock()

        result = build_controlled_execution_artifact(
            artifact([intent()]),
            wealth_core_service=wealth_core,
        )

        self.assertEqual(result["schema"], OUTPUT_SCHEMA)
        self.assertEqual(result["status"], OUTPUT_STATUS)
        self.assertEqual(result["mode"], MODE_DRY_RUN)
        self.assertEqual(result["state"], STATE_DRY_RUN)
        wealth_core.post_transaction.assert_not_called()

        self.assertTrue(result["research_only"])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["production_persist"])
        self.assertFalse(result["orders_created"])
        self.assertFalse(result["trades_executed"])

    def test_dry_run_preserves_intent_provenance(self):
        result = build_controlled_execution_artifact(
            artifact([intent(rank=7)])
        )

        output = result["intents"][0]

        self.assertEqual(output["source_rank"], 7)
        self.assertEqual(output["source_schema"], INPUT_SCHEMA)
        self.assertEqual(output["source_status"], INPUT_STATUS)
        self.assertTrue(output["execution_ready"])
        self.assertEqual(output["execution_state"], STATE_DRY_RUN)

    def test_non_execution_ready_intent_is_rejected(self):
        with self.assertRaises(ControlledExecutionContractError):
            build_controlled_execution_artifact(
                artifact([intent(execution_ready=False)])
            )

    def test_execute_without_explicit_authority_is_rejected(self):
        wealth_core = Mock()

        with self.assertRaises(ControlledExecutionContractError):
            build_controlled_execution_artifact(
                artifact([intent()]),
                mode=MODE_EXECUTE,
                wealth_core_service=wealth_core,
            )

        wealth_core.post_transaction.assert_not_called()

    def test_execute_requires_wealth_core_service(self):
        with self.assertRaises(ControlledExecutionContractError):
            build_controlled_execution_artifact(
                artifact([intent()]),
                mode=MODE_EXECUTE,
                execution_authority=True,
            )

    def test_execute_calls_only_canonical_wealth_core_transaction_path(self):
        wealth_core = Mock()
        wealth_core.post_transaction.return_value = {
            "id": "txn-1",
            "txn_type": "BUY",
        }

        result = build_controlled_execution_artifact(
            artifact([intent()]),
            mode=MODE_EXECUTE,
            execution_authority=True,
            wealth_core_service=wealth_core,
        )

        wealth_core.post_transaction.assert_called_once()

        kwargs = wealth_core.post_transaction.call_args.kwargs

        self.assertEqual(kwargs["account_id"], "account-1")
        self.assertEqual(kwargs["asset_id"], "asset-1")
        self.assertEqual(kwargs["txn_type"], "BUY")
        self.assertEqual(kwargs["quantity"], 10.0)
        self.assertEqual(kwargs["amount"], 2500.0)
        self.assertEqual(kwargs["currency"], "TRY")
        self.assertEqual(kwargs["price"], 250.0)
        self.assertEqual(
            kwargs["idempotency_key"],
            "fund26:AAA:1",
        )

        self.assertEqual(result["state"], STATE_EXECUTED)
        self.assertEqual(
            result["intents"][0]["execution_state"],
            STATE_EXECUTED,
        )
        self.assertEqual(
            result["executed_transactions"],
            [{"id": "txn-1", "txn_type": "BUY"}],
        )

        self.assertTrue(result["execution_authority"])
        self.assertTrue(result["production_persist"])
        self.assertFalse(result["orders_created"])
        self.assertFalse(result["trades_executed"])

    def test_wrong_input_schema_fails_closed(self):
        source = artifact([intent()])
        source["schema"] = "wrong"

        with self.assertRaises(ControlledExecutionContractError):
            build_controlled_execution_artifact(source)

    def test_wrong_input_status_fails_closed(self):
        source = artifact([intent()])
        source["status"] = "WRONG"

        with self.assertRaises(ControlledExecutionContractError):
            build_controlled_execution_artifact(source)

    def test_upstream_execution_authority_must_be_false(self):
        source = artifact([intent()])
        source["execution_authority"] = True

        with self.assertRaises(ControlledExecutionContractError):
            build_controlled_execution_artifact(source)

    def test_upstream_production_persist_must_be_false(self):
        source = artifact([intent()])
        source["production_persist"] = True

        with self.assertRaises(ControlledExecutionContractError):
            build_controlled_execution_artifact(source)

    def test_missing_idempotency_key_blocks_execute(self):
        source_intent = intent()
        source_intent.pop("idempotency_key")

        wealth_core = Mock()

        with self.assertRaises(ControlledExecutionContractError):
            build_controlled_execution_artifact(
                artifact([source_intent]),
                mode=MODE_EXECUTE,
                execution_authority=True,
                wealth_core_service=wealth_core,
            )

        wealth_core.post_transaction.assert_not_called()

    def test_unsupported_transaction_type_fails_closed(self):
        source_intent = intent()
        source_intent["txn_type"] = "SELL"

        with self.assertRaises(ControlledExecutionContractError):
            build_controlled_execution_artifact(
                artifact([source_intent])
            )

    def test_multiple_intents_preserve_order_and_rank(self):
        result = build_controlled_execution_artifact(
            artifact([
                intent("ZZZ", rank=1),
                intent("AAA", rank=2),
            ])
        )

        self.assertEqual(
            [
                (item["symbol"], item["source_rank"])
                for item in result["intents"]
            ],
            [("ZZZ", 1), ("AAA", 2)],
        )


if __name__ == "__main__":
    unittest.main()


class Fund27BExecutionFailureTests(unittest.TestCase):
    def test_wealth_core_failure_propagates_and_no_order_is_created(self):
        wealth_core = Mock()
        wealth_core.post_transaction.side_effect = RuntimeError(
            "WEALTH_CORE_FAILURE"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "WEALTH_CORE_FAILURE",
        ):
            build_controlled_execution_artifact(
                artifact([intent()]),
                mode=MODE_EXECUTE,
                execution_authority=True,
                wealth_core_service=wealth_core,
            )

        wealth_core.post_transaction.assert_called_once()

    def test_empty_intent_list_never_creates_execution(self):
        wealth_core = Mock()

        result = build_controlled_execution_artifact(
            artifact([]),
            mode=MODE_EXECUTE,
            execution_authority=True,
            wealth_core_service=wealth_core,
        )

        self.assertEqual(result["intents"], [])
        self.assertEqual(result["executed_transactions"], [])
        self.assertFalse(result["orders_created"])
        self.assertFalse(result["trades_executed"])
        wealth_core.post_transaction.assert_not_called()
