from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from services.portfolio_management_service import PortfolioManagementService
from services.wealth_contract import (
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    WealthValidationError,
    buy_commission_from_ledger,
    compute_buy_cost_basis,
    normalize_trade_amount,
)
from services.wealth_core_service import WealthCoreService
from services.wealth_position_engine import materialize_position_from_transactions


FORBIDDEN_PROVIDER_TOKENS = (
    "fmp_client",
    "FMPClient",
    "CandidatePriceService",
    "openai",
    "sec_client",
    "SECFinancialClient",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "current_price",
)

CHANGED_PATHS = (
    Path("services/wealth_contract.py"),
    Path("services/wealth_position_engine.py"),
    Path("services/portfolio_management_service.py"),
    Path("components/portfolio_management_ui.py"),
)


class MemoryTxnRepo:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def insert(self, payload: dict) -> dict:
        row = {
            "id": f"txn-{len(self.rows) + 1}",
            "created_at": payload.get("executed_at") or "2026-08-01T00:00:00+00:00",
            **payload,
        }
        self.rows.append(row)
        return row

    def list_for_position(self, user_id: str, account_id: str, asset_id: str) -> list[dict]:
        return [
            row
            for row in self.rows
            if row.get("account_id") == account_id and str(row.get("asset_id")) == str(asset_id)
        ]

    def get_by_id(self, user_id: str, txn_id: str):
        return next((row for row in self.rows if row["id"] == txn_id), None)

    def has_reversal_for(self, user_id: str, original_id: str) -> bool:
        return any(row.get("reversal_of_id") == original_id for row in self.rows)

    def list_for_user(self, user_id: str, limit: int = 1000) -> list[dict]:
        return list(self.rows)[:limit]


def _wired_wealth(*, asset_id: str = "asset-crm") -> tuple[WealthCoreService, MemoryTxnRepo, list[dict]]:
    wealth = WealthCoreService(MagicMock(), "user-1")
    repo = MemoryTxnRepo()
    upserts: list[dict] = []
    asset = {
        "id": asset_id,
        "symbol": "CRM",
        "currency": "USD",
        "asset_class": ASSET_CLASS_EQUITY,
        "market": "US",
    }
    cash_asset = {"id": "asset-cash-usd", "symbol": "CASH", "currency": "USD"}
    wealth.accounts.get_by_id = MagicMock(return_value={"id": "acc-1", "currency": "USD"})
    wealth.assets.get_by_id = MagicMock(
        side_effect=lambda user_id, aid: cash_asset if aid == cash_asset["id"] else asset
    )
    wealth.assets.find_by_identity = MagicMock(return_value=asset)
    wealth.assets.create = MagicMock(return_value=asset)
    wealth.ensure_cash_asset = MagicMock(return_value=cash_asset)
    wealth.transactions = repo
    wealth.positions.upsert = MagicMock(side_effect=lambda **kwargs: upserts.append(kwargs) or kwargs)
    wealth.positions.delete_for_account_asset = MagicMock()
    return wealth, repo, upserts


