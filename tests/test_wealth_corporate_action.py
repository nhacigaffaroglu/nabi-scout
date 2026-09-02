from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from services.fx_conversion_engine import apply_fx_to_position_rows
from services.portfolio_intelligence_engine import value_position
from services.wealth_contract import TXN_TYPE_CORPORATE_ACTION, WealthValidationError
from services.wealth_corporate_action import (
    ACTION_BONUS_SHARE,
    ACTION_STOCK_SPLIT,
    COST_BASIS_UNRESOLVED,
    build_corporate_action_event,
    corporate_action_already_applied,
    overlay_unresolved_quantity,
    proposed_corporate_action_row,
    split_quantity_and_cost,
)
from services.wealth_external_cash_flow import contribution_delta_for_transaction
from services.wealth_position_engine import materialize_position_from_transactions


PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
)
ENGINE = Path("services/wealth_corporate_action.py")
POSITION_ENGINE = Path("services/wealth_position_engine.py")


def _buy(quantity: float, amount: float, executed_at: str = "2025-01-01T00:00:00+00:00") -> dict:
    return {
        "id": "buy-1",
        "txn_type": "buy",
        "quantity": quantity,
        "amount": amount,
        "executed_at": executed_at,
        "created_at": executed_at,
    }


def _quote(price: float, currency: str = "TRY"):
    return type("Q", (), {"available": True, "price": price, "as_of": "2026-08-19"})()


class CorporateActionMathTests(unittest.TestCase):
    def test_two_for_one_preserves_total_cost(self) -> None:
        qty_after, cost_after, unit_after = split_quantity_and_cost(
            quantity=797,
            total_cost=371170.87,
            ratio=2.0,
        )
        self.assertEqual(qty_after, 1594)
        self.assertAlmostEqual(cost_after, 371170.87)
        self.assertAlmostEqual(unit_after, 232.855)

    def test_bonus_share_is_same_as_split(self) -> None:
        bonus = build_corporate_action_event(
            symbol="ABC",
            action_type=ACTION_BONUS_SHARE,
            effective_date="2026-05-14",
            ratio=2.0,
            quantity_before=100,
            total_cost=1000,
        )
        split = build_corporate_action_event(
            symbol="ABC",
            action_type=ACTION_STOCK_SPLIT,
            effective_date="2026-05-14",
            ratio=2.0,
            quantity_before=100,
            total_cost=1000,
        )
        self.assertEqual(bonus.quantity_after, split.quantity_after)
        self.assertEqual(bonus.cost_after, split.cost_after)
        self.assertEqual(bonus.additional_quantity(), 100)

    def test_proposed_row_is_not_a_purchase(self) -> None:
        event = build_corporate_action_event(
            symbol="ABC",
            action_type=ACTION_BONUS_SHARE,
            effective_date="2026-05-14",
            ratio=2.0,
            quantity_before=797,
            total_cost=371170.87,
            source="issuer-notice",
        )
        row = proposed_corporate_action_row(event)
        self.assertEqual(row["txn_type"], TXN_TYPE_CORPORATE_ACTION)
        self.assertNotEqual(row["txn_type"], "buy")
        self.assertEqual(row["amount"], 0.0)
        self.assertEqual(row["quantity"], 797)
        self.assertIn("BONUS_SHARE", row["notes"])
        self.assertIn("quantity_before", row["notes"])


