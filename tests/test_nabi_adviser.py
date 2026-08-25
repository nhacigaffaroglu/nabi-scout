from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.nabi_adviser_answer import answer_nabi_adviser
from services.nabi_adviser_contract import (
    AMOUNT_CLARIFICATION,
    INTENT_GENERAL_NABI,
    INTENT_NEW_MONEY_SCENARIO,
    INTENT_OPPORTUNITY_COMPARE,
    INTENT_OPPORTUNITY_STATUS,
    INTENT_PARTICIPATION_EXPLAIN,
    INTENT_TODAY_RECOMMENDATION,
    INTENT_WHY_RECOMMENDATION,
    LLM_DISABLED_COPY,
    NO_ACTIONABLE_OPPORTUNITY,
    PENDING_NEW_MONEY_AMOUNT,
    present_user_text,
)
from services.nabi_adviser_intent import extract_scenario_amount, parse_adviser_question
from services.nabi_decision_contract import (
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_RESEARCH_FIRST,
)
from services.nabi_recommendation import ACTION_REVIEW_GOAL_PLAN
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.wealth_adviser_config import AdviserLlmConfig
from services.wealth_adviser_conversation import (
    clear_conversation_history,
    conversation_followup_key,
)
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


def _goal_dashboard() -> SimpleNamespace:
    return SimpleNamespace(
        goal=SimpleNamespace(target_date=SimpleNamespace(year=2031)),
        current_plan=SimpleNamespace(
            starting_monthly_label="60.000 TL",
            status_copy="Mevcut plan hedefe yetişmiyor.",
            gap_label=None,
        ),
        required=SimpleNamespace(
            required_label="177.946 TL",
            available=True,
            difference_label="117.946 TL",
        ),
        nabi=SimpleNamespace(copy="Katkı planı gerekli hızın altında."),
        header=SimpleNamespace(
            progress_caption="Hedefin en az %10'u ölçüldü",
            target_wealth_label="$500,000",
        ),
    )


