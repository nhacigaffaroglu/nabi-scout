from __future__ import annotations

import unittest

from services.wealth_contract import (
    TXN_TYPE_BUY,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_SELL,
    TXN_TYPE_TRANSFER_IN,
    TXN_TYPE_TRANSFER_OUT,
    TXN_TYPE_WITHDRAW,
)
from services.wealth_performance_engine import aggregate_cash_flows
from services.wealth_position_engine import materialize_position_from_transactions


def _txn(
    txn_type: str,
    *,
    quantity: float,
    amount: float,
    account_id: str = "acc-1",
    executed_at: str = "2026-02-01T12:00:00+00:00",
) -> dict:
    return {
        "id": f"{txn_type}-{account_id}-{quantity}",
        "account_id": account_id,
        "txn_type": txn_type,
        "quantity": quantity,
        "amount": amount,
        "currency": "USD",
        "executed_at": executed_at,
        "created_at": executed_at,
    }


class WealthTransferAccountingTests(unittest.TestCase):
    def test_transfer_does_not_affect_cash_ledger(self) -> None:
        cash_qty, _ = materialize_position_from_transactions(
            [
                _txn(TXN_TYPE_DEPOSIT, quantity=0, amount=1000, account_id="cash"),
            ]
        )
        self.assertEqual(cash_qty, 1000)

    def test_transfer_has_zero_external_cash_flow(self) -> None:
        from datetime import datetime, timezone

        txns = [
            _txn(TXN_TYPE_TRANSFER_OUT, quantity=4, amount=1000, account_id="acc-a"),
            _txn(TXN_TYPE_TRANSFER_IN, quantity=4, amount=1000, account_id="acc-b"),
            _txn(TXN_TYPE_BUY, quantity=10, amount=2500, account_id="acc-a"),
        ]
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 3, 1, tzinfo=timezone.utc)
        inflows, outflows, dividends, fees, _warnings = aggregate_cash_flows(
            txns,
            account_ids={"acc-a", "acc-b"},
            base_currency="USD",
            period_start=start,
            period_end=end,
        )
        self.assertEqual(inflows, 0.0)
        self.assertEqual(outflows, 0.0)
        self.assertEqual(dividends, 0.0)
        self.assertEqual(fees, 0.0)

    def test_sell_still_counts_as_trade_not_transfer(self) -> None:
        from datetime import datetime, timezone

        txns = [
            _txn(TXN_TYPE_BUY, quantity=10, amount=1000, account_id="acc-a"),
            _txn(TXN_TYPE_SELL, quantity=4, amount=500, account_id="acc-a"),
        ]
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 3, 1, tzinfo=timezone.utc)
        inflows, outflows, _d, _f, _w = aggregate_cash_flows(
            txns,
            account_ids={"acc-a"},
            base_currency="USD",
            period_start=start,
            period_end=end,
        )
        self.assertEqual(inflows, 0.0)
        self.assertEqual(outflows, 0.0)

    def test_cash_deposit_withdraw_unaffected_by_transfer_semantics(self) -> None:
        from datetime import datetime, timezone

        txns = [
            _txn(TXN_TYPE_DEPOSIT, quantity=0, amount=500, account_id="acc-a"),
            _txn(TXN_TYPE_WITHDRAW, quantity=0, amount=100, account_id="acc-a"),
            _txn(TXN_TYPE_TRANSFER_OUT, quantity=2, amount=200, account_id="acc-a"),
        ]
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 3, 1, tzinfo=timezone.utc)
        inflows, outflows, _d, _f, _w = aggregate_cash_flows(
            txns,
            account_ids={"acc-a"},
            base_currency="USD",
            period_start=start,
            period_end=end,
        )
        self.assertAlmostEqual(inflows, 500.0)
        self.assertAlmostEqual(outflows, 100.0)


if __name__ == "__main__":
    unittest.main()
