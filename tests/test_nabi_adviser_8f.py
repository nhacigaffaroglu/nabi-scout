from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from services.nabi_adviser_answer import answer_nabi_adviser
from services.nabi_adviser_context import build_nabi_adviser_context
from services.nabi_adviser_contract import REASON_8E_VS_NEW_MONEY_CONFLICT
from services.nabi_decision_contract import ACTION_CONSIDER_NEW_POSITION
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REVIEW,
    DECISION_WATCH,
    PortfolioSecurityDecision,
)
from services.wealth_adviser_config import AdviserLlmConfig
from services.wealth_new_money_allocation import REASON_STRONG_CANDIDATE
from tests.test_nabi_decision_v3 import _candidate, _plan, _rec
from tests.test_wealth_new_money_allocation import _policy, _view


def _cfg(*, usable: bool) -> AdviserLlmConfig:
    return AdviserLlmConfig(
        enabled=usable,
        provider="openai",
        model="gpt-test",
        timeout_seconds=10,
        max_output_tokens=256,
        temperature=0.0,
        api_key="sk-test" if usable else None,
    )


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


PARITY = (
    ("CRM", DECISION_WATCH, False, PARTICIPATION_STATUS_UYGUN, True, "WATCH", ("SI_WATCH",)),
    ("AAPL", DECISION_HOLD, False, "Uygun Değil", False, "AVOID", ("PARTICIPATION_NOT_UYGUN",)),
    ("MRVL", DECISION_REVIEW, False, "Kontrol Et", False, "CAUTION", ("PARTICIPATION_NOT_UYGUN",)),
    ("ADBE", DECISION_INSUFFICIENT_DATA, False, PARTICIPATION_STATUS_UYGUN, True, None, ("SI_MISSING",)),
)


