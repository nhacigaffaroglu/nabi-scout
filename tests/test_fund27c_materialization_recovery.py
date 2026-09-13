import unittest
from unittest.mock import MagicMock

from services.wealth_core_service import WealthCoreService
from services.turkiye_fund_wealth_os_integration import (
    INPUT_SCHEMA,
    INPUT_STATUS,
    build_fund_wealth_os_integration_artifact,
)


class Fund27CMaterializationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.service = WealthCoreService(self.client, "user-a")

    @staticmethod
    def _existing_transaction():
        return {
            "id": "txn-existing",
            "account_id": "acc-1",
            "asset_id": "asset-1",
            "txn_type": "buy",
            "quantity": 10,
            "amount": 1000,
            "currency": "USD",
            "price": 100,
            "reversal_of_id": None,
            "idempotency_key": "fund27:test:recovery",
        }

    def test_idempotent_replay_repairs_materialization_without_duplicate_insert(self):
        existing = self._existing_transaction()

        self.service.transactions.get_by_idempotency_key = MagicMock(
            return_value=existing
        )
        self.service.transactions.insert = MagicMock()

        self.service.accounts.get_by_id = MagicMock(
            return_value={"id": "acc-1", "currency": "USD"}
        )
        self.service.assets.get_by_id = MagicMock(
            return_value={"id": "asset-1", "currency": "USD"}
        )
        self.service.transactions.list_for_position = MagicMock(
            return_value=[
                {
                    "txn_type": "buy",
                    "quantity": 10,
                    "amount": 1000,
                    "executed_at": "2026-09-13T10:00:00+00:00",
                    "created_at": "2026-09-13T10:00:00+00:00",
                }
            ]
        )
        self.service.positions.upsert = MagicMock(
            return_value={"quantity": 10, "average_cost": 100}
        )

        result = self.service.post_transaction(
            account_id="acc-1",
            asset_id="asset-1",
            txn_type="buy",
            quantity=10,
            price=100,
            amount=1000,
            currency="USD",
            idempotency_key="fund27:test:recovery",
        )

        self.assertEqual(result, existing)
        self.service.transactions.insert.assert_not_called()
        self.service.positions.upsert.assert_called_once()

    def test_public_recovery_rebuilds_position_from_existing_ledger(self):
        self.service.accounts.get_by_id = MagicMock(
            return_value={"id": "acc-1", "currency": "USD"}
        )
        self.service.assets.get_by_id = MagicMock(
            return_value={"id": "asset-1", "currency": "USD"}
        )
        self.service.transactions.list_for_position = MagicMock(
            return_value=[
                {
                    "txn_type": "buy",
                    "quantity": 4,
                    "amount": 400,
                    "executed_at": "2026-09-13T10:00:00+00:00",
                    "created_at": "2026-09-13T10:00:00+00:00",
                }
            ]
        )
        self.service.positions.upsert = MagicMock(
            return_value={
                "account_id": "acc-1",
                "asset_id": "asset-1",
                "quantity": 4,
                "average_cost": 100,
            }
        )
        self.service.positions.get_for_account_asset = MagicMock(
            return_value={
                "account_id": "acc-1",
                "asset_id": "asset-1",
                "quantity": 4,
                "average_cost": 100,
            }
        )

        result = self.service.recover_position_materialization(
            account_id="acc-1",
            asset_id="asset-1",
        )

        self.service.positions.upsert.assert_called_once()
        self.assertEqual(result["quantity"], 4)
        self.assertEqual(result["average_cost"], 100)


class Fund27CDeterministicIdempotencyTests(unittest.TestCase):
    @staticmethod
    def _artifact(generated_at):
        return {
            "schema": INPUT_SCHEMA,
            "status": INPUT_STATUS,
            "generated_at": generated_at,
            "currency": "TRY",
            "research_only": True,
            "execution_authority": False,
            "production_persist": False,
            "rows": [
                {
                    "fund_code": "AAA",
                    "allocation_state": "ALLOCATED",
                    "quantity": 10,
                    "allocated_amount": 1000,
                    "price": 100,
                    "currency": "TRY",
                    "decision_rank": 1,
                    "decision_evaluation_source_rank": 1,
                    "canonical_decision_source_rank": 1,
                    "recommendation_source_rank": 1,
                    "deployment_source_rank": 1,
                    "allocation_source_rank": 1,
                }
            ],
        }

    def _build(self, generated_at):
        return build_fund_wealth_os_integration_artifact(
            self._artifact(generated_at),
            account_id="acc-1",
            asset_ids_by_symbol={"AAA": "asset-1"},
        )["transaction_intents"][0]

    def test_same_allocation_run_produces_same_idempotency_key(self):
        first = self._build("2026-09-13T12:00:00+00:00")
        second = self._build("2026-09-13T12:00:00+00:00")

        self.assertTrue(first["idempotency_key"])
        self.assertEqual(
            first["idempotency_key"],
            second["idempotency_key"],
        )

    def test_different_allocation_run_produces_different_idempotency_key(self):
        first = self._build("2026-09-13T12:00:00+00:00")
        second = self._build("2026-09-13T13:00:00+00:00")

        self.assertNotEqual(
            first["idempotency_key"],
            second["idempotency_key"],
        )

    def test_idempotency_key_preserves_source_timestamp(self):
        intent = self._build("2026-09-13T12:00:00+00:00")

        self.assertEqual(
            intent["source_generated_at"],
            "2026-09-13T12:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
