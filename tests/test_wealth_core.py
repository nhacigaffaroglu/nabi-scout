import inspect
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.auth_service import get_current_user_id
from services.nabi_intelligence_facade import (
    InvestmentIntelligenceView,
    get_investment_intelligence,
)
from services.supabase_client import AuthenticationRequired
from services.wealth_contract import WealthValidationError
from services.wealth_core_service import WealthCoreService


class WealthCoreServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.user_id = "user-a"
        self.other_user_id = "user-b"
        self.service = WealthCoreService(self.client, self.user_id)

    def test_post_transaction_rebuilds_position(self) -> None:
        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.insert = MagicMock(
            return_value={"id": "txn-1", "txn_type": "buy"}
        )
        self.service.transactions.list_for_position = MagicMock(
            return_value=[
                {
                    "txn_type": "buy",
                    "quantity": 10,
                    "amount": 1000,
                    "executed_at": "2026-01-01",
                    "created_at": "2026-01-01",
                }
            ]
        )
        self.service.positions.upsert = MagicMock(return_value={"quantity": 10})

        self.service.post_transaction(
            account_id="acc-1",
            asset_id="asset-1",
            txn_type="buy",
            quantity=10,
            price=100,
            amount=1000,
        )

        self.service.transactions.insert.assert_called_once()
        self.service.positions.upsert.assert_called_once()
        upsert_kwargs = self.service.positions.upsert.call_args.kwargs
        self.assertEqual(upsert_kwargs["user_id"], self.user_id)
        self.assertAlmostEqual(upsert_kwargs["quantity"], 10)
        self.assertAlmostEqual(upsert_kwargs["average_cost"], 100.0)

    def test_post_transaction_deletes_zero_position(self) -> None:
        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.insert = MagicMock(return_value={"id": "txn-2"})
        ledger_buy_only = [
            {
                "txn_type": "buy",
                "quantity": 5,
                "amount": 500,
                "executed_at": "2026-01-01",
                "created_at": "2026-01-01",
            },
        ]
        ledger_after_sell = ledger_buy_only + [
            {
                "txn_type": "sell",
                "quantity": 5,
                "amount": 550,
                "executed_at": "2026-01-02",
                "created_at": "2026-01-02",
            },
        ]
        self.service.transactions.list_for_position = MagicMock(
            side_effect=[ledger_buy_only, ledger_after_sell]
        )
        self.service.positions.delete_for_account_asset = MagicMock()

        self.service.post_transaction(
            account_id="acc-1",
            asset_id="asset-1",
            txn_type="sell",
            quantity=5,
            price=110,
            amount=550,
        )

        self.service.positions.delete_for_account_asset.assert_called_once_with(
            self.user_id,
            "acc-1",
            "asset-1",
        )

    def test_register_asset_is_idempotent(self) -> None:
        existing = {"id": "asset-1", "symbol": "AAPL"}
        self.service.assets.find_by_identity = MagicMock(return_value=existing)
        self.service.assets.create = MagicMock()

        result = self.service.register_asset(
            symbol="AAPL",
            market="US",
            asset_class="equity",
        )

        self.assertEqual(result, existing)
        self.service.assets.create.assert_not_called()

    def test_reversal_requires_matching_original(self) -> None:
        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.get_by_id = MagicMock(
            return_value={
                "id": "orig",
                "account_id": "acc-2",
                "asset_id": "asset-1",
            }
        )

        with self.assertRaises(WealthValidationError):
            self.service.post_transaction(
                account_id="acc-1",
                asset_id="asset-1",
                txn_type="buy",
                quantity=1,
                price=100,
                amount=100,
                reversal_of_id="orig",
            )

    def test_duplicate_reversal_rejected(self) -> None:
        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.get_by_id = MagicMock(
            return_value={
                "id": "orig",
                "account_id": "acc-1",
                "asset_id": "asset-1",
            }
        )
        self.service.transactions.has_reversal_for = MagicMock(return_value=True)

        with self.assertRaises(WealthValidationError):
            self.service.post_transaction(
                account_id="acc-1",
                asset_id="asset-1",
                txn_type="buy",
                quantity=1,
                price=100,
                amount=100,
                reversal_of_id="orig",
            )

    def test_materialization_failure_surfaces_explicit_error(self) -> None:
        from services.wealth_contract import WealthMaterializationError

        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.insert = MagicMock(return_value={"id": "txn-1"})
        self.service.transactions.list_for_position = MagicMock(return_value=[])
        self.service._rebuild_position = MagicMock(side_effect=RuntimeError("db down"))

        with self.assertRaises(WealthMaterializationError):
            self.service.post_transaction(
                account_id="acc-1",
                asset_id="asset-1",
                txn_type="buy",
                quantity=1,
                price=100,
                amount=100,
            )

    def test_cross_user_account_rejected(self) -> None:
        self.service.accounts.get_by_id = MagicMock(return_value=None)
        with self.assertRaises(WealthValidationError):
            self.service.post_transaction(
                account_id="foreign-account",
                asset_id="asset-1",
                txn_type="buy",
                quantity=1,
                price=10,
                amount=10,
            )

    def test_oversell_rejected_before_insert(self) -> None:
        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        existing_ledger = [
            {
                "txn_type": "buy",
                "quantity": 10,
                "amount": 1000,
                "executed_at": "2026-01-01",
                "created_at": "2026-01-01",
            }
        ]
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.list_for_position = MagicMock(return_value=existing_ledger)
        self.service.transactions.insert = MagicMock()
        self.service.positions.upsert = MagicMock()
        self.service.positions.delete_for_account_asset = MagicMock()

        with self.assertRaises(WealthValidationError):
            self.service.post_transaction(
                account_id="acc-1",
                asset_id="asset-1",
                txn_type="sell",
                quantity=11,
                price=100,
                amount=1100,
            )

        self.service.transactions.insert.assert_not_called()
        self.service.positions.upsert.assert_not_called()
        self.service.positions.delete_for_account_asset.assert_not_called()

    def test_overdraw_rejected_before_insert(self) -> None:
        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        existing_ledger = [
            {
                "txn_type": "deposit",
                "quantity": 0,
                "amount": 100,
                "executed_at": "2026-01-01",
                "created_at": "2026-01-01",
            }
        ]
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.list_for_position = MagicMock(return_value=existing_ledger)
        self.service.transactions.insert = MagicMock()

        with self.assertRaises(WealthValidationError):
            self.service.post_transaction(
                account_id="acc-1",
                asset_id="asset-1",
                txn_type="withdraw",
                quantity=0,
                amount=150,
            )

        self.service.transactions.insert.assert_not_called()

    def test_invalid_reversal_rejected_before_insert(self) -> None:
        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.get_by_id = MagicMock(
            return_value={
                "id": "orig",
                "account_id": "acc-1",
                "asset_id": "asset-1",
                "txn_type": "sell",
                "quantity": 11,
                "amount": 1100,
            }
        )
        self.service.transactions.has_reversal_for = MagicMock(return_value=False)
        self.service.transactions.insert = MagicMock()

        with self.assertRaises(WealthValidationError):
            self.service.post_transaction(
                account_id="acc-1",
                asset_id="asset-1",
                txn_type="sell",
                quantity=10,
                price=100,
                amount=1000,
                reversal_of_id="orig",
            )

        self.service.transactions.insert.assert_not_called()

    def test_valid_transaction_inserts_once(self) -> None:
        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.list_for_position = MagicMock(return_value=[])
        self.service.transactions.insert = MagicMock(return_value={"id": "txn-new"})
        self.service.positions.upsert = MagicMock(return_value={"quantity": 2})

        result = self.service.post_transaction(
            account_id="acc-1",
            asset_id="asset-1",
            txn_type="buy",
            quantity=2,
            price=50,
            amount=100,
        )

        self.assertEqual(result["id"], "txn-new")
        self.service.transactions.insert.assert_called_once()
        insert_payload = self.service.transactions.insert.call_args.args[0]
        self.assertEqual(insert_payload["amount"], 100)

    def test_corrupted_ledger_reversal_recovery_via_service(self) -> None:
        account = {"id": "acc-1", "currency": "USD"}
        asset = {"id": "asset-1", "currency": "USD"}
        corrupted_ledger = [
            {
                "id": "buy-1",
                "txn_type": "buy",
                "quantity": 10,
                "amount": 1000,
                "executed_at": "2026-01-01",
                "created_at": "2026-01-01",
            },
            {
                "id": "sell-bad",
                "txn_type": "sell",
                "quantity": 11,
                "amount": 1100,
                "account_id": "acc-1",
                "asset_id": "asset-1",
                "executed_at": "2026-01-02",
                "created_at": "2026-01-02",
            },
        ]
        recovered_ledger = corrupted_ledger + [
            {
                "id": "rev-1",
                "txn_type": "sell",
                "quantity": 11,
                "amount": 1100,
                "executed_at": "2026-01-03",
                "created_at": "2026-01-03",
                "reversal_of_id": "sell-bad",
            }
        ]
        self.service.accounts.get_by_id = MagicMock(return_value=account)
        self.service.assets.get_by_id = MagicMock(return_value=asset)
        self.service.transactions.get_by_id = MagicMock(
            return_value=corrupted_ledger[1],
        )
        self.service.transactions.has_reversal_for = MagicMock(return_value=False)
        self.service.transactions.list_for_position = MagicMock(
            side_effect=[corrupted_ledger, recovered_ledger]
        )
        self.service.transactions.insert = MagicMock(return_value={"id": "rev-1"})
        self.service.positions.upsert = MagicMock()

        self.service.post_transaction(
            account_id="acc-1",
            asset_id="asset-1",
            txn_type="sell",
            quantity=11,
            price=100,
            amount=1100,
            reversal_of_id="sell-bad",
        )

        upsert_kwargs = self.service.positions.upsert.call_args.kwargs
        self.assertAlmostEqual(upsert_kwargs["quantity"], 10)
        self.assertAlmostEqual(upsert_kwargs["average_cost"], 100.0)

    def test_buy_sell_amount_derived_from_quantity_and_price(self) -> None:
        from services.wealth_contract import normalize_trade_amount

        self.assertEqual(
            normalize_trade_amount("buy", quantity=10, price=100, amount=0),
            1000,
        )
        with self.assertRaises(WealthValidationError):
            normalize_trade_amount("sell", quantity=5, price=0, amount=0)

    def test_is_transaction_reversal_eligible(self) -> None:
        reversed_ids = {"orig-1"}
        self.assertTrue(
            WealthCoreService.is_transaction_reversal_eligible(
                {"id": "orig-2", "txn_type": "buy"},
                reversed_ids,
            )
        )
        self.assertFalse(
            WealthCoreService.is_transaction_reversal_eligible(
                {"id": "orig-1", "txn_type": "buy"},
                reversed_ids,
            )
        )
        self.assertFalse(
            WealthCoreService.is_transaction_reversal_eligible(
                {"id": "rev-1", "txn_type": "buy", "reversal_of_id": "orig-1"},
                reversed_ids,
            )
        )

    def test_reverse_transaction_uses_original_values(self) -> None:
        original = {
            "id": "orig-1",
            "account_id": "acc-1",
            "asset_id": "asset-1",
            "txn_type": "sell",
            "quantity": 11.0,
            "amount": 1100.0,
            "currency": "USD",
            "price": 100.0,
        }
        self.service.transactions.get_by_id = MagicMock(return_value=original)
        self.service.transactions.list_for_user = MagicMock(return_value=[original])
        self.service.transactions.has_reversal_for = MagicMock(return_value=False)
        self.service.post_transaction = MagicMock(return_value={"id": "rev-1"})

        self.service.reverse_transaction("orig-1")

        self.service.post_transaction.assert_called_once_with(
            account_id="acc-1",
            asset_id="asset-1",
            txn_type="sell",
            quantity=11.0,
            amount=1100.0,
            currency="USD",
            price=100.0,
            notes="İşlem geri alma kaydı",
            reversal_of_id="orig-1",
        )

    def test_reverse_transaction_rejects_reversal_row(self) -> None:
        self.service.transactions.get_by_id = MagicMock(
            return_value={
                "id": "rev-1",
                "reversal_of_id": "orig-1",
                "account_id": "acc-1",
                "asset_id": "asset-1",
                "txn_type": "sell",
                "quantity": 11.0,
                "amount": 1100.0,
            }
        )
        self.service.post_transaction = MagicMock()

        with self.assertRaises(WealthValidationError):
            self.service.reverse_transaction("rev-1")

        self.service.post_transaction.assert_not_called()

    def test_reverse_transaction_rejects_already_reversed(self) -> None:
        original = {
            "id": "orig-1",
            "account_id": "acc-1",
            "asset_id": "asset-1",
            "txn_type": "sell",
            "quantity": 11.0,
            "amount": 1100.0,
            "currency": "USD",
            "price": 100.0,
        }
        reversal = {
            "id": "rev-1",
            "reversal_of_id": "orig-1",
            "account_id": "acc-1",
            "asset_id": "asset-1",
            "txn_type": "sell",
            "quantity": 11.0,
            "amount": 1100.0,
        }
        self.service.transactions.get_by_id = MagicMock(return_value=original)
        self.service.transactions.list_for_user = MagicMock(
            return_value=[original, reversal]
        )
        self.service.post_transaction = MagicMock()

        with self.assertRaises(WealthValidationError):
            self.service.reverse_transaction("orig-1")

        self.service.post_transaction.assert_not_called()

    def test_reverse_transaction_never_mutates_original(self) -> None:
        original = {
            "id": "orig-1",
            "account_id": "acc-1",
            "asset_id": "asset-1",
            "txn_type": "buy",
            "quantity": 10.0,
            "amount": 1000.0,
            "currency": "USD",
            "price": 100.0,
        }
        self.service.transactions.get_by_id = MagicMock(return_value=original)
        self.service.transactions.list_for_user = MagicMock(return_value=[original])
        self.service.post_transaction = MagicMock(return_value={"id": "rev-1"})

        self.service.reverse_transaction("orig-1")

        self.assertFalse(hasattr(self.service.transactions, "update"))
        self.service.post_transaction.assert_called_once()


