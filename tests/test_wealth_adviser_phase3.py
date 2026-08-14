import inspect
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from services.wealth_adviser_contract import (
    ADVISER_LLM_INPUT_SCHEMA_VERSION,
    ADVISER_SCHEMA_VERSION,
    AdviserValidationContext,
    PreferenceAssessmentStatus,
)
from services.wealth_adviser_conversation import (
    MAX_CONVERSATION_TURNS,
    append_conversation_turn,
    clear_adviser_session_state,
    clear_conversation_history,
    conversation_session_key,
    get_conversation_history,
)
from services.wealth_adviser_interpretation_service import WealthAdviserInterpretationService
from services.wealth_adviser_output_validator import validate_adviser_response
from services.wealth_adviser_preference_engine import (
    build_adviser_user_context,
    build_preference_assessments,
)
from services.wealth_adviser_profile_contract import (
    AdviserGoal,
    ConcentrationPreference,
    GoalType,
    InvestorProfile,
    InvestmentHorizon,
    RiskPreference,
)
from services.wealth_adviser_profile_service import WealthAdviserGoalService, WealthAdviserProfileService
from services.wealth_adviser_prompt import (
    build_llm_input_payload,
    build_llm_messages,
    payload_contains_forbidden_keys,
    validate_llm_input_payload_shape,
)
from services.wealth_adviser_service import WealthAdviserService
from services.wealth_adviser_contract import AdviserConversationTurn, AdviserResponse
from tests.test_wealth_adviser import _diagnostics, _full_health, _position, _view
from tests.test_wealth_adviser_llm import _brief, _valid_llm_json
from services.wealth_adviser_config import AdviserLlmConfig


def _concentrated_view():
    return _view(
        positions=[_position(symbol="AAPL", weight_pct=96.8, market_value=9680)],
        health=_full_health(
            largest_position_weight_pct=96.8,
            top3_concentration_pct=96.8,
            largest_asset_class_concentration_pct=96.8,
            cash_pct=3.2,
            invested_pct=96.8,
        ),
    )


def _profile(**overrides) -> InvestorProfile:
    defaults = dict(
        user_id="user-1",
        profile_version=1,
        investment_horizon=InvestmentHorizon.LONG.value,
        risk_preference="HIGH",
        liquidity_need=None,
        cash_preference=None,
        concentration_preference=None,
        income_need=None,
        experience_level=None,
        notes=None,
        created_at=None,
        updated_at=None,
    )
    defaults.update(overrides)
    return InvestorProfile(**defaults)


class InvestorProfileContractTests(unittest.TestCase):
    def test_unknown_fields_remain_unknown(self) -> None:
        profile = InvestorProfile.empty("user-1")
        self.assertIsNone(profile.investment_horizon)
        self.assertIn("investment_horizon", profile.missing_fields())

    def test_profile_serialization_deterministic(self) -> None:
        profile = _profile(concentration_preference=ConcentrationPreference.ACCEPT_HIGH.value)
        self.assertEqual(profile.to_dict(), profile.to_dict())


class PreferenceAssessmentTests(unittest.TestCase):
    def setUp(self) -> None:
        view = _concentrated_view()
        self.context = WealthAdviserService().build_context(
            view, _diagnostics(view), generated_from_snapshot_count=0
        )

    def test_concentration_preference_conflict(self) -> None:
        profile = _profile(concentration_preference=ConcentrationPreference.AVOID.value)
        assessments = build_preference_assessments(self.context, profile, ())
        codes = {item.code for item in assessments}
        self.assertIn("CONCENTRATION_PREF_CONFLICT", codes)
        conflict = next(item for item in assessments if item.code == "CONCENTRATION_PREF_CONFLICT")
        self.assertEqual(conflict.status, PreferenceAssessmentStatus.POTENTIAL_CONFLICT)

    def test_concentration_acceptance_alignment(self) -> None:
        profile = _profile(concentration_preference=ConcentrationPreference.ACCEPT_HIGH.value)
        assessments = build_preference_assessments(self.context, profile, ())
        codes = {item.code for item in assessments}
        self.assertIn("CONCENTRATION_ACCEPTANCE", codes)

    def test_missing_data_insufficient(self) -> None:
        from services.wealth_adviser_profile_contract import AdviserGoal, GoalType

        goal = AdviserGoal(
            id="goal-income-1",
            user_id="user-1",
            portfolio_id=None,
            goal_type=GoalType.INCOME.value,
            title="Gelir hedefi",
            target_date=None,
            target_amount=None,
            currency=None,
            priority=1,
            notes=None,
            active=True,
            created_at=None,
            updated_at=None,
        )
        assessments = build_preference_assessments(self.context, _profile(), (goal,))
        self.assertTrue(
            any(item.status == PreferenceAssessmentStatus.INSUFFICIENT_DATA for item in assessments)
        )

    def test_diagnostics_severity_unchanged_in_statements(self) -> None:
        profile = _profile(concentration_preference=ConcentrationPreference.ACCEPT_HIGH.value)
        assessments = build_preference_assessments(self.context, profile, ())
        combined = " ".join(item.statement for item in assessments).lower()
        self.assertNotIn("severity lowered", combined)
        self.assertNotIn("şiddet düşür", combined)