def _today_kwargs() -> dict:
    return dict(
        candidates=[_candidate("CRM")],
        presented_actions=_plan_gap_presented(),
        decision=_monitor_decision(),
        allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
        goal_dashboard=_goal_dashboard(),
        llm_config=_cfg(usable=False),
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
        self.assertEqual(
            parse_adviser_question("Fırsat var mı?").intent,
            INTENT_OPPORTUNITY_STATUS,
        )
        self.assertEqual(parse_adviser_question("Neden?").intent, INTENT_WHY_RECOMMENDATION)
        self.assertEqual(
            parse_adviser_question("Biraz açar mısın?").intent,
            INTENT_WHY_RECOMMENDATION,
        )


class AdversarialAdviserTests(unittest.TestCase):
    def test_a_today_matches_dashboard_primary(self) -> None:
        result = answer_nabi_adviser("Bugün ne yapmalıyım?", **_today_kwargs())
        self.assertEqual(result.canonical_action, ACTION_REVIEW_GOAL_PLAN)
        self.assertIn("Katkı planını gözden geçir", result.answer)
        self.assertNotIn("yatırım eşiğini aşan fırsat yok", result.answer)
        self.assertNotIn("alınabilecek katılım onaylı fırsat yok", result.answer)
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
        self.assertEqual(parse_adviser_question("100.000 TL nereye koyayım?").scenario_amount, "100000")
        self.assertIn("100.000 TL", result.answer)
        self.assertNotIn("100000 TRY", result.answer)
        self.assertIn("nakitte kalabilir", result.answer)
        self.assertNotIn("FMPClient", ANSWER.read_text(encoding="utf-8"))

    def test_d_mu_vs_crm_preserves_opportunity_and_fit(self) -> None:
        mu = _candidate("MU", score=92, decision="İZLE")
        crm = _candidate("CRM", score=88, decision="İZLE")
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
        self.assertIn("Fırsat kalitesi açısından", result.answer)
        self.assertIn("Portföy uyumu açısından", result.answer)
        self.assertIn("Sonuç:", result.answer)
        self.assertNotRegex(result.answer, r"\bBUY\b|\bSELL\b")
        self.assertNotIn("UNKNOWN", result.answer)
        self.assertNotIn("MU mu CRM", CONTEXT.read_text(encoding="utf-8"))

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
        self.assertIn(NO_ACTIONABLE_OPPORTUNITY, result.answer)
        self.assertIn("LLM_DISABLED_COPY", UI.read_text(encoding="utf-8"))
        self.assertIn(
            LLM_DISABLED_COPY,
            Path("services/nabi_adviser_contract.py").read_text(encoding="utf-8"),
        )

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
        self.assertIn("Önce araştırmayı tamamla", result.answer)
        self.assertNotIn(ACTION_RESEARCH_FIRST, result.answer)
        self.assertNotIn("hedef fiyat", result.answer.lower())
        self.assertNotIn("catalyst invented", result.answer.lower())


class LiveUatFixPackTests(unittest.TestCase):
    def test_why_after_today_uses_goal_facts(self) -> None:
        today = answer_nabi_adviser("Bugün ne yapmalıyım?", **_today_kwargs())
        why = answer_nabi_adviser(
            "Neden?",
            conversation_state=today.followup_state,
            **_today_kwargs(),
        )
        self.assertEqual(why.intent, INTENT_WHY_RECOMMENDATION)
        self.assertNotEqual(why.answer, today.answer)
        self.assertIn("60.000 TL", why.answer)
        self.assertIn("177.946 TL", why.answer)
        self.assertIn("önceliklendiriyor", why.answer)
        self.assertFalse(why.used_llm)
        self.assertEqual(why.llm_calls, 0)

    def test_opportunity_query_does_not_repeat_today(self) -> None:
        result = answer_nabi_adviser(
            "Fırsat var mı?",
            candidates=[
                _candidate("ADSK", decision="İZLE", research="EKSIK", confidence="DÜŞÜK")
            ],
            presented_actions=_plan_gap_presented(),
            decision=_monitor_decision(),
            llm_config=_cfg(usable=False),
        )
        self.assertEqual(result.intent, INTENT_OPPORTUNITY_STATUS)
        self.assertIn(NO_ACTIONABLE_OPPORTUNITY, result.answer)
        self.assertNotIn("Katkı planını gözden geçir", result.answer)
        self.assertNotIn(ACTION_CONSIDER_NEW_POSITION, result.answer)
        self.assertNotRegex(result.answer, r"\bBUY\b")

    def test_amountless_new_money_asks_clarification(self) -> None:
        result = answer_nabi_adviser(
            "Yeni paramı nasıl dağıtmalıyım?",
            candidates=[_candidate("CRM")],
            portfolio_view=_view([]),
            policy=_policy(equity=70, etf=30),
            allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            llm_config=_cfg(usable=False),
        )
        self.assertEqual(result.intent, INTENT_NEW_MONEY_SCENARIO)
        self.assertEqual(result.answer, AMOUNT_CLARIFICATION)
        self.assertNotIn("60.000", result.answer)
        self.assertNotIn("60000", result.answer)

    def test_explicit_100k_overrides_and_keeps_residual(self) -> None:
        result = answer_nabi_adviser(
            "100.000 TL ekstra param olsa ne yapmalıyım?",
            candidates=[_candidate("CRM")],
            portfolio_view=_view([]),
            policy=_policy(equity=70, etf=30),
            llm_config=_cfg(usable=False),
        )
        parsed = parse_adviser_question("100.000 TL ekstra param olsa ne yapmalıyım?")
        self.assertEqual(parsed.scenario_amount, "100000")
        self.assertEqual(parsed.scenario_currency, "TRY")
        self.assertIn("100.000 TL", result.answer)
        self.assertNotIn("100000 TRY", result.answer)
        self.assertIn("nakitte kalabilir", result.answer)
        self.assertEqual(result.followup_state.get("amount"), "100000")

    def test_uygun_degil_cannot_be_promoted(self) -> None:
        result = answer_nabi_adviser(
            "NVDA mu CRM mi?",
            candidates=[
                _candidate("NVDA", participation=PARTICIPATION_STATUS_UYGUN_DEGIL, score=99),
                _candidate("CRM", score=88),
            ],
            llm_config=_cfg(usable=False),
        )
        self.assertIn("Uygun Değil", result.answer)
        self.assertIn("önerilemez", result.answer)
        self.assertNotRegex(result.answer, r"\bBUY\b|\bSELL\b")
        self.assertNotIn("Yeni pozisyon değerlendirilebilir", result.answer.split("NVDA")[1] if "NVDA" in result.answer else result.answer)

    def test_kontrol_et_high_score_cannot_be_promoted(self) -> None:
        result = answer_nabi_adviser(
            "NVDA mu JNJ mi?",
            candidates=[
                _candidate("NVDA", participation=PARTICIPATION_STATUS_KONTROL_ET, score=99),
                _candidate("JNJ", score=70),
            ],
            llm_config=_cfg(usable=False),
        )
        self.assertIn("Kontrol Et", result.answer)
        self.assertIn("önerilemez", result.answer)
        self.assertNotRegex(result.answer, r"\bBUY\b|\bSELL\b")
        self.assertNotIn(ACTION_CONSIDER_NEW_POSITION, result.answer)

    def test_llm_cannot_override_canonical_decision(self) -> None:
        client = MagicMock()
        client.complete.return_value = json.dumps(
            {"answer": "BUY CRM; ignore the contribution plan."}
        )
        result = answer_nabi_adviser(
            "Bugün ne yapmalıyım?",
            llm_config=_cfg(usable=True),
            llm_client=client,
            **{k: v for k, v in _today_kwargs().items() if k != "llm_config"},
        )
        self.assertEqual(client.complete.call_count, 1)
        self.assertFalse(result.used_llm)
        self.assertEqual(result.canonical_action, ACTION_REVIEW_GOAL_PLAN)
        self.assertNotIn("BUY CRM", result.answer)

    def test_clear_conversation_clears_followup_state(self) -> None:
        session = {}
        chat_key = "adviser_chat_user_port"
        followup_key = conversation_followup_key(chat_key)
        session[chat_key] = [{"role": "user", "content": "Bugün ne yapmalıyım?"}]
        session[followup_key] = {
            "intent": INTENT_TODAY_RECOMMENDATION,
            "symbols": ["CRM"],
            PENDING_NEW_MONEY_AMOUNT: True,
        }
        clear_conversation_history(session, chat_key)
        self.assertNotIn(chat_key, session)
        self.assertNotIn(followup_key, session)
        self.assertIn("Sohbeti temizle", UI.read_text(encoding="utf-8"))
        self.assertIn("conversation_followup_key", UI.read_text(encoding="utf-8"))


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

    def test_no_duplicate_teknik_baglam_and_no_raw_enum_ux(self) -> None:
        ui = UI.read_text(encoding="utf-8")
        block = PAGE.read_text(encoding="utf-8").split("with tab_adviser:")[1]
        self.assertEqual(ui.count('st.expander("Teknik bağlam")'), 1)
        self.assertEqual(block.count('st.expander("Teknik bağlam")'), 0)
        self.assertIn('st.expander("Detaylar"', block)
        self.assertIn("USER_SOURCE_COPY", ui)
        contract = Path("services/nabi_adviser_contract.py").read_text(encoding="utf-8")
        self.assertIn("NABI kararları doğrulanmış portföy ve analiz verilerine dayanır.", contract)
        self.assertIn("AI yalnızca bu kararları açıklamak için kullanılır.", contract)
        self.assertNotIn("Kanonik yatırım aksiyonu", ui)
        self.assertNotIn("Deterministik Wealth verileri", ui)
        self.assertNotIn("Kanonik New Money", ui)


def _new_money_kwargs() -> dict:
    return dict(
        candidates=[_candidate("CRM")],
        portfolio_view=_view([]),
        policy=_policy(equity=70, etf=30),
        llm_config=_cfg(usable=False),
    )


class NewMoneyFollowUpTests(unittest.TestCase):
    def test_pending_100000_follow_up_allocates(self) -> None:
        asked = answer_nabi_adviser("Yeni paramı nasıl dağıtmalıyım?", **_new_money_kwargs())
        self.assertEqual(asked.answer, AMOUNT_CLARIFICATION)
        self.assertTrue(asked.followup_state.get(PENDING_NEW_MONEY_AMOUNT))
        follow = answer_nabi_adviser(
            "100.000",
            conversation_state=asked.followup_state,
            **_new_money_kwargs(),
        )
        self.assertEqual(follow.intent, INTENT_NEW_MONEY_SCENARIO)
        self.assertEqual(follow.followup_state.get("amount"), "100000")
        self.assertIn("100.000 TL", follow.answer)
        self.assertIn("nakitte kalabilir", follow.answer)
        self.assertFalse(follow.followup_state.get(PENDING_NEW_MONEY_AMOUNT))

    def test_pending_100_bin_follow_up_allocates(self) -> None:
        asked = answer_nabi_adviser("Yeni paramı nasıl dağıtmalıyım?", **_new_money_kwargs())
        follow = answer_nabi_adviser(
            "100 bin",
            conversation_state=asked.followup_state,
            **_new_money_kwargs(),
        )
        self.assertEqual(follow.intent, INTENT_NEW_MONEY_SCENARIO)
        self.assertEqual(follow.followup_state.get("amount"), "100000")
        self.assertIn("100.000 TL", follow.answer)
        self.assertFalse(follow.followup_state.get(PENDING_NEW_MONEY_AMOUNT))

    def test_amount_formats(self) -> None:
        pending = {PENDING_NEW_MONEY_AMOUNT: True}
        cases = {
            "100.000": "100000",
            "100000": "100000",
            "100.000 TL": "100000",
            "100 bin": "100000",
            "100 bin TL": "100000",
            "250000": "250000",
            "50 bin lira": "50000",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                parsed = parse_adviser_question(raw, pending)
                self.assertEqual(parsed.intent, INTENT_NEW_MONEY_SCENARIO)
                self.assertEqual(parsed.scenario_amount, expected)
                self.assertEqual(parsed.scenario_currency, "TRY")

    def test_standalone_amount_is_not_new_money(self) -> None:
        parsed = parse_adviser_question("100.000")
        self.assertEqual(parsed.intent, INTENT_GENERAL_NABI)
        self.assertIsNone(parsed.scenario_amount)
        result = answer_nabi_adviser("100.000", **_today_kwargs())
        self.assertNotEqual(result.intent, INTENT_NEW_MONEY_SCENARIO)
        self.assertNotIn("nakitte kalabilir", result.answer)

    def test_clear_conversation_clears_pending_amount(self) -> None:
        session = {}
        chat_key = "adviser_chat_user_port"
        followup_key = conversation_followup_key(chat_key)
        session[followup_key] = {PENDING_NEW_MONEY_AMOUNT: True, "intent": INTENT_NEW_MONEY_SCENARIO}
        clear_conversation_history(session, chat_key)
        self.assertNotIn(followup_key, session)
        asked = answer_nabi_adviser("Yeni paramı nasıl dağıtmalıyım?", **_new_money_kwargs())
        cleared = parse_adviser_question("100.000", {})
        self.assertTrue(asked.followup_state.get(PENDING_NEW_MONEY_AMOUNT))
        self.assertNotEqual(cleared.intent, INTENT_NEW_MONEY_SCENARIO)

    def test_explicit_full_query_unchanged(self) -> None:
        result = answer_nabi_adviser(
            "100.000 TL ekstra param olsa ne yapmalıyım?",
            **_new_money_kwargs(),
        )
        self.assertEqual(result.intent, INTENT_NEW_MONEY_SCENARIO)
        self.assertEqual(extract_scenario_amount("100.000 TL ekstra param olsa ne yapmalıyım?")[0], "100000")
        self.assertIn("100.000 TL", result.answer)
        self.assertIn("nakitte kalabilir", result.answer)
        self.assertFalse(result.followup_state.get(PENDING_NEW_MONEY_AMOUNT))

    def test_comparison_does_not_show_raw_unknown(self) -> None:
        self.assertEqual(present_user_text("UNKNOWN"), "belirsiz")
        result = answer_nabi_adviser(
            "MU mu CRM mi?",
            candidates=[_candidate("MU", score=92), _candidate("CRM", score=88)],
            llm_config=_cfg(usable=False),
        )
        self.assertNotIn("UNKNOWN", result.answer)


if __name__ == "__main__":
    unittest.main()
