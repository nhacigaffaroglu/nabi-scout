import unittest
from typing import Optional

from services.wealth_contract import WealthValidationError
from services.wealth_position_engine import materialize_position_from_transactions


def _txn(
    txn_type: str,
    *,
    quantity: float,
    amount: float,
    executed_at: str = "2026-01-01T00:00:00+00:00",
    reversal_of_id: Optional[str] = None,
) -> dict:
    return {
        "txn_type": txn_type,
        "quantity": quantity,
        "amount": amount,
        "executed_at": executed_at,
        "created_at": executed_at,
        "reversal_of_id": reversal_of_id,
    }


class WealthPositionEngineTests(unittest.TestCase):
    def test_buy_updates_weighted_average_cost(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn("buy", quantity=10, amount=1000, executed_at="2026-01-01T00:00:00+00:00"),
                _txn("buy", quantity=10, amount=1200, executed_at="2026-01-02T00:00:00+00:00"),
            ]
        )
        self.assertEqual(qty, 20)
        self.assertAlmostEqual(avg, 110.0)

    def test_sell_keeps_average_cost(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn("buy", quantity=10, amount=1000),
                _txn("sell", quantity=4, amount=500),
            ]
        )
        self.assertEqual(qty, 6)
        self.assertAlmostEqual(avg, 100.0)

    def test_sell_beyond_quantity_raises(self) -> None:
        with self.assertRaises(WealthValidationError):
            materialize_position_from_transactions(
                [_txn("buy", quantity=5, amount=500), _txn("sell", quantity=6, amount=600)]
            )

    def test_deposit_and_withdraw_cash(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn("deposit", quantity=0, amount=1000),
                _txn("withdraw", quantity=0, amount=200),
            ]
        )
        self.assertEqual(qty, 800)
        self.assertAlmostEqual(avg, 1.0)

    def test_dividend_increases_cash(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn("deposit", quantity=0, amount=500),
                _txn("dividend", quantity=0, amount=25),
            ]
        )
        self.assertEqual(qty, 525)

    def test_fee_reduces_cash(self) -> None:
        qty, _ = materialize_position_from_transactions(
            [
                _txn("deposit", quantity=0, amount=500),
                _txn("fee", quantity=0, amount=10),
            ]
        )
        self.assertEqual(qty, 490)

    def test_reversal_inverts_buy(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                _txn("buy", quantity=10, amount=1000),
                _txn(
                    "buy",
                    quantity=10,
                    amount=1000,
                    executed_at="2026-01-02T00:00:00+00:00",
                    reversal_of_id="orig",
                ),
            ]
        )
        self.assertEqual(qty, 0)
        self.assertEqual(avg, 0.0)

    def test_zero_position_after_full_sell(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [_txn("buy", quantity=3, amount=300), _txn("sell", quantity=3, amount=330)]
        )
        self.assertEqual(qty, 0)
        self.assertEqual(avg, 0.0)

    def test_equal_executed_at_uses_created_at_tiebreaker(self) -> None:
        qty, avg = materialize_position_from_transactions(
            [
                {
                    "txn_type": "sell",
                    "quantity": 4,
                    "amount": 400,
                    "executed_at": "2026-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:01+00:00",
                },
                {
                    "txn_type": "buy",
                    "quantity": 10,
                    "amount": 1000,
                    "executed_at": "2026-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            ]
        )
        self.assertEqual(qty, 6)
        self.assertAlmostEqual(avg, 100.0)


if __name__ == "__main__":
    unittest.main()