class CorporateActionLedgerTests(unittest.TestCase):
    def test_replay_adjusts_quantity_and_unit_cost(self) -> None:
        event = build_corporate_action_event(
            symbol="ABC",
            action_type=ACTION_BONUS_SHARE,
            effective_date="2026-05-14",
            ratio=2.0,
            quantity_before=797,
            total_cost=371170.87,
        )
        qty, avg = materialize_position_from_transactions(
            [_buy(797, 371170.87), proposed_corporate_action_row(event)]
        )
        self.assertEqual(qty, 1594)
        self.assertAlmostEqual(avg, 232.855)
        self.assertAlmostEqual(qty * avg, 371170.87)

    def test_corporate_action_cannot_create_cash(self) -> None:
        with self.assertRaises(WealthValidationError):
            materialize_position_from_transactions(
                [
                    _buy(10, 1000),
                    {
                        "txn_type": TXN_TYPE_CORPORATE_ACTION,
                        "quantity": 10,
                        "amount": 50,
                        "executed_at": "2026-05-14T00:00:00+00:00",
                    },
                ]
            )

    def test_apply_helper_is_idempotent(self) -> None:
        event = build_corporate_action_event(
            symbol="ABC",
            action_type=ACTION_BONUS_SHARE,
            effective_date="2026-05-14",
            ratio=2.0,
            quantity_before=100,
            total_cost=800,
        )
        existing = [proposed_corporate_action_row(event)]
        self.assertTrue(corporate_action_already_applied(existing, event))
        self.assertFalse(
            corporate_action_already_applied(
                [_buy(100, 800)],
                event,
            )
        )

    def test_no_symbol_hardcode_in_engine(self) -> None:
        blob = ENGINE.read_text(encoding="utf-8") + POSITION_ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("BIMAS", blob)
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token, blob)

    def test_contribution_delta_is_zero(self) -> None:
        event = build_corporate_action_event(
            symbol="ABC",
            action_type=ACTION_BONUS_SHARE,
            effective_date="2026-05-14",
            ratio=2.0,
            quantity_before=10,
            total_cost=100,
        )
        row = proposed_corporate_action_row(event)
        row["currency"] = "TRY"
        self.assertEqual(contribution_delta_for_transaction(row, plan_currency="TRY"), 0)


class UnresolvedCostTests(unittest.TestCase):
    def test_missing_post_action_lot_is_not_zeroed(self) -> None:
        position = {
            "id": "p1",
            "account_id": "a1",
            "asset_id": "s1",
            "quantity": 1594,
            "average_cost": 232.855,
        }
        overlaid = overlay_unresolved_quantity(
            position,
            authoritative_quantity=1611,
            cost_covered_quantity=1594,
        )
        self.assertEqual(overlaid["quantity"], 1611)
        self.assertAlmostEqual(overlaid["average_cost"], 232.855)
        self.assertTrue(overlaid["cost_basis_unresolved"])
        self.assertEqual(overlaid["cost_basis_status"], COST_BASIS_UNRESOLVED)
        row = value_position(
            position=overlaid,
            asset={"symbol": "ABC", "asset_class": "equity", "currency": "TRY"},
            account={"name": "Broker"},
            base_currency="USD",
            quote=_quote(416.5),
        )
        self.assertAlmostEqual(row.quantity, 1611)
        self.assertAlmostEqual(row.market_value, 1611 * 416.5)
        self.assertAlmostEqual(row.cost_basis, 1594 * 232.855)
        self.assertNotAlmostEqual(row.cost_basis, 0.0)
        self.assertIsNone(row.unrealized_pl)
        self.assertTrue(row.cost_basis_unresolved)

    def test_fx_does_not_invent_pl(self) -> None:
        native = value_position(
            position=overlay_unresolved_quantity(
                {"id": "p1", "account_id": "a1", "asset_id": "s1", "quantity": 1594, "average_cost": 232.855},
                authoritative_quantity=1611,
                cost_covered_quantity=1594,
            ),
            asset={"symbol": "ABC", "asset_class": "equity", "currency": "TRY"},
            account={"name": "Broker"},
            base_currency="USD",
            quote=_quote(416.5),
        )
        fx = MagicMock()
        fx.convert_amount.side_effect = [
            type("R", (), {"converted": True, "converted_amount": 100.0, "stale": False, "rate_used": 48.0, "rate_date": "2026-08-21", "limitation": None, "unavailable": False})(),
            type("R", (), {"converted": True, "converted_amount": 80.0, "stale": False, "rate_used": 48.0, "rate_date": "2026-08-21", "limitation": None, "unavailable": False})(),
        ]
        rows, _totals = apply_fx_to_position_rows(
            [native],
            base_currency="USD",
            fx_service=fx,
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].unrealized_pl)
        self.assertTrue(rows[0].cost_basis_unresolved)
        self.assertAlmostEqual(rows[0].market_value, 100.0)
        self.assertAlmostEqual(rows[0].cost_basis, 80.0)


if __name__ == "__main__":
    unittest.main()