class BuyCostFormulaTests(unittest.TestCase):
    def test_fee_zero(self) -> None:
        basis = compute_buy_cost_basis(10, 100, 0)
        self.assertEqual(basis.gross_cost, 1000.0)
        self.assertEqual(basis.commission, 0.0)
        self.assertEqual(basis.total_cost_basis, 1000.0)
        self.assertEqual(basis.effective_unit_cost, 100.0)

    def test_fee_included(self) -> None:
        basis = compute_buy_cost_basis(10, 100, 20)
        self.assertEqual(basis.gross_cost, 1000.0)
        self.assertEqual(basis.commission, 20.0)
        self.assertEqual(basis.total_cost_basis, 1020.0)
        self.assertEqual(basis.effective_unit_cost, 102.0)

    def test_decimal_fee(self) -> None:
        basis = compute_buy_cost_basis(10, 100, 2.55)
        self.assertAlmostEqual(basis.total_cost_basis, 1002.55)
        self.assertAlmostEqual(basis.effective_unit_cost, 100.255)

    def test_negative_fee_rejected(self) -> None:
        with self.assertRaises(WealthValidationError):
            compute_buy_cost_basis(10, 100, -0.01)

    def test_blank_or_none_commission_is_zero(self) -> None:
        self.assertEqual(compute_buy_cost_basis(10, 100, None).commission, 0.0)
        self.assertEqual(compute_buy_cost_basis(10, 100, 0.0).total_cost_basis, 1000.0)

    def test_normalize_buy_allows_commission_in_amount(self) -> None:
        self.assertEqual(
            normalize_trade_amount("buy", quantity=10, price=100, amount=0),
            1000.0,
        )
        self.assertEqual(
            normalize_trade_amount("buy", quantity=10, price=100, amount=1020),
            1020.0,
        )

    def test_normalize_buy_rejects_amount_below_gross(self) -> None:
        with self.assertRaises(WealthValidationError):
            normalize_trade_amount("buy", quantity=10, price=100, amount=900)

    def test_normalize_sell_still_requires_qty_times_price(self) -> None:
        self.assertEqual(
            normalize_trade_amount("sell", quantity=4, price=102, amount=408),
            408.0,
        )
        with self.assertRaises(WealthValidationError):
            normalize_trade_amount("sell", quantity=4, price=102, amount=400)


class PositionEngineCommissionTests(unittest.TestCase):
    def test_buy_fee_changes_basis_not_quantity(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                {
                    "txn_type": "buy",
                    "quantity": 10,
                    "price": 100,
                    "amount": 1020,
                    "executed_at": "2026-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            ]
        )
        self.assertEqual(qty, 10)
        self.assertAlmostEqual(avg, 102.0)
        self.assertAlmostEqual(qty * avg, 1020.0)

    def test_multi_lot_weighted_average_not_naive_unit_mean(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                {
                    "txn_type": "buy",
                    "quantity": 10,
                    "price": 100,
                    "amount": 1020,
                    "executed_at": "2026-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "txn_type": "buy",
                    "quantity": 5,
                    "price": 120,
                    "amount": 610,
                    "executed_at": "2026-01-02T00:00:00+00:00",
                    "created_at": "2026-01-02T00:00:00+00:00",
                },
            ]
        )
        self.assertEqual(qty, 15)
        self.assertAlmostEqual(qty * avg, 1630.0)
        self.assertAlmostEqual(avg, 1630.0 / 15)
        self.assertNotAlmostEqual(avg, (100 + 120) / 2)

    def test_fee_cash_event_still_reduces_cash_quantity(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                {
                    "txn_type": "deposit",
                    "quantity": 0,
                    "amount": 500,
                    "executed_at": "2026-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "txn_type": "fee",
                    "quantity": 0,
                    "amount": 10,
                    "executed_at": "2026-01-02T00:00:00+00:00",
                    "created_at": "2026-01-02T00:00:00+00:00",
                },
            ]
        )
        self.assertEqual(qty, 490)
        self.assertAlmostEqual(avg, 1.0)