class MultiTurnConversationTests(unittest.TestCase):
    def test_history_scoped_and_bounded(self) -> None:
        session = {}
        key = conversation_session_key("user-a", "portfolio-a")
        for idx in range(MAX_CONVERSATION_TURNS + 4):
            append_conversation_turn(session, key, role="user", content=f"q{idx}")
        history = get_conversation_history(session, key)
        self.assertLessEqual(len(history), MAX_CONVERSATION_TURNS)
        self.assertEqual(history[-1].content, f"q{MAX_CONVERSATION_TURNS + 3}")

    def test_clear_history(self) -> None:
        session = {}
        key = conversation_session_key("user-a", "portfolio-a")
        append_conversation_turn(session, key, role="user", content="hello")
        clear_conversation_history(session, key)
        self.assertEqual(get_conversation_history(session, key), [])

    def test_cross_portfolio_keys_differ(self) -> None:
        self.assertNotEqual(
            conversation_session_key("user-a", "p1"),
            conversation_session_key("user-a", "p2"),
        )


class Phase3LlmFirewallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = _brief()
        self.context = self.brief.context

    def _response(self, **overrides) -> AdviserResponse:
        defaults = dict(
            answer="Safe summary.",
            key_points=(),
            referenced_finding_ids=(),
            limitations=(),
            follow_up_questions=(),
            safety_flags=(),
            model_name="test",
            generated_at="t",
            grounded=False,
        )
        defaults.update(overrides)
        return AdviserResponse(**defaults)

    def test_exact_trade_command_rejected(self) -> None:
        result = validate_adviser_response(
            self._response(answer="Buy AAPL now."),
            self.context,
        )
        self.assertFalse(result.valid)

    def test_exact_rebalance_instruction_rejected(self) -> None:
        result = validate_adviser_response(
            self._response(answer="AAPL'ı %40'a indir."),
            self.context,
        )
        self.assertFalse(result.valid)

    def test_specific_security_recommendation_rejected(self) -> None:
        result = validate_adviser_response(
            self._response(answer="VOO al."),
            self.context,
        )
        self.assertFalse(result.valid)

    def test_valid_option_level_guidance_accepted(self) -> None:
        result = validate_adviser_response(
            self._response(
                answer="Yeni katkıları farklı varlık sınıflarına yönlendirme seçeneğini değerlendirebilirsiniz.",
                options_to_consider=("Yeni katkıları çeşitlendirmeyi düşünün",),
            ),
            self.context,
        )
        self.assertTrue(result.valid)

    def test_unknown_goal_id_rejected(self) -> None:
        result = validate_adviser_response(
            self._response(relevant_goal_ids=("missing-goal",)),
            self.context,
            validation_context=AdviserValidationContext((), (), (), ()),
        )
        self.assertFalse(result.valid)

    def test_llm_input_v2_shape(self) -> None:
        payload = build_llm_input_payload(self.brief, user_question="Q").to_dict()
        self.assertEqual(payload["schema_version"], ADVISER_LLM_INPUT_SCHEMA_VERSION)
        self.assertTrue(validate_llm_input_payload_shape(payload))


