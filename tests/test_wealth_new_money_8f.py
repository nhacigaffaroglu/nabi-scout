from __future__ import annotations

import unittest
from decimal import Decimal

from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REVIEW,
    DECISION_WATCH,
)
from services.portfolio_security_decision_service import (
    fail_closed_portfolio_security_decision,
)
from services.wealth_new_money_allocation import (
    REASON_BELOW_MIN_TRADE,
    REASON_CONCENTRATION_LIMIT,
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_EXPOSURE_INCREASE_NOT_ALLOWED,
    REASON_STRONG_CANDIDATE,
)
from tests.test_nabi_adviser_8f import _psd
from tests.test_wealth_new_money_allocation import (
    _candidate,
    _plan,
    _policy,
    _row,
    _view,
)


def _holding_view():
    return _view(
        [
            _row("AAPL", market_value=1000, weight_pct=10, price=100),
            _row("SPUS", market_value=9000, weight_pct=90, price=100, asset_class="etf"),
        ]
    )


def _new_view():
    return _view(
        [_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]
    )


class NewMoneyExposureGateTests(unittest.TestCase):
    def test_a_existing_holding_8e_true_may_allocate(self) -> None:
        plan = _plan(
            view=_holding_view(),
            policy=_policy(equity=40, etf=60),
            candidates=[],
            security_decisions=(_psd("AAPL", DECISION_HOLD, increase=True),),
        )
        rec = next(row for row in plan.recommendations if row.symbol == "AAPL")
        self.assertEqual(rec.existing_or_new, "existing")
        self.assertEqual(rec.reason_code, REASON_EXISTING_HOLDING_TOPUP)
        self.assertGreater(rec.allocated_amount, 0)

    def test_b_existing_holding_8e_false_no_topup(self) -> None:
        plan = _plan(
            view=_holding_view(),
            policy=_policy(equity=40, etf=60),
            candidates=[],
            security_decisions=(_psd("AAPL", DECISION_HOLD, increase=False),),
        )
        self.assertNotIn("AAPL", [row.symbol for row in plan.recommendations])
        self.assertTrue(
            any(
                row.symbol == "AAPL"
                and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in plan.skipped
            )
        )

    def test_c_new_position_8e_true_may_allocate(self) -> None:
        plan = _plan(
            view=_new_view(),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
            security_decisions=(_psd("MSFT", DECISION_WATCH, increase=True),),
        )
        rec = next(row for row in plan.recommendations if row.symbol == "MSFT")
        self.assertEqual(rec.existing_or_new, "new")
        self.assertEqual(rec.reason_code, REASON_STRONG_CANDIDATE)
        self.assertGreater(rec.allocated_amount, 0)

    def test_d_new_position_8e_false_no_allocation(self) -> None:
        plan = _plan(
            view=_new_view(),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
            security_decisions=(_psd("MSFT", DECISION_WATCH, increase=False),),
        )
        self.assertNotIn("MSFT", [row.symbol for row in plan.recommendations])
        self.assertTrue(
            any(
                row.symbol == "MSFT"
                and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in plan.skipped
            )
        )

    def test_e_missing_8e_fails_closed(self) -> None:
        plan = _plan(
            view=_new_view(),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
            security_decisions=(),
        )
        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.residual_cash, plan.input_amount)
        self.assertTrue(
            any(
                row.symbol == "MSFT"
                and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in plan.skipped
            )
        )

    def test_f_unavailable_8e_fails_closed(self) -> None:
        plan = _plan(
            view=_new_view(),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
            security_decisions=(fail_closed_portfolio_security_decision("MSFT"),),
        )
        self.assertEqual(plan.recommendations, ())
        self.assertTrue(
            any(
                row.symbol == "MSFT"
                and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in plan.skipped
            )
        )
        self.assertFalse(
            fail_closed_portfolio_security_decision("MSFT").exposure_increase_allowed
        )

    def test_g_blocked_plus_eligible_continues(self) -> None:
        plan = _plan(
            view=_new_view(),
            policy=_policy(equity=70, etf=30),
            candidates=[
                _candidate("CRM", "GÜÇLÜ ADAY"),
                _candidate("MSFT", "GÜÇLÜ ADAY"),
            ],
            security_decisions=(
                _psd("CRM", DECISION_WATCH, increase=False, reasons=("SI_WATCH",)),
                _psd("MSFT", DECISION_HOLD, increase=True),
            ),
        )
        self.assertNotIn("CRM", [row.symbol for row in plan.recommendations])
        rec = next(row for row in plan.recommendations if row.symbol == "MSFT")
        self.assertGreater(rec.allocated_amount, 0)
        self.assertTrue(
            any(
                row.symbol == "CRM"
                and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in plan.skipped
            )
        )

    def test_h_all_blocked_leaves_residual(self) -> None:
        plan = _plan(
            view=_new_view(),
            policy=_policy(equity=70, etf=30),
            candidates=[
                _candidate("CRM", "GÜÇLÜ ADAY"),
                _candidate("MSFT", "GÜÇLÜ ADAY"),
            ],
            amount="100000",
            security_decisions=(
                _psd("CRM", DECISION_WATCH, increase=False),
                _psd("MSFT", DECISION_HOLD, increase=False),
            ),
        )
        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertEqual(plan.total_allocated, Decimal("0"))

    def test_i_blocked_does_not_bypass_lot_or_concentration(self) -> None:
        lot_blocked = _plan(
            view=_new_view(),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
            amount="60000",
            min_trade="100000",
            security_decisions=(_psd("MSFT", DECISION_WATCH, increase=True),),
        )
        self.assertEqual(lot_blocked.recommendations, ())
        self.assertTrue(
            any(row.reason_code == REASON_BELOW_MIN_TRADE for row in lot_blocked.skipped)
        )
        concentrated = _plan(
            view=_view(
                [_row("AAPL", market_value=10000, weight_pct=100, price=100)]
            ),
            policy=_policy(equity=100, etf=0),
            candidates=[],
            security_decisions=(_psd("AAPL", DECISION_HOLD, increase=False),),
        )
        self.assertEqual(concentrated.recommendations, ())
        self.assertTrue(
            any(
                row.symbol == "AAPL"
                and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in concentrated.skipped
            )
        )
        self.assertFalse(
            any(
                row.symbol == "AAPL" and row.reason_code == REASON_CONCENTRATION_LIMIT
                for row in concentrated.recommendations
            )
        )


