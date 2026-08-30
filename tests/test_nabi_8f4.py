from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from components.wealth_new_money_allocation_ui import (
    RESULT_STATE_KEY,
    render_new_money_allocation,
)
from services.nabi_adviser_context import build_nabi_adviser_context
from services.nabi_decision_contract import (
    ACTION_CONSIDER_NEW_POSITION,
    DecisionV3Brief,
)
from services.opportunity_center_presentation import (
    build_opportunity_center,
    opportunity_displayed_security_action,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REVIEW,
    DECISION_WATCH,
)
from services.wealth_new_money_allocation import REASON_EXPOSURE_INCREASE_NOT_ALLOWED
from tests.test_nabi_adviser_8f import _psd
from tests.test_nabi_decision_v3 import _candidate
from services.nabi_today_presentation import today_displayed_security_action
from tests.test_nabi_today_8f import _today
from tests.test_wealth_new_money_allocation import (
    _candidate as _nm_candidate,
    _fx,
    _policy,
)
from tests.test_wealth_new_money_allocation_ui import (
    DummySt,
    _canonical_plan,
    _empty_result,
    _patch,
    _underweight_view,
    _wealth,
)

UI_ALLOC = Path("components/wealth_new_money_allocation_ui.py")
FIRSAT_UI = Path("components/opportunity_center_ui.py")
FIRSAT_PAGE = Path("pages/5_Firsatlar.py")

PARITY = (
    ("CRM", DECISION_WATCH, False, PARTICIPATION_STATUS_UYGUN, True, "WATCH", ("SI_WATCH",)),
    ("AAPL", DECISION_HOLD, False, "Uygun Değil", False, "AVOID", ("PARTICIPATION_NOT_UYGUN",)),
    ("MRVL", DECISION_REVIEW, False, "Kontrol Et", False, "CAUTION", ("PARTICIPATION_NOT_UYGUN",)),
    ("ADBE", DECISION_INSUFFICIENT_DATA, False, PARTICIPATION_STATUS_UYGUN, True, None, ("SI_MISSING",)),
)


def _brief(final_action: str, symbol: str) -> DecisionV3Brief:
    return DecisionV3Brief(
        final_action=final_action,
        timing_state="WAIT",
        portfolio_fit="UNKNOWN",
        why="legacy",
        symbol=symbol,
    )


class GoalCenterGateTests(unittest.TestCase):
    def test_goal_center_passes_canonical_security_decisions(self) -> None:
        source = UI_ALLOC.read_text(encoding="utf-8")
        self.assertIn("resolve_adviser_security_decisions", source)
        self.assertIn("security_decisions=gate_decisions", source)
        dummy = DummySt(clicked=True)
        allocate = MagicMock(return_value=_empty_result())
        decision = _psd("MSFT", DECISION_WATCH, increase=False)
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=_wealth(),
                plan=_canonical_plan(),
                policy=_policy(equity=80, etf=20),
                candidates=[_nm_candidate("MSFT", "GÜÇLÜ ADAY")],
                conversion=_fx(),
                allocate_fn=allocate,
                session_state=dummy.session_state,
                security_decisions=(decision,),
            )
        self.assertIn("security_decisions", allocate.call_args.kwargs)
        self.assertIs(allocate.call_args.kwargs["security_decisions"][0], decision)

    def test_goal_center_cannot_bypass_8e_gate(self) -> None:
        dummy = DummySt(clicked=True)
        decision = _psd("MSFT", DECISION_WATCH, increase=False, reasons=("SI_WATCH",))
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=_wealth(),
                plan=_canonical_plan(),
                policy=_policy(equity=70, etf=30),
                candidates=[_nm_candidate("MSFT", "GÜÇLÜ ADAY")],
                conversion=_fx(),
                session_state=dummy.session_state,
                security_decisions=(decision,),
            )
        result = dummy.session_state[RESULT_STATE_KEY]
        self.assertNotIn("MSFT", [row.symbol for row in result.recommendations])
        self.assertEqual(result.total_allocated, 0)
        self.assertEqual(result.residual_cash, result.input_amount)
        self.assertTrue(
            any(
                row.symbol == "MSFT"
                and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in result.skipped
            )
        )


class FirsatlarEightEDisplayTests(unittest.TestCase):
    def test_firsatlar_displays_canonical_8e_action(self) -> None:
        ui = FIRSAT_UI.read_text(encoding="utf-8")
        page = FIRSAT_PAGE.read_text(encoding="utf-8")
        self.assertIn("opportunity_displayed_security_action", ui)
        self.assertNotIn("decision_brief.final_action", ui)
        self.assertIn("resolve_adviser_security_decisions", page)
        view = build_opportunity_center(
            candidates=[_candidate("CRM")],
            decision_brief=_brief(ACTION_CONSIDER_NEW_POSITION, "CRM"),
            security_decisions=(_psd("CRM", DECISION_WATCH, increase=False),),
        )
        self.assertEqual(opportunity_displayed_security_action(view), DECISION_WATCH)
        self.assertEqual(view.decision_brief.final_action, ACTION_CONSIDER_NEW_POSITION)

    def test_missing_8e_on_firsatlar_fails_closed(self) -> None:
        view = build_opportunity_center(
            candidates=[_candidate("ADBE")],
            decision_brief=_brief(ACTION_CONSIDER_NEW_POSITION, "ADBE"),
            security_decisions=(),
        )
        self.assertEqual(
            opportunity_displayed_security_action(view),
            DECISION_INSUFFICIENT_DATA,
        )
        self.assertNotEqual(
            opportunity_displayed_security_action(view),
            view.decision_brief.final_action,
        )


class SurfaceParityTests(unittest.TestCase):
    def test_adviser_today_firsatlar_parity(self) -> None:
        decisions = tuple(
            _psd(
                symbol,
                decision,
                increase=increase,
                participation_status=participation,
                research_allowed=allowed,
                si_state=si_state,
                reasons=reasons,
            )
            for symbol, decision, increase, participation, allowed, si_state, reasons in PARITY
        )
        for symbol, decision, _increase, participation, *_rest in PARITY:
            with self.subTest(symbol=symbol):
                cand = _candidate(symbol, participation=participation)
                adviser = build_nabi_adviser_context(
                    f"{symbol}'yı almalı mıyım?",
                    candidates=[cand],
                    security_decisions=decisions,
                )
                today = _today(candidates=[cand], security_decisions=decisions)
                firsat = build_opportunity_center(
                    candidates=[cand],
                    decision_brief=_brief(ACTION_CONSIDER_NEW_POSITION, symbol),
                    security_decisions=decisions,
                )
                adviser_action = next(
                    item.decision for item in adviser.security_decisions if item.symbol == symbol
                )
                today_action = today_displayed_security_action(today)
                firsat_action = opportunity_displayed_security_action(firsat, symbol)
                self.assertEqual(adviser_action, decision)
                self.assertEqual(today_action, decision)
                self.assertEqual(firsat_action, decision)


if __name__ == "__main__":
    unittest.main()