class Phase3InterpretationTests(unittest.TestCase):
    def test_one_submit_one_call(self) -> None:
        brief = _brief()
        client = MagicMock()
        client.complete.return_value = _valid_llm_json(brief)
        service = WealthAdviserInterpretationService(
            config=AdviserLlmConfig(
                enabled=True,
                provider="openai",
                model="gpt-test",
                timeout_seconds=5,
                max_output_tokens=500,
                temperature=0.2,
                api_key="test-key",
            ),
            client=client,
        )
        service.interpret(brief, user_question="Follow up?")
        client.complete.assert_called_once()

    def test_follow_up_receives_history_in_payload(self) -> None:
        brief = _brief()
        client = MagicMock()
        client.complete.return_value = _valid_llm_json(brief)
        service = WealthAdviserInterpretationService(
            config=AdviserLlmConfig(
                enabled=True,
                provider="openai",
                model="gpt-test",
                timeout_seconds=5,
                max_output_tokens=500,
                temperature=0.2,
                api_key="test-key",
            ),
            client=client,
        )
        from services.wealth_adviser_contract import AdviserConversationTurn

        history = (
            AdviserConversationTurn(role="user", content="Yoğunlaşma bilinçli.", grounded=False),
            AdviserConversationTurn(
                role="assistant",
                content="Anladım, tercihiniz bağlam olarak not edildi.",
                grounded=True,
            ),
        )
        service.interpret(brief, user_question="En önemli trade-off?", conversation_history=history)
        sent_messages = client.complete.call_args.args[0]
        payload = json.loads(sent_messages[1]["content"])
        self.assertIn("UNTRUSTED_CONVERSATION_HISTORY", payload)
        self.assertEqual(len(payload["UNTRUSTED_CONVERSATION_HISTORY"]), 2)


class Phase3InvariantTests(unittest.TestCase):
    def test_profile_does_not_modify_portfolio_facts(self) -> None:
        view = _concentrated_view()
        service = WealthAdviserService()
        base_context = service.build_context(view, _diagnostics(view))
        user_context = build_adviser_user_context(
            profile=_profile(concentration_preference=ConcentrationPreference.ACCEPT_HIGH.value),
            goals=(),
            context=base_context,
        )
        enriched = service.build_context(
            view,
            _diagnostics(view),
            user_context=user_context,
        )
        self.assertEqual(enriched.portfolio.largest_position_pct, base_context.portfolio.largest_position_pct)
        self.assertEqual(enriched.findings, base_context.findings)

    def test_schema_version_bumped(self) -> None:
        self.assertEqual(ADVISER_SCHEMA_VERSION, "wealth-adviser-v3")


class Phase3UiStaticTests(unittest.TestCase):
    @staticmethod
    def _adviser_block() -> str:
        from pathlib import Path

        return Path("pages/10_Wealth.py").read_text(encoding="utf-8").split("with tab_adviser:")[1]

    def test_profile_save_form_present(self) -> None:
        block = self._adviser_block()
        self.assertIn("adviser_profile_form", block)
        self.assertIn("Profili kaydet", block)

    def test_chat_send_only_on_submit(self) -> None:
        block = self._adviser_block()
        self.assertIn("adviser_chat_form", block)
        self.assertIn("Gönder", block)
        self.assertNotIn(".interpret(", block.split("if send_message")[0])

    def test_conversation_key_scoped(self) -> None:
        block = self._adviser_block()
        self.assertIn("conversation_session_key", block)


class GoalServiceTests(unittest.TestCase):
    def test_create_goal_validates_type(self) -> None:
        service = WealthAdviserGoalService(MagicMock(), "user-1")
        with self.assertRaises(ValueError):
            service.create_goal(portfolio_id=None, goal_type="INVALID", title="X")