class NewMoneyShadowParityTests(unittest.TestCase):
    """Read-only fixture shadow. Current 8E increase_allowed is false for all four."""

    CASES = (
        ("CRM", DECISION_WATCH, ("SI_WATCH",)),
        ("AAPL", DECISION_HOLD, ("PARTICIPATION_NOT_UYGUN",)),
        ("MRVL", DECISION_REVIEW, ("PARTICIPATION_NOT_UYGUN",)),
        ("ADBE", DECISION_INSUFFICIENT_DATA, ("SI_MISSING",)),
    )

    def test_current_four_names_are_gated_to_zero(self) -> None:
        view = _new_view()
        policy = _policy(equity=70, etf=30)
        candidates = [
            _candidate(symbol, "GÜÇLÜ ADAY", participation_status=PARTICIPATION_STATUS_UYGUN)
            for symbol, _decision, _reasons in self.CASES
        ]
        before = _plan(
            view=view,
            policy=policy,
            candidates=candidates,
            amount="100000",
        )
        after = _plan(
            view=view,
            policy=policy,
            candidates=candidates,
            amount="100000",
            security_decisions=tuple(
                _psd(symbol, decision, increase=False, reasons=reasons)
                for symbol, decision, reasons in self.CASES
            ),
        )
        self.assertGreater(before.total_allocated, 0)
        self.assertEqual(after.recommendations, ())
        self.assertEqual(after.residual_cash, Decimal("100000"))
        for symbol, _decision, _reasons in self.CASES:
            self.assertTrue(
                any(
                    row.symbol == symbol
                    and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                    for row in after.skipped
                )
            )


if __name__ == "__main__":
    unittest.main()