class EightFAdviserPassthroughTests(unittest.TestCase):
    def test_security_decisions_passthrough_into_context(self) -> None:
        injected = _psd("CRM", DECISION_WATCH, increase=False, reasons=("SI_WATCH",))
        context = build_nabi_adviser_context(
            "CRM'yı almalı mıyım?",
            candidates=[_candidate("CRM")],
            security_decisions=(injected,),
        )
        match = next(item for item in context.security_decisions if item.symbol == "CRM")
        self.assertIs(match, injected)
        self.assertEqual(match.decision, DECISION_WATCH)
        self.assertFalse(match.exposure_increase_allowed)

    def test_uses_8e4b_loader_when_client_present(self) -> None:
        loaded = _psd("CRM", DECISION_WATCH, increase=False, reasons=("SI_WATCH",))
        with patch(
            "services.nabi_adviser_context.evaluate_portfolio_security_for_symbol",
            return_value=loaded,
        ) as loader:
            context = build_nabi_adviser_context(
                "CRM'yı almalı mıyım?",
                candidates=[_candidate("CRM")],
                portfolio_security_client=object(),
                user_id="user-1",
            )
        symbols = [call.args[1] for call in loader.call_args_list]
        self.assertIn("CRM", symbols)
        match = next(item for item in context.security_decisions if item.symbol == "CRM")
        self.assertEqual(match.decision, DECISION_WATCH)

    def test_parity_crm_aapl_mrvl_adbe(self) -> None:
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
        for symbol, decision, increase, *_rest in PARITY:
            with self.subTest(symbol=symbol):
                question = f"{symbol}'yı almalı mıyım?"
                context = build_nabi_adviser_context(
                    question,
                    candidates=[_candidate(symbol)],
                    security_decisions=decisions,
                )
                match = next(item for item in context.security_decisions if item.symbol == symbol)
                self.assertEqual(match.decision, decision)
                self.assertEqual(match.exposure_increase_allowed, increase)
                result = answer_nabi_adviser(
                    question,
                    candidates=[_candidate(symbol)],
                    security_decisions=decisions,
                    llm_config=_cfg(usable=False),
                )
                self.assertEqual(result.canonical_action, decision)
                self.assertNotIn(ACTION_CONSIDER_NEW_POSITION, result.answer)
                self.assertIn(symbol, result.answer)

    def test_adbe_uygun_yeni_is_not_consider(self) -> None:
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
        result = answer_nabi_adviser(
            "ADBE'yi almalı mıyım?",
            candidates=[adbe],
            security_decisions=(decision,),
            llm_config=_cfg(usable=False),
        )
        context = build_nabi_adviser_context(
            "ADBE'yi almalı mıyım?",
            candidates=[adbe],
            security_decisions=(decision,),
        )
        self.assertEqual(result.canonical_action, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(context.security_decisions[0].exposure_increase_allowed)
        self.assertNotIn(ACTION_CONSIDER_NEW_POSITION, result.answer)
        self.assertNotIn("Yeni pozisyon değerlendirilebilir", result.answer)
        self.assertIn("SI_MISSING", result.canonical_answer)

    def test_uygun_does_not_imply_research_allowed_increase(self) -> None:
        decision = _psd(
            "CRM",
            DECISION_WATCH,
            increase=False,
            participation_status=PARTICIPATION_STATUS_UYGUN,
            research_allowed=False,
            reasons=("RESEARCH_NOT_ALLOWED",),
        )
        context = build_nabi_adviser_context(
            "CRM'yı almalı mıyım?",
            candidates=[_candidate("CRM")],
            security_decisions=(decision,),
        )
        match = context.security_decisions[0]
        self.assertEqual(match.participation_status, PARTICIPATION_STATUS_UYGUN)
        self.assertIs(match.research_allowed, False)
        self.assertFalse(match.exposure_increase_allowed)
        self.assertNotEqual(match.decision, ACTION_CONSIDER_NEW_POSITION)


class EightFNewMoneyConflictTests(unittest.TestCase):
    def test_surfaces_conflict_without_changing_plan_or_8e(self) -> None:
        plan = _plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new"))
        eight_e = _psd("CRM", DECISION_WATCH, increase=False, reasons=("SI_WATCH",))
        with patch(
            "services.nabi_adviser_context.allocate_new_money",
            return_value=plan,
        ):
            context = build_nabi_adviser_context(
                "100.000 TL nereye koyayım?",
                candidates=[_candidate("CRM")],
                portfolio_view=_view([]),
                policy=_policy(equity=70, etf=30),
                allocation=plan,
                security_decisions=(eight_e,),
            )
        self.assertIn(REASON_8E_VS_NEW_MONEY_CONFLICT, context.blockers)
        self.assertIn(REASON_8E_VS_NEW_MONEY_CONFLICT, context.limitations)
        self.assertIn("exposure artışına izin vermiyor", context.canonical_answer)
        self.assertEqual(
            [item["symbol"] for item in context.new_money_context["recommendations"]],
            ["CRM"],
        )
        self.assertEqual(plan.recommendations[0].symbol, "CRM")
        self.assertEqual(str(plan.recommendations[0].allocated_amount), "20000")
        match = next(item for item in context.security_decisions if item.symbol == "CRM")
        self.assertEqual(match.decision, DECISION_WATCH)
        self.assertFalse(match.exposure_increase_allowed)
        self.assertNotEqual(
            context.current_recommendation.get("action_code"),
            ACTION_CONSIDER_NEW_POSITION,
        )


class EightFLlmBoundaryTests(unittest.TestCase):
    def test_llm_cannot_alter_deterministic_8e_fields(self) -> None:
        decision = _psd(
            "ADBE",
            DECISION_INSUFFICIENT_DATA,
            increase=False,
            participation_status=PARTICIPATION_STATUS_UYGUN,
            research_allowed=True,
            reasons=("SI_MISSING",),
        )
        client = MagicMock()
        client.complete.return_value = json.dumps(
            {"answer": "CONSIDER_NEW_POSITION ADBE because Uygun."}
        )
        result = answer_nabi_adviser(
            "ADBE'yi almalı mıyım?",
            candidates=[_candidate("ADBE")],
            security_decisions=(decision,),
            llm_config=_cfg(usable=True),
            llm_client=client,
        )
        context = build_nabi_adviser_context(
            "ADBE'yi almalı mıyım?",
            candidates=[_candidate("ADBE")],
            security_decisions=(decision,),
        )
        self.assertEqual(client.complete.call_count, 1)
        self.assertFalse(result.used_llm)
        self.assertEqual(result.canonical_action, DECISION_INSUFFICIENT_DATA)
        self.assertEqual(context.security_decisions[0].decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(context.security_decisions[0].exposure_increase_allowed)
        self.assertNotIn(ACTION_CONSIDER_NEW_POSITION, result.answer)


if __name__ == "__main__":
    unittest.main()
