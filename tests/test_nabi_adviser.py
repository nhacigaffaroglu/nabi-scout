from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.nabi_adviser_answer import answer_nabi_adviser
from services.nabi_adviser_contract import (
    INTENT_NEW_MONEY_SCENARIO,
    INTENT_OPPORTUNITY_COMPARE,
    INTENT_PARTICIPATION_EXPLAIN,
    INTENT_TODAY_RECOMMENDATION,
    LLM_DISABLED_COPY,
)
from services.nabi_adviser_intent import parse_adviser_question
from services.nabi_decision_contract import (
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_RESEARCH_FIRST,
)
from services.nabi_recommendation import ACTION_REVIEW_GOAL_PLAN
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
)
from services.wealth_adviser_config import AdviserLlmConfig
from services.wealth_new_money_allocation import REASON_STRONG_CANDIDATE
from tests.test_nabi_decision_v3 import (
    _candidate,
    _monitor_decision,
    _plan,
    _plan_gap_presented,
    _rec,
    _thesis,
)
from tests.test_wealth_new_money_allocation import _policy, _view

PAGE = Path("pages/10_Wealth.py")
UI = Path("components/nabi_adviser_ui.py")
ANSWER = Path("services/nabi_adviser_answer.py")
CONTEXT = Path("services/nabi_adviser_context.py")


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


class IntentRoutingTests(unittest.TestCase):
    def test_today_and_participation_and_compare(self) -> None:
        self.assertEqual(
            parse_adviser_question("Bugün ne yapmalıyım?").intent,
            INTENT_TODAY_RECOMMENDATION,
        )
        parsed = parse_adviser_question("NVDA'yı almalı mıyım?")
        self.assertEqual(parsed.intent, INTENT_PARTICIPATION_EXPLAIN)
        self.assertEqual(parsed.focus_symbol, "NVDA")
        compare = parse_adviser_question("MU mu CRM mi?")
        self.assertEqual(compare.intent, INTENT_OPPORTUNITY_COMPARE)
        self.assertEqual(compare.compare_symbols[:2], ("MU", "CRM"))
        money = parse_adviser_question("100.000 TL nereye koyayım?")
        self.assertEqual(money.intent, INTENT_NEW_MONEY_SCENARIO)
        self.assertEqual(money.scenario_amount, "100000")
        self.assertEqual(money.scenario_currency, "TRY")


