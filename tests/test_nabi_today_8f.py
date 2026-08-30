from __future__ import annotations

import unittest

from services.nabi_adviser_context import build_nabi_adviser_context
from services.nabi_decision_contract import ACTION_CONSIDER_NEW_POSITION
from services.nabi_today_presentation import (
    build_nabi_today_executive,
    today_displayed_security_action,
    today_security_action,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REVIEW,
    DECISION_WATCH,
    PortfolioSecurityDecision,
)
from tests.test_nabi_decision_v3 import _candidate
from tests.test_nabi_recommendation import _decision
from tests.test_nabi_today_ux import _cockpit, _goal, _money, _presented, _wealth_section


def _psd(
    symbol: str,
    decision: str,
    *,
    increase: bool = False,
    participation_status: str | None = None,
    research_allowed: bool | None = None,
    si_state: str | None = None,
    reasons: tuple[str, ...] = (),
) -> PortfolioSecurityDecision:
    return PortfolioSecurityDecision(
        symbol=symbol,
        decision=decision,
        confidence="MEDIUM",
        exposure_increase_allowed=increase,
        participation_status=participation_status,
        research_allowed=research_allowed,
        security_intelligence_state=si_state,
        primary_reasons=reasons,
        blocking_reasons=reasons,
        reason_codes=reasons,
    )


def _today(**overrides):
    payload = dict(
        wealth=_wealth_section(),
        cockpit=_cockpit(),
        goal_dashboard=_goal(),
        presented_actions=_presented(healthy=True),
        candidates=[],
        new_money=_money(ready=False),
        performance=None,
        decision=_decision(),
    )
    payload.update(overrides)
    return build_nabi_today_executive(**payload)


PARITY = (
    ("CRM", DECISION_WATCH, False, PARTICIPATION_STATUS_UYGUN, True, "WATCH", ("SI_WATCH",)),
    ("AAPL", DECISION_HOLD, False, "Uygun Değil", False, "AVOID", ("PARTICIPATION_NOT_UYGUN",)),
    ("MRVL", DECISION_REVIEW, False, "Kontrol Et", False, "CAUTION", ("PARTICIPATION_NOT_UYGUN",)),
    ("ADBE", DECISION_INSUFFICIENT_DATA, False, PARTICIPATION_STATUS_UYGUN, True, None, ("SI_MISSING",)),
)


class TodayEightEAuthorityTests(unittest.TestCase):
    def test_today_uses_canonical_8e_action(self) -> None:
        decision = _psd("CRM", DECISION_WATCH, increase=False, reasons=("SI_WATCH",))
        today = _today(
            candidates=[_candidate("CRM")],
            security_decisions=(decision,),
        )
        action = today_security_action(today, "CRM")
        self.assertIsNotNone(action)
        self.assertEqual(action.decision, DECISION_WATCH)
        self.assertFalse(action.exposure_increase_allowed)
        self.assertEqual(today_displayed_security_action(today), DECISION_WATCH)
        self.assertNotEqual(today.recommendation.action_code, ACTION_CONSIDER_NEW_POSITION)

    def test_today_adviser_parity(self) -> None:
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
        for symbol, decision, increase, participation, *_rest in PARITY:
            with self.subTest(symbol=symbol):
                today = _today(
                    candidates=[_candidate(symbol, participation=participation)],
                    security_decisions=decisions,
                )
                adviser = build_nabi_adviser_context(
                    f"{symbol}'yı almalı mıyım?",
                    candidates=[_candidate(symbol, participation=participation)],
                    security_decisions=decisions,
                )
                today_action = today_security_action(today, symbol)
                adviser_action = next(
                    item for item in adviser.security_decisions if item.symbol == symbol
                )
                self.assertEqual(today_action.decision, decision)
                self.assertEqual(adviser_action.decision, decision)
                self.assertEqual(
                    today_action.exposure_increase_allowed,
                    adviser_action.exposure_increase_allowed,
                )
                self.assertEqual(today_action.exposure_increase_allowed, increase)
                self.assertEqual(today_displayed_security_action(today), decision)

    def test_adbe_yeni_guclu_aday_is_not_consider(self) -> None:
        adbe = _candidate(
            "ADBE",
            participation=PARTICIPATION_STATUS_UYGUN,
            decision="GÜÇLÜ ADAY",
            research="YENI",
        )
        decision = _psd(
            "ADBE",
            DECISION_INSUFFICIENT_DATA,
            increase=False,
            participation_status=PARTICIPATION_STATUS_UYGUN,
            research_allowed=True,
            reasons=("SI_MISSING",),
        )
        today = _today(candidates=[adbe], security_decisions=(decision,))
        self.assertEqual(today_displayed_security_action(today), DECISION_INSUFFICIENT_DATA)
        self.assertNotEqual(today.recommendation.action_code, ACTION_CONSIDER_NEW_POSITION)
        self.assertNotIn(ACTION_CONSIDER_NEW_POSITION, today.synthesis)

    def test_missing_8e_fails_closed_without_legacy_consider(self) -> None:
        today = _today(candidates=[_candidate("ADBE")])
        self.assertEqual(today_displayed_security_action(today), DECISION_INSUFFICIENT_DATA)
        self.assertNotEqual(today.recommendation.action_code, ACTION_CONSIDER_NEW_POSITION)
        self.assertFalse(
            any(item.exposure_increase_allowed for item in today.security_decisions)
        )

    def test_legacy_recommendation_cannot_override_8e(self) -> None:
        decision = _psd("CRM", DECISION_WATCH, increase=False, reasons=("SI_WATCH",))
        today = _today(
            candidates=[_candidate("CRM", decision="GÜÇLÜ ADAY")],
            security_decisions=(decision,),
        )
        self.assertEqual(today.recommendation.action_code, DECISION_WATCH)
        self.assertEqual(today.synthesis, today.recommendation.primary_action)
        self.assertNotEqual(today.recommendation.action_code, ACTION_CONSIDER_NEW_POSITION)
        self.assertEqual(today_displayed_security_action(today), DECISION_WATCH)
        if (
            today.decision_v3 is not None
            and today.decision_v3.final_action == ACTION_CONSIDER_NEW_POSITION
        ):
            self.assertNotEqual(
                today_displayed_security_action(today),
                today.decision_v3.final_action,
            )


if __name__ == "__main__":
    unittest.main()