class ManualAddHoldingCommissionTests(unittest.TestCase):
    def test_buy_fee_zero_ledger_and_position(self) -> None:
        wealth, repo, upserts = _wired_wealth()
        preview = compute_buy_cost_basis(10, 100, 0)
        PortfolioManagementService(wealth).add_holding(
            account_id="acc-1",
            symbol="CRM",
            quantity=10,
            average_cost=100,
            commission=0,
            executed_at="2026-01-01",
        )
        row = repo.rows[0]
        self.assertEqual(row["txn_type"], "buy")
        self.assertEqual(row["quantity"], 10)
        self.assertEqual(row["price"], 100)
        self.assertEqual(row["amount"], preview.total_cost_basis)
        self.assertEqual(buy_commission_from_ledger(
            quantity=row["quantity"], price=row["price"], amount=row["amount"]
        ), 0.0)
        self.assertAlmostEqual(upserts[-1]["quantity"], 10)
        self.assertAlmostEqual(upserts[-1]["average_cost"], 100.0)
        self.assertEqual(len(repo.rows), 1)

    def test_buy_with_fee_preserves_execution_price(self) -> None:
        wealth, repo, upserts = _wired_wealth()
        preview = compute_buy_cost_basis(10, 100, 20)
        PortfolioManagementService(wealth).add_holding(
            account_id="acc-1",
            symbol="CRM",
            quantity=10,
            average_cost=100,
            commission=20,
            executed_at="2026-01-01",
        )
        row = repo.rows[0]
        self.assertEqual(row["txn_type"], "buy")
        self.assertEqual(row["quantity"], preview.quantity)
        self.assertEqual(row["price"], preview.unit_price)
        self.assertEqual(row["amount"], preview.total_cost_basis)
        self.assertAlmostEqual(
            buy_commission_from_ledger(
                quantity=row["quantity"], price=row["price"], amount=row["amount"]
            ),
            20.0,
        )
        self.assertAlmostEqual(upserts[-1]["quantity"], 10)
        self.assertAlmostEqual(upserts[-1]["average_cost"], preview.effective_unit_cost)
        self.assertFalse(any(item["txn_type"] == "fee" for item in repo.rows))

    def test_decimal_fee_persisted_basis(self) -> None:
        wealth, repo, upserts = _wired_wealth()
        preview = compute_buy_cost_basis(10, 100, 2.55)
        PortfolioManagementService(wealth).add_holding(
            account_id="acc-1",
            symbol="CRM",
            quantity=10,
            average_cost=100,
            commission=2.55,
            executed_at="2026-01-01",
        )
        self.assertAlmostEqual(repo.rows[0]["amount"], preview.total_cost_basis)
        self.assertAlmostEqual(upserts[-1]["average_cost"], preview.effective_unit_cost)

    def test_negative_fee_rejected_before_insert(self) -> None:
        wealth, repo, upserts = _wired_wealth()
        with self.assertRaises(WealthValidationError):
            PortfolioManagementService(wealth).add_holding(
                account_id="acc-1",
                symbol="CRM",
                quantity=10,
                average_cost=100,
                commission=-1,
            )
        self.assertEqual(repo.rows, [])
        self.assertEqual(upserts, [])

    def test_ui_preview_equals_persisted_basis(self) -> None:
        wealth, repo, upserts = _wired_wealth()
        preview = compute_buy_cost_basis(10, 100, 20)
        PortfolioManagementService(wealth).add_holding(
            account_id="acc-1",
            symbol="CRM",
            quantity=preview.quantity,
            average_cost=preview.unit_price,
            commission=preview.commission,
            executed_at="2026-01-01",
        )
        qty, avg = materialize_position_from_transactions(repo.rows)
        self.assertEqual(repo.rows[0]["amount"], preview.total_cost_basis)
        self.assertEqual(repo.rows[0]["price"], preview.unit_price)
        self.assertEqual(qty, preview.quantity)
        self.assertAlmostEqual(avg, preview.effective_unit_cost)
        self.assertAlmostEqual(upserts[-1]["average_cost"], preview.effective_unit_cost)
        self.assertAlmostEqual(qty * avg, preview.total_cost_basis)

    def test_multi_lot_wac(self) -> None:
        wealth, repo, upserts = _wired_wealth()
        mgmt = PortfolioManagementService(wealth)
        first = compute_buy_cost_basis(10, 100, 20)
        second = compute_buy_cost_basis(5, 120, 10)
        mgmt.add_holding(
            account_id="acc-1",
            symbol="CRM",
            quantity=10,
            average_cost=100,
            commission=20,
            executed_at="2026-01-01",
        )
        mgmt.add_holding(
            account_id="acc-1",
            symbol="CRM",
            quantity=5,
            average_cost=120,
            commission=10,
            executed_at="2026-01-02",
        )
        qty, avg = materialize_position_from_transactions(repo.rows)
        self.assertEqual(len(repo.rows), 2)
        self.assertEqual(qty, 15)
        self.assertAlmostEqual(qty * avg, first.total_cost_basis + second.total_cost_basis)
        self.assertAlmostEqual(avg, 1630.0 / 15)
        self.assertAlmostEqual(upserts[-1]["quantity"], 15)
        self.assertAlmostEqual(upserts[-1]["average_cost"], 1630.0 / 15)

    def test_cash_deposit_ignores_buy_commission_logic(self) -> None:
        wealth, repo, upserts = _wired_wealth()
        PortfolioManagementService(wealth).add_holding(
            account_id="acc-1",
            symbol="CASH",
            quantity=500,
            average_cost=0,
            asset_class=ASSET_CLASS_CASH,
            commission=20,
            executed_at="2026-01-01",
        )
        row = repo.rows[0]
        self.assertEqual(row["txn_type"], "deposit")
        self.assertEqual(row["quantity"], 500)
        self.assertEqual(row["amount"], 500)
        self.assertEqual(row["price"], 1.0)
        self.assertAlmostEqual(upserts[-1]["quantity"], 500)
        self.assertAlmostEqual(upserts[-1]["average_cost"], 1.0)

    def test_sell_keeps_commission_inclusive_wac(self) -> None:
        wealth, repo, upserts = _wired_wealth()
        mgmt = PortfolioManagementService(wealth)
        mgmt.add_holding(
            account_id="acc-1",
            symbol="CRM",
            quantity=10,
            average_cost=100,
            commission=20,
            executed_at="2026-01-01",
        )
        wealth.post_transaction(
            account_id="acc-1",
            asset_id="asset-crm",
            txn_type="sell",
            quantity=4,
            price=102,
            amount=408,
            executed_at="2026-01-02T00:00:00+00:00",
        )
        qty, avg = materialize_position_from_transactions(repo.rows)
        self.assertEqual(qty, 6)
        self.assertAlmostEqual(avg, 102.0)
        self.assertEqual(repo.rows[1]["txn_type"], "sell")

    def test_reversal_cancels_commission_buy(self) -> None:
        wealth, repo, _upserts = _wired_wealth()
        PortfolioManagementService(wealth).add_holding(
            account_id="acc-1",
            symbol="CRM",
            quantity=10,
            average_cost=100,
            commission=20,
            executed_at="2026-01-01",
        )
        original_id = repo.rows[0]["id"]
        wealth.reverse_transaction(original_id)
        qty, avg = materialize_position_from_transactions(repo.rows)
        self.assertEqual(len(repo.rows), 2)
        self.assertEqual(repo.rows[1]["reversal_of_id"], original_id)
        self.assertEqual(repo.rows[1]["amount"], 1020)
        self.assertEqual(repo.rows[1]["price"], 100)
        self.assertEqual(qty, 0)
        self.assertEqual(avg, 0.0)