class Phase3ValidationGateTests(unittest.TestCase):
    def test_migration_profile_rls_and_unique_user(self) -> None:
        from pathlib import Path

        sql = Path("database/migration_wealth_adviser_phase3.sql").read_text(encoding="utf-8").lower()
        self.assertIn("unique (user_id)", sql)
        self.assertIn("user_id uuid not null", sql)
        self.assertIn("auth.uid() = user_id", sql)
        self.assertNotIn("to anon", sql)
        self.assertNotIn("service_role", sql)

    def test_migration_goal_composite_fk(self) -> None:
        from pathlib import Path

        phase1 = Path("database/migration_wealth_core_phase1.sql").read_text(encoding="utf-8")
        migration = Path("database/migration_wealth_adviser_phase3.sql").read_text(encoding="utf-8")
        self.assertIn("wealth_portfolios_user_id_id_uidx", phase1)
        self.assertIn("foreign key (user_id, portfolio_id)", migration)
        self.assertIn("references public.wealth_portfolios (user_id, id)", migration)

    def test_profile_repository_scopes_user_id(self) -> None:
        from repositories.wealth_investor_profile_repository import WealthInvestorProfileRepository

        source = inspect.getsource(WealthInvestorProfileRepository)
        self.assertIn('.eq("user_id", user_id)', source)
        self.assertNotIn("user_id = payload", source.lower())

    def test_goal_repository_scopes_user_id_on_update(self) -> None:
        from repositories.wealth_adviser_goal_repository import WealthAdviserGoalRepository

        source = inspect.getsource(WealthAdviserGoalRepository)
        self.assertIn('.eq("user_id", user_id)', source)
        self.assertIn('.eq("active", True)', source)

    def test_profile_invariance_across_risk_profiles(self) -> None:
        view = _concentrated_view()
        diagnostics = _diagnostics(view)
        service = WealthAdviserService()
        base = service.build_context(view, diagnostics)
        for risk in (RiskPreference.LOW.value, RiskPreference.HIGH.value):
            ctx = service.build_context(
                view,
                diagnostics,
                user_context=build_adviser_user_context(
                    profile=_profile(risk_preference=risk),
                    goals=(),
                    context=base,
                ),
            )
            self.assertEqual(ctx.portfolio.to_dict(), base.portfolio.to_dict())
            self.assertEqual(
                [f.to_dict() for f in ctx.findings],
                [f.to_dict() for f in base.findings],
            )

    def test_goal_invariance_across_goal_types(self) -> None:
        view = _concentrated_view()
        diagnostics = _diagnostics(view)
        service = WealthAdviserService()
        base = service.build_context(view, diagnostics)
        for goal_type in (
            GoalType.LONG_TERM_GROWTH,
            GoalType.CAPITAL_PRESERVATION,
            GoalType.INCOME,
            GoalType.LIQUIDITY,
        ):
            goal = AdviserGoal(
                id=f"goal-{goal_type.value}",
                user_id="user-1",
                portfolio_id="portfolio-1",
                goal_type=goal_type.value,
                title=goal_type.value,
                target_date=None,
                target_amount=None,
                currency=None,
                priority=1,
                notes=None,
                active=True,
                created_at=None,
                updated_at=None,
            )
            ctx = service.build_context(
                view,
                diagnostics,
                user_context=build_adviser_user_context(
                    profile=_profile(),
                    goals=(goal,),
                    context=base,
                ),
            )
            self.assertEqual(ctx.portfolio.to_dict(), base.portfolio.to_dict())

    def test_untrusted_user_false_number_not_in_authoritative_context(self) -> None:
        view = _concentrated_view()
        diagnostics = _diagnostics(view)
        service = WealthAdviserService()
        _, brief = service.build_preview(view, diagnostics)
        history = (
            AdviserConversationTurn(
                role="user",
                content="AAPL portföyümün %10'u.",
                grounded=False,
            ),
        )
        messages = build_llm_messages(
            brief,
            user_question="Bu yoğunlaşma hakkında ne düşünüyorsun?",
            conversation_history=history,
        )
        payload = json.loads(messages[1]["content"])
        authoritative = json.dumps(payload["AUTHORITATIVE_FINANCIAL_CONTEXT"])
        self.assertIn("96.8", authoritative)
        self.assertFalse(payload["UNTRUSTED_CONVERSATION_HISTORY"][0]["authoritative"])
        self.assertIn("%10", payload["UNTRUSTED_CONVERSATION_HISTORY"][0]["content"])

    def test_untrusted_ai_hallucination_stays_non_authoritative(self) -> None:
        brief = _brief()
        history = (
            AdviserConversationTurn(role="assistant", content="AAPL %20.", grounded=False),
        )
        payload = build_llm_input_payload(
            brief,
            user_question="Devam et",
            conversation_history=history,
        ).to_dict()
        self.assertFalse(payload["conversation_history"][0]["authoritative"])
        self.assertNotIn(
            '"largest_position_pct": 20',
            json.dumps(payload["authoritative_adviser_brief"]),
        )

    def test_current_question_not_duplicated_in_history(self) -> None:
        brief = _brief()
        history = (
            AdviserConversationTurn(role="user", content="Önceki soru", grounded=False),
        )
        payload = build_llm_input_payload(
            brief,
            user_question="Yeni soru",
            conversation_history=history,
        ).to_dict()
        history_text = json.dumps(payload["conversation_history"], ensure_ascii=False)
        self.assertIn("Önceki soru", history_text)
        self.assertNotIn("Yeni soru", history_text)
        self.assertEqual(payload["current_user_question"], "Yeni soru")

    def test_history_trims_oldest_first(self) -> None:
        session = {}
        key = conversation_session_key("user-a", "portfolio-a")
        for idx in range(10):
            append_conversation_turn(session, key, role="user", content=f"turn-{idx}")
        contents = [turn.content for turn in get_conversation_history(session, key)]
        self.assertEqual(len(contents), MAX_CONVERSATION_TURNS)
        self.assertEqual(contents[0], "turn-2")
        self.assertEqual(contents[-1], "turn-9")

    def test_logout_clears_adviser_session_keys(self) -> None:
        session = {
            "adviser_chat_u1_p1": [{"role": "user", "content": "hi"}],
            "adviser_response_u1_p1": {"answer": "x"},
            "other_key": 1,
        }
        clear_adviser_session_state(session)
        self.assertNotIn("adviser_chat_u1_p1", session)
        self.assertNotIn("adviser_response_u1_p1", session)
        self.assertIn("other_key", session)

    def test_llm_input_v3_section_labels(self) -> None:
        messages = build_llm_messages(_brief(), user_question="Q")
        payload = json.loads(messages[1]["content"])
        for label in (
            "AUTHORITATIVE_FINANCIAL_CONTEXT",
            "AUTHORITATIVE_COMPANY_INTELLIGENCE",
            "AUTHORITATIVE_INVESTMENT_THESIS",
            "AUTHORITATIVE_NABI_CONTEXT",
            "AUTHORITATIVE_PORTFOLIO_CONTEXT",
            "EXPLICIT_USER_PROFILE",
            "ACTIVE_GOALS",
            "DETERMINISTIC_CONFLICTS_AND_ASSESSMENTS",
            "UNTRUSTED_CONVERSATION_HISTORY",
            "CURRENT_USER_QUESTION",
        ):
            self.assertIn(label, payload)
        self.assertFalse(payload_contains_forbidden_keys(payload))

    def test_validator_rejects_profile_severity_override_claim(self) -> None:
        brief = _brief()
        result = validate_adviser_response(
            AdviserResponse(
                answer="Diagnostic severity lowered because of your preference.",
                key_points=(),
                referenced_finding_ids=(),
                limitations=(),
                follow_up_questions=(),
                safety_flags=(),
                model_name="test",
                generated_at="t",
                grounded=False,
            ),
            brief.context,
        )
        self.assertFalse(result.valid)

    def test_validator_rejects_missing_data_completion_claim(self) -> None:
        brief = _brief()
        result = validate_adviser_response(
            AdviserResponse(
                answer="Your high risk preference makes missing valuation data complete.",
                key_points=(),
                referenced_finding_ids=(),
                limitations=(),
                follow_up_questions=(),
                safety_flags=(),
                model_name="test",
                generated_at="t",
                grounded=False,
            ),
            brief.context,
        )
        self.assertFalse(result.valid)

    def test_profile_service_user_id_from_constructor(self) -> None:
        source = inspect.getsource(WealthAdviserProfileService.save_profile)
        self.assertIn("self.user_id", source)
        self.assertNotIn("st.session_state", source)

    def test_no_llm_on_profile_goal_clear_paths(self) -> None:
        from pathlib import Path

        block = Path("pages/10_Wealth.py").read_text(encoding="utf-8").split("with tab_adviser:")[1]
        self.assertNotIn(".interpret(", block.split("if save_profile")[0])
        self.assertNotIn(".interpret(", block.split("if add_goal")[0])
        self.assertNotIn(".interpret(", block.split('button("Sohbeti temizle"')[0])


if __name__ == "__main__":
    unittest.main()