class AdversarialAdviserTests(unittest.TestCase):
    def test_a_today_matches_dashboard_primary(self) -> None:
        result = answer_nabi_adviser(
            "Bugün ne yapmalıyım?",
            candidates=[_candidate("CRM")],
            presented_actions=_plan_gap_presented(),
            decision=_monitor_decision(),
            allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            llm_config=_cfg(usable=False),
        )
        self.assertEqual(result.canonical_action, ACTION_REVIEW_GOAL_PLAN)
        self.assertIn("Katkı planını gözden geçir", result.answer)
        self.assertEqual(result.llm_calls, 0)

    def test_b_kontrol_et_is_not_investable(self) -> None:
        result = answer_nabi_adviser(
            "NVDA'yı almalı mıyım?",
            candidates=[
                _candidate(
                    "NVDA",
                    participation=PARTICIPATION_STATUS_KONTROL_ET,
                    score=99,
                )
            ],
            llm_config=_cfg(usable=False),
        )
        self.assertEqual(result.intent, INTENT_PARTICIPATION_EXPLAIN)
        self.assertNotIn(ACTION_CONSIDER_NEW_POSITION, result.answer)
        self.assertIn("katılım", result.answer.lower())
        self.assertNotRegex(result.answer.lower(), r"\bbuy\b")

    def test_c_new_money_uses_canonical_allocation(self) -> None:
        view = _view([])
        result = answer_nabi_adviser(
            "100.000 TL nereye koyayım?",
            candidates=[_candidate("CRM")],
            portfolio_view=view,
            policy=_policy(equity=70, etf=30),
            llm_config=_cfg(usable=False),
        )
        self.assertEqual(result.intent, INTENT_NEW_MONEY_SCENARIO)
        self.assertIn("100000", result.answer.replace(",", "").replace(".", ""))
        self.assertIn("New Money", result.answer)
        self.assertNotIn("FMPClient", ANSWER.read_text(encoding="utf-8"))

    def test_d_mu_vs_crm_preserves_opportunity_and_fit(self) -> None:
        mu = _candidate("MU", score=92)
        crm = _candidate("CRM", score=88)
        portfolio = SimpleNamespace(
            priced_positions=(SimpleNamespace(symbol="MU", weight_pct=25.0),)
        )
        plan = _plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new"))
        result = answer_nabi_adviser(
            "MU mu CRM mi?",
            candidates=[mu, crm],
            theses={"MU": _thesis("MU"), "CRM": _thesis("CRM")},
            portfolio_view=portfolio,
            allocation=plan,
            decision=_monitor_decision(),
            llm_config=_cfg(usable=False),
        )
        self.assertEqual(result.intent, INTENT_OPPORTUNITY_COMPARE)
        self.assertIn("MU", result.answer)
        self.assertIn("CRM", result.answer)

    def test_e_llm_disabled_is_still_useful(self) -> None:
        result = answer_nabi_adviser(
            "Fırsat var mı?",
            candidates=[
                {"symbol": "JNJ", "participation_status": PARTICIPATION_STATUS_UYGUN}
            ],
            llm_config=_cfg(usable=False),
        )
        self.assertFalse(result.used_llm)
        self.assertTrue(result.answer)
        self.assertIn(LLM_DISABLED_COPY, UI.read_text(encoding="utf-8"))

    def test_f_llm_enabled_one_call_per_submit(self) -> None:
        client = MagicMock()
        client.complete.return_value = json.dumps(
            {"answer": "Kanonik öneri katkı planını gözden geçirmektir."}
        )
        result = answer_nabi_adviser(
            "Bugün ne yapmalıyım?",
            presented_actions=_plan_gap_presented(),
            decision=_monitor_decision(),
            llm_config=_cfg(usable=True),
            llm_client=client,
        )
        self.assertEqual(client.complete.call_count, 1)
        self.assertEqual(result.llm_calls, 1)
        self.assertTrue(result.used_llm)

    def test_g_llm_buy_sell_is_constrained(self) -> None:
        client = MagicMock()
        client.complete.return_value = json.dumps({"answer": "BUY NVDA now"})
        result = answer_nabi_adviser(
            "NVDA'yı almalı mıyım?",
            candidates=[
                _candidate("NVDA", participation=PARTICIPATION_STATUS_KONTROL_ET)
            ],
            llm_config=_cfg(usable=True),
            llm_client=client,
        )
        self.assertEqual(result.llm_calls, 1)
        self.assertFalse(result.used_llm)
        self.assertNotIn("BUY NVDA", result.answer)
        self.assertIn("katılım", result.answer.lower())

    def test_h_missing_evidence_is_not_invented(self) -> None:
        result = answer_nabi_adviser(
            "ADSK neden RESEARCH_FIRST?",
            candidates=[
                {
                    "symbol": "ADSK",
                    "participation_status": PARTICIPATION_STATUS_UYGUN,
                }
            ],
            llm_config=_cfg(usable=False),
        )
        self.assertIn(ACTION_RESEARCH_FIRST, result.answer)
        self.assertNotIn("hedef fiyat", result.answer.lower())
        self.assertNotIn("catalyst invented", result.answer.lower())


class AdviserUiAndSafetyTests(unittest.TestCase):
    def test_page_does_not_fetch_providers_on_chat(self) -> None:
        block = PAGE.read_text(encoding="utf-8").split("with tab_adviser:")[1]
        self.assertNotIn("FMPClient.from_streamlit_secrets", block)
        self.assertNotIn("CompanyIntelligenceCoreService", block)
        self.assertNotIn("WEALTH_ADVISER_LLM_API_KEY", block)
        self.assertIn("render_nabi_adviser", block)
        self.assertIn("adviser_chat_form", UI.read_text(encoding="utf-8"))
        self.assertIn("NABI Danışman", UI.read_text(encoding="utf-8"))

    def test_no_second_score_engine(self) -> None:
        source = CONTEXT.read_text(encoding="utf-8") + ANSWER.read_text(encoding="utf-8")
        self.assertIn("build_nabi_decision_v3", source)
        self.assertIn("allocate_new_money", source)
        self.assertNotIn("nabi_score_v4", source)


if __name__ == "__main__":
    unittest.main()
