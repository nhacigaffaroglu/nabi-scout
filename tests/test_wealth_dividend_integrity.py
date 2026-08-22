from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from services.portfolio_management_service import PortfolioManagementService
from services.wealth_contract import (
    TXN_TYPE_BUY,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_FEE,
    TXN_TYPE_SELL,
    TXN_TYPE_TRANSFER_IN,
    TXN_TYPE_TRANSFER_OUT,
    TXN_TYPE_WITHDRAW,
)
from services.wealth_external_cash_flow import contribution_delta_for_transaction
from services.wealth_performance_engine import collect_timed_external_flows
from services.wealth_position_engine import materialize_position_from_transactions


ACCOUNT = "acc-1"
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
)


def _txn(
    txn_type: str,
    *,
    quantity: float,
    amount: float,
    executed_at: str = "2026-01-01T00:00:00+00:00",
    account_id: str = ACCOUNT,
    txn_id: str | None = None,
    currency: str = "USD",
) -> dict:
    return {
        "id": txn_id or f"{txn_type}-{quantity}-{amount}-{executed_at}",
        "account_id": account_id,
        "txn_type": txn_type,
        "quantity": quantity,
        "amount": amount,
        "currency": currency,
        "executed_at": executed_at,
        "created_at": executed_at,
    }


class DividendPositionIntegrityTests(unittest.TestCase):
    def test_buy_increases_equity_quantity(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [_txn(TXN_TYPE_BUY, quantity=833, amount=9996)]
        )
        self.assertEqual(qty, 833)
        self.assertAlmostEqual(avg, 12.0)

    def test_sell_decreases_equity_quantity(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn(TXN_TYPE_BUY, quantity=833, amount=9996),
                _txn(TXN_TYPE_SELL, quantity=33, amount=400, executed_at="2026-01-02T00:00:00+00:00"),
            ]
        )
        self.assertEqual(qty, 800)
        self.assertAlmostEqual(avg, 12.0)

    def test_dividend_does_not_increase_equity_quantity(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn(TXN_TYPE_BUY, quantity=833, amount=9996),
                _txn(
                    TXN_TYPE_DIVIDEND,
                    quantity=25,
                    amount=25,
                    executed_at="2026-01-02T00:00:00+00:00",
                ),
            ]
        )
        self.assertEqual(qty, 833)
        self.assertAlmostEqual(avg, 12.0)

    def test_dividend_on_empty_position_does_not_create_position(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [_txn(TXN_TYPE_DIVIDEND, quantity=8330, amount=8330)]
        )
        self.assertEqual(qty, 0)
        self.assertEqual(avg, 0.0)

    def test_dividend_quantity_8330_does_not_create_shares(self) -> None:
        qty, _ = materialize_position_from_transactions(
            [_txn(TXN_TYPE_DIVIDEND, quantity=8330, amount=8330)]
        )
        self.assertNotEqual(qty, 8330)
        self.assertEqual(qty, 0)

    def test_dividend_does_not_alter_avg_cost(self) -> None:
        before_qty, before_avg = materialize_position_from_transactions(
            [_txn(TXN_TYPE_BUY, quantity=10, amount=1000)]
        )
        after_qty, after_avg = materialize_position_from_transactions(
            [
                _txn(TXN_TYPE_BUY, quantity=10, amount=1000),
                _txn(
                    TXN_TYPE_DIVIDEND,
                    quantity=100,
                    amount=50,
                    executed_at="2026-01-02T00:00:00+00:00",
                ),
            ]
        )
        self.assertEqual(after_qty, before_qty)
        self.assertEqual(after_avg, before_avg)

    def test_legitimate_buy_unchanged_when_dividend_present(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn(TXN_TYPE_BUY, quantity=833, amount=9996, account_id="ml"),
                _txn(
                    TXN_TYPE_DIVIDEND,
                    quantity=8330,
                    amount=8330,
                    executed_at="2026-08-18T13:08:17+00:00",
                    account_id="midas",
                ),
            ]
        )
        self.assertEqual(qty, 833)
        self.assertAlmostEqual(avg, 12.0)

    def test_buy_plus_dividend_quantity_equals_buy(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn(TXN_TYPE_BUY, quantity=833, amount=9996),
                _txn(
                    TXN_TYPE_DIVIDEND,
                    quantity=8330,
                    amount=8330,
                    executed_at="2026-08-18T13:08:17+00:00",
                ),
            ]
        )
        self.assertEqual(qty, 833)
        self.assertAlmostEqual(avg, 12.0)

    def test_dividend_only_asset_has_no_open_equity_position(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [_txn(TXN_TYPE_DIVIDEND, quantity=8330, amount=8330)]
        )
        self.assertEqual(qty, 0.0)
        self.assertEqual(avg, 0.0)

    def test_deposit_withdraw_unchanged(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn(TXN_TYPE_DEPOSIT, quantity=0, amount=1000),
                _txn(TXN_TYPE_WITHDRAW, quantity=0, amount=200, executed_at="2026-01-02T00:00:00+00:00"),
            ]
        )
        self.assertEqual(qty, 800)
        self.assertAlmostEqual(avg, 1.0)

    def test_transfer_accounting_unchanged(self) -> None:
        source_qty, source_avg = materialize_position_from_transactions(
            [
                _txn(TXN_TYPE_BUY, quantity=10, amount=2500),
                _txn(TXN_TYPE_TRANSFER_OUT, quantity=4, amount=1000, executed_at="2026-01-02T00:00:00+00:00"),
            ]
        )
        dest_qty, dest_avg = materialize_position_from_transactions(
            [_txn(TXN_TYPE_TRANSFER_IN, quantity=4, amount=1000)]
        )
        self.assertEqual(source_qty, 6)
        self.assertEqual(dest_qty, 4)
        self.assertAlmostEqual(source_avg, 250.0)
        self.assertAlmostEqual(dest_avg, 250.0)

    def test_fee_still_reduces_cash(self) -> None:
        qty, _ = materialize_position_from_transactions(
            [
                _txn(TXN_TYPE_DEPOSIT, quantity=0, amount=500),
                _txn(TXN_TYPE_FEE, quantity=0, amount=10, executed_at="2026-01-02T00:00:00+00:00"),
            ]
        )
        self.assertEqual(qty, 490)

    def test_reversal_pair_still_cancels_buy(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                {
                    "id": "orig",
                    "txn_type": TXN_TYPE_BUY,
                    "quantity": 10,
                    "amount": 1000,
                    "executed_at": "2026-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "txn_type": TXN_TYPE_BUY,
                    "quantity": 10,
                    "amount": 1000,
                    "executed_at": "2026-01-02T00:00:00+00:00",
                    "created_at": "2026-01-02T00:00:00+00:00",
                    "reversal_of_id": "orig",
                },
            ]
        )
        self.assertEqual(qty, 0)
        self.assertEqual(avg, 0.0)

    def test_dividend_reversal_pair_does_not_create_shares(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                {
                    "id": "div-1",
                    "txn_type": TXN_TYPE_DIVIDEND,
                    "quantity": 8330,
                    "amount": 8330,
                    "executed_at": "2026-08-18T13:08:17+00:00",
                    "created_at": "2026-08-18T13:08:18+00:00",
                },
                {
                    "txn_type": TXN_TYPE_DIVIDEND,
                    "quantity": 8330,
                    "amount": 8330,
                    "executed_at": "2026-08-18T14:00:00+00:00",
                    "created_at": "2026-08-18T14:00:00+00:00",
                    "reversal_of_id": "div-1",
                },
            ]
        )
        self.assertEqual(qty, 0)
        self.assertEqual(avg, 0.0)