class ManualEntryUiCommissionTests(unittest.TestCase):
    def test_form_contains_commission_and_preview_labels(self) -> None:
        ui = Path("components/portfolio_management_ui.py").read_text(encoding="utf-8")
        for token in (
            "Kurum / Hesap",
            "Varlık türü",
            "Sembol",
            "Adet",
            "Birim alış fiyatı",
            "Komisyon / masraf",
            "Para birimi",
            "Alış tarihi",
            "Not (opsiyonel)",
            "Brüt alış",
            "Komisyon",
            "Toplam maliyet",
            "Komisyon dahil birim maliyet",
            "compute_buy_cost_basis",
            "commission=float(commission)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, ui)
        self.assertNotIn("Alış fiyatı / ortalama maliyet", ui)

    def test_preview_helper_uses_shared_formula(self) -> None:
        ui = Path("components/portfolio_management_ui.py").read_text(encoding="utf-8")
        self.assertIn("def render_buy_cost_preview", ui)
        self.assertIn("basis.gross_cost", ui)
        self.assertIn("basis.commission", ui)
        self.assertIn("basis.total_cost_basis", ui)
        self.assertIn("basis.effective_unit_cost", ui)


class ProviderIsolationTests(unittest.TestCase):
    def test_changed_modules_have_zero_provider_imports(self) -> None:
        for path in CHANGED_PATHS:
            source = path.read_text(encoding="utf-8")
            lowered = source.lower()
            for token in FORBIDDEN_PROVIDER_TOKENS:
                with self.subTest(path=str(path), token=token):
                    self.assertNotIn(token.lower(), lowered)


if __name__ == "__main__":
    unittest.main()