class WealthReversalUiTests(unittest.TestCase):
    WEALTH_PAGE = Path("pages/10_Wealth.py")

    def test_page_exposes_reverse_action_without_freeform_id(self) -> None:
        source = self.WEALTH_PAGE.read_text(encoding="utf-8")
        self.assertIn("Geri Al", source)
        self.assertIn("reverse_transaction", source)
        self.assertIn("is_transaction_reversal_eligible", source)
        self.assertNotIn('text_input("reversal_of_id"', source)
        self.assertNotIn("reversal_of_id = st.", source)

    def test_page_reverse_uses_service_path(self) -> None:
        source = self.WEALTH_PAGE.read_text(encoding="utf-8")
        self.assertIn("wealth.reverse_transaction(txn_id)", source)
        self.assertIn("WealthMaterializationError", source)


class NabiIntelligenceFacadeTests(unittest.TestCase):
    def test_facade_reads_existing_candidate_without_writes(self) -> None:
        client = MagicMock()
        with patch(
            "services.nabi_intelligence_facade.CandidateRepository"
        ) as candidate_cls, patch(
            "services.nabi_intelligence_facade.ParticipationAssessmentRepository"
        ) as participation_cls:
            candidate_cls.return_value.get_by_symbol.return_value = {
                "id": "cand-1",
                "symbol": "AAPL",
                "market": "US",
                "company_name": "Apple",
                "decision": "İzle",
                "nabi_score": 72.5,
                "research_status": "Aktif",
            }
            participation_cls.return_value.get_latest.return_value = {
                "participation_status": "Uygun",
                "participation_score": 80,
            }

            view = get_investment_intelligence(client, "AAPL")

        self.assertIsInstance(view, InvestmentIntelligenceView)
        self.assertTrue(view.has_candidate)
        self.assertTrue(view.has_participation_snapshot)
        self.assertEqual(view.participation_status, "Uygun")
        candidate_cls.return_value.create.assert_not_called()
        candidate_cls.return_value.upsert_by_symbol.assert_not_called()