class DividendContributionAndDietzTests(unittest.TestCase):
    def test_dividend_excluded_from_external_contribution(self) -> None:
        delta = contribution_delta_for_transaction(
            _txn(TXN_TYPE_DIVIDEND, quantity=8330, amount=8330, currency="TRY"),
            plan_currency="TRY",
        )
        self.assertEqual(delta, Decimal("0"))
        self.assertEqual(
            contribution_delta_for_transaction(
                _txn(TXN_TYPE_DEPOSIT, quantity=0, amount=100, currency="TRY"),
                plan_currency="TRY",
            ),
            Decimal("100"),
        )
        self.assertEqual(
            contribution_delta_for_transaction(
                _txn(TXN_TYPE_WITHDRAW, quantity=0, amount=40, currency="TRY"),
                plan_currency="TRY",
            ),
            Decimal("-40"),
        )

    def test_dividend_excluded_from_modified_dietz_external_flows(self) -> None:
        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        end = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)
        flows = collect_timed_external_flows(
            [
                _txn(
                    TXN_TYPE_DEPOSIT,
                    quantity=0,
                    amount=50,
                    currency="USD",
                    executed_at="2026-08-05T12:00:00+00:00",
                ),
                _txn(
                    TXN_TYPE_DIVIDEND,
                    quantity=8330,
                    amount=8330,
                    currency="USD",
                    executed_at="2026-08-10T12:00:00+00:00",
                ),
                _txn(
                    TXN_TYPE_WITHDRAW,
                    quantity=0,
                    amount=10,
                    currency="USD",
                    executed_at="2026-08-12T12:00:00+00:00",
                ),
                _txn(
                    TXN_TYPE_BUY,
                    quantity=1,
                    amount=50,
                    currency="USD",
                    executed_at="2026-08-08T12:00:00+00:00",
                ),
            ],
            account_ids={ACCOUNT},
            base_currency="USD",
            period_start=start,
            period_end=end,
        )
        self.assertEqual([row.signed_amount for row in flows], [50.0, -10.0])


class DividendCashEventMappingTests(unittest.TestCase):
    def test_record_cash_event_does_not_copy_amount_into_quantity(self) -> None:
        wealth = MagicMock()
        wealth.register_asset.return_value = {"id": "asset-visn"}
        wealth.post_transaction.return_value = {"id": "txn-1"}
        PortfolioManagementService(wealth).record_cash_event(
            account_id="midas",
            txn_type="dividend",
            amount=8330.0,
            currency="USD",
            symbol="VISN",
        )
        kwargs = wealth.post_transaction.call_args.kwargs
        self.assertEqual(kwargs["txn_type"], TXN_TYPE_DIVIDEND)
        self.assertEqual(kwargs["amount"], 8330.0)
        self.assertEqual(kwargs["quantity"], 0.0)

    def test_no_provider_imports_in_engine_or_cash_event(self) -> None:
        engine = Path("services/wealth_position_engine.py").read_text(encoding="utf-8")
        mgmt = Path("services/portfolio_management_service.py").read_text(encoding="utf-8")
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token, engine)
            self.assertNotIn(token, mgmt)


if __name__ == "__main__":
    unittest.main()