class WealthFirewallTests(unittest.TestCase):
    WEALTH_MODULES = (
        "services.wealth_contract",
        "services.wealth_position_engine",
        "services.wealth_core_service",
        "services.nabi_intelligence_facade",
    )
    WEALTH_PAGE = Path("pages/10_Wealth.py")
    FORBIDDEN = (
        "scanner_v",
        "nabi_score_v4",
        "decision_engine",
        "participation_business",
        "participation_financial",
        "participation_assessment_service",
        "manual_analysis_service",
        "investment_candidates",
        "watchlist",
        "tracked_funds",
        "scan_runs",
    )

    def test_wealth_core_has_no_forbidden_imports(self) -> None:
        for module_name in self.WEALTH_MODULES:
            module = __import__(module_name, fromlist=["*"])
            source = inspect.getsource(module)
            with self.subTest(module=module_name):
                for token in self.FORBIDDEN:
                    self.assertNotIn(token, source)

        page_source = self.WEALTH_PAGE.read_text(encoding="utf-8")
        for token in self.FORBIDDEN:
            self.assertNotIn(token, page_source)

    def test_nabi_facade_does_not_write(self) -> None:
        import services.nabi_intelligence_facade as module

        source = inspect.getsource(module)
        self.assertNotIn(".insert(", source)
        self.assertNotIn(".update(", source)
        self.assertNotIn(".delete(", source)
        self.assertNotIn(".upsert(", source)


class WealthMigrationRlsTests(unittest.TestCase):
    MIGRATION_PATH = Path("database/migration_wealth_core_phase1.sql")
    TABLES = (
        "wealth_portfolios",
        "wealth_accounts",
        "wealth_assets",
        "wealth_liabilities",
        "wealth_transactions",
        "wealth_positions",
    )

    def test_migration_exists(self) -> None:
        self.assertTrue(self.MIGRATION_PATH.is_file())

    def test_all_tables_user_scoped_with_rls(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8")
        for table in self.TABLES:
            with self.subTest(table=table):
                self.assertIn(f"create table if not exists public.{table}", sql)
                self.assertIn(f"user_id uuid not null references auth.users(id)", sql)
                self.assertIn(f"alter table public.{table} enable row level security", sql)

    def test_policies_use_auth_uid_equals_user_id(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        policy_blocks = re.findall(
            r"create policy[\s\S]*?;",
            sql,
        )
        self.assertGreater(len(policy_blocks), 0)
        for block in policy_blocks:
            self.assertIn("auth.uid() = user_id", block)

    def test_transactions_append_only_policies(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        txn_policies = [
            block
            for block in re.findall(r"create policy[\s\S]*?;", sql)
            if "wealth_transactions" in block
        ]
        joined = "\n".join(txn_policies)
        self.assertIn("for select", joined)
        self.assertIn("for insert", joined)
        self.assertNotIn("for update", joined)
        self.assertNotIn("for delete", joined)

    def test_no_anon_policies(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("to anon", sql)

    def test_composite_owner_foreign_keys_present(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        for constraint in (
            "wealth_accounts_portfolio_owner_fkey",
            "wealth_liabilities_portfolio_owner_fkey",
            "wealth_transactions_account_owner_fkey",
            "wealth_transactions_asset_owner_fkey",
            "wealth_transactions_reversal_owner_fkey",
            "wealth_positions_account_owner_fkey",
            "wealth_positions_asset_owner_fkey",
        ):
            with self.subTest(constraint=constraint):
                self.assertIn(constraint, sql)

    def test_does_not_touch_nabi_tables(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        for token in (
            "investment_candidates",
            "watchlist",
            "tracked_funds",
            "scan_runs",
            "participation_assessment_snapshots",
        ):
            self.assertNotIn(token, sql)


class AuthUserIdTests(unittest.TestCase):
    def test_get_current_user_id_returns_uuid_string(self) -> None:
        client = MagicMock()
        client.auth.get_user.return_value = MagicMock(user=MagicMock(id="uuid-123"))
        self.assertEqual(get_current_user_id(client), "uuid-123")

    def test_get_current_user_id_requires_session(self) -> None:
        client = MagicMock()
        client.auth.get_user.return_value = MagicMock(user=None)
        with self.assertRaises(AuthenticationRequired):
            get_current_user_id(client)


if __name__ == "__main__":
    unittest.main()
