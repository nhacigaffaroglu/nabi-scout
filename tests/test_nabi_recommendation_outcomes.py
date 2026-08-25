from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from services.nabi_decision_contract import (
    ACTION_BLOCKED_PARTICIPATION,
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    ACTION_NO_ACTION,
    ACTION_RESEARCH_FIRST,
    ACTION_WAIT,
    ACTION_WATCH,
    DecisionAuditRecord,
)
from services.nabi_decision_orchestrator import (
    build_nabi_decision_v3,
    evaluate_candidate_investment,
)
from services.nabi_opportunity_comparison import best_deploy_comparison
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.nabi_recommendation import (
    ACTION_REVIEW_GOAL_PLAN,
    build_nabi_recommendation,
)
from services.nabi_recommendation_history_contract import (
    AUTO_POLICY_LEARNING,
    INTERPRET_INVESTMENT_MEASURED,
    INTERPRET_NON_DEPLOYMENT,
    INTERPRET_NOT_INVESTMENT,
    INTERPRET_OBSERVATION_ONLY,
    OUTCOME_NEGATIVE,
    OUTCOME_POSITIVE,
    OUTCOME_UNKNOWN,
    OUTCOME_WINDOWS,
    POLICY_LEARNING_STATE,
    apply_outcome_to_policy,
    logical_event_identity_from_audit,
)
from services.nabi_recommendation_history_presentation import (
    TRACKING_READY,
    present_history_rows,
    present_tracking_status,
)
from services.nabi_recommendation_history_service import record_recommendation
from services.nabi_recommendation_history_store import InMemoryRecommendationHistoryStore
from services.nabi_recommendation_outcome_service import (
    DictPriceBook,
    PricePoint,
    observe_matured_windows,
    observe_window,
)
from services.nabi_recommendation_performance import (
    investment_failure_count,
    summarize_outcomes,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.wealth_new_money_allocation import (
    REASON_STRONG_CANDIDATE,
    AllocationPlan,
)
from tests.test_nabi_decision_v3 import (
    NOW,
    _candidate,
    _monitor_decision,
    _plan,
    _plan_gap_presented,
    _rec,
    _thesis,
)

HOME = Path("components/nabi_home_dashboard.py")
TODAY = Path("services/nabi_today_presentation.py")
FIRSAT = Path("pages/5_Firsatlar.py")
CENTER_UI = Path("components/opportunity_center_ui.py")
SCORE = Path("services/nabi_score_v4.py")
HISTORY = Path("services/nabi_recommendation_history_service.py")
OUTCOME = Path("services/nabi_recommendation_outcome_service.py")


def _audit(**overrides) -> DecisionAuditRecord:
    payload = dict(
        recommendation_id="rec-1",
        generated_at="2026-08-25T07:00:00+00:00",
        symbol="CRM",
        final_action=ACTION_RESEARCH_FIRST,
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_completeness="LOW",
        decision_class="GÜÇLÜ ADAY",
        nabi_score=90.0,
        timing_state="UNKNOWN",
        portfolio_fit="GOOD_FIT",
        wealth_action=ACTION_REVIEW_GOAL_PLAN,
        reason_codes=("EVIDENCE_LOW", ACTION_REVIEW_GOAL_PLAN),
        evidence_references=(),
        persisted=False,
        logical_event_id="",
    )
    payload.update(overrides)
    return DecisionAuditRecord(**payload)


def _book(symbol: str, day: str, price: float, currency: str = "USD") -> DictPriceBook:
    return DictPriceBook(
        {
            (symbol, day): PricePoint(
                price, currency, as_of=day, source_reference=f"fixture:{symbol}:{day}"
            )
        }
    )


class HistoryIdempotencyTests(unittest.TestCase):
    def test_a_same_recommendation_recorded_once(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        base = _audit()
        for index in range(10):
            audit = replace(
                base,
                recommendation_id=f"rec-{index}",
                generated_at=f"2026-08-25T07:00:{index:02d}+00:00",
            )
            record_recommendation(audit, store)
        self.assertEqual(len(store.list_records()), 1)
        self.assertEqual(store.list_records()[0].recommendation_id, "rec-0")

    def test_b_material_action_change_is_new_event(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        first = record_recommendation(_audit(), store)
        second = record_recommendation(
            _audit(
                recommendation_id="rec-2",
                final_action=ACTION_CONSIDER_NEW_POSITION,
                research_completeness="HIGH",
                timing_state="FAVORABLE",
                reason_codes=("DEPLOY_NEW",),
            ),
            store,
        )
        self.assertEqual(len(store.list_records()), 2)
        self.assertNotEqual(first.logical_event_id, second.logical_event_id)

    def test_c_participation_change_preserves_old_event(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        old = record_recommendation(_audit(), store)
        blocked = evaluate_candidate_investment(
            _candidate("CRM", participation=PARTICIPATION_STATUS_UYGUN_DEGIL),
            now=NOW,
        )
        current = record_recommendation(
            _audit(
                recommendation_id="rec-blocked",
                final_action=blocked.final_action,
                participation_status=blocked.participation_status,
                reason_codes=blocked.reason_codes,
            ),
            store,
        )
        self.assertEqual(old.final_action, ACTION_RESEARCH_FIRST)
        self.assertEqual(current.final_action, ACTION_BLOCKED_PARTICIPATION)
        self.assertEqual(len(store.list_records()), 2)
        self.assertEqual(store.list_records()[0].recommendation_id, old.recommendation_id)


class OutcomeInterpretationTests(unittest.TestCase):
    def test_d_blocked_positive_return_is_not_investment_failure(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        record = record_recommendation(
            _audit(
                final_action=ACTION_BLOCKED_PARTICIPATION,
                participation_status="Kontrol Et",
            ),
            store,
            price_at_recommendation=100.0,
            price_currency="USD",
        )
        prices = _book("CRM", "2026-09-01", 150.0)
        outcome = observe_window(
            record, "7D", as_of=date(2026, 9, 1), prices=prices, store=store
        )
        self.assertAlmostEqual(outcome.return_pct or 0.0, 50.0)
        self.assertEqual(outcome.interpretation, INTERPRET_NOT_INVESTMENT)
        self.assertEqual(outcome.outcome_state, OUTCOME_UNKNOWN)
        self.assertEqual(investment_failure_count(store.list_outcomes()), 0)

    def test_e_research_first_is_observation_only(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        record = record_recommendation(
            _audit(),
            store,
            price_at_recommendation=100.0,
            price_currency="USD",
        )
        prices = _book("CRM", "2026-09-01", 130.0)
        outcome = observe_window(
            record, "7D", as_of=date(2026, 9, 1), prices=prices, store=store
        )
        self.assertAlmostEqual(outcome.return_pct or 0.0, 30.0)
        self.assertEqual(outcome.interpretation, INTERPRET_OBSERVATION_ONLY)
        self.assertEqual(investment_failure_count((outcome,)), 0)
        summary = summarize_outcomes(store.list_records(), (outcome,))
        research_buckets = [
            bucket for bucket in summary.buckets if bucket.action == ACTION_RESEARCH_FIRST
        ]
        self.assertTrue(research_buckets)
        self.assertFalse(research_buckets[0].investment_evaluated)

    def test_f_consider_return_is_calculated(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        record = record_recommendation(
            _audit(final_action=ACTION_CONSIDER_NEW_POSITION),
            store,
            price_at_recommendation=80.0,
            price_currency="USD",
        )
        prices = _book("CRM", "2026-09-01", 88.0)
        outcome = observe_window(
            record, "7D", as_of=date(2026, 9, 1), prices=prices, store=store
        )
        self.assertAlmostEqual(outcome.return_pct, 10.0)
        self.assertEqual(outcome.outcome_state, OUTCOME_POSITIVE)
        self.assertEqual(outcome.interpretation, INTERPRET_INVESTMENT_MEASURED)

    def test_g_missing_observation_price_is_unknown(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        record = record_recommendation(
            _audit(final_action=ACTION_CONSIDER_NEW_POSITION),
            store,
            price_at_recommendation=80.0,
            price_currency="USD",
        )
        outcome = observe_window(
            record,
            "7D",
            as_of=date(2026, 9, 1),
            prices=DictPriceBook({}),
            store=store,
        )
        self.assertIsNone(outcome.return_pct)
        self.assertEqual(outcome.outcome_state, OUTCOME_UNKNOWN)

    def test_h_mixed_currency_is_unknown(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        record = record_recommendation(
            _audit(final_action=ACTION_CONSIDER_NEW_POSITION),
            store,
            price_at_recommendation=100.0,
            price_currency="USD",
        )
        prices = _book("CRM", "2026-09-01", 100.0, currency="EUR")
        outcome = observe_window(
            record, "7D", as_of=date(2026, 9, 1), prices=prices, store=store
        )
        self.assertIsNone(outcome.return_pct)
        self.assertEqual(outcome.outcome_state, OUTCOME_UNKNOWN)

    def test_i_seven_day_does_not_create_later_windows(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        record = record_recommendation(
            _audit(final_action=ACTION_CONSIDER_TOP_UP),
            store,
            price_at_recommendation=10.0,
            price_currency="USD",
        )
        prices = DictPriceBook(
            {
                ("CRM", "2026-09-01"): PricePoint(
                    11.0, "USD", as_of="2026-09-01", source_reference="fixture"
                ),
                ("CRM", "2026-09-24"): PricePoint(
                    12.0, "USD", as_of="2026-09-24", source_reference="fixture"
                ),
            }
        )
        observe_window(record, "7D", as_of=date(2026, 9, 1), prices=prices, store=store)
        self.assertIsNotNone(store.find_outcome(record.recommendation_id, "7D"))
        self.assertIsNone(store.find_outcome(record.recommendation_id, "30D"))
        self.assertIsNone(store.find_outcome(record.recommendation_id, "90D"))
        self.assertIsNone(store.find_outcome(record.recommendation_id, "365D"))
        mature = observe_matured_windows(
            record, as_of=date(2026, 9, 1), prices=prices, store=store
        )
        self.assertEqual(tuple(item.window for item in mature), ("7D",))

    def test_j_outcomes_cannot_mutate_policy(self) -> None:
        before = CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT
        score_before = SCORE.read_text(encoding="utf-8")
        self.assertFalse(AUTO_POLICY_LEARNING)
        self.assertEqual(POLICY_LEARNING_STATE, "DISABLED")
        with self.assertRaisesRegex(RuntimeError, "DISABLED"):
            apply_outcome_to_policy(return_pct=50.0)
        self.assertEqual(CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT, before)
        self.assertEqual(SCORE.read_text(encoding="utf-8"), score_before)

    def test_k_dashboard_refresh_does_not_persist(self) -> None:
        for path in (HOME, TODAY, FIRSAT, CENTER_UI):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("record_recommendation", source)
            self.assertNotIn("record_decision_v3", source)
        self.assertIn("present_tracking_status(None)", TODAY.read_text(encoding="utf-8"))
        self.assertIn(TRACKING_READY, HOME.read_text(encoding="utf-8") + TODAY.read_text(encoding="utf-8") + CENTER_UI.read_text(encoding="utf-8") + Path("services/nabi_recommendation_history_presentation.py").read_text(encoding="utf-8"))

    def test_l_opportunity_vs_deployment_remains(self) -> None:
        mu = _candidate("MU", score=92)
        crm = _candidate("CRM", score=88)
        portfolio = SimpleNamespace(
            priced_positions=(SimpleNamespace(symbol="MU", weight_pct=25.0),)
        )
        plan = _plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new"))
        view = build_nabi_decision_v3(
            candidates=[mu, crm],
            theses={"MU": _thesis("MU"), "CRM": _thesis("CRM")},
            portfolio_view=portfolio,
            allocation=plan,
            decision=_monitor_decision(),
            valuation_complete=True,
            now=NOW,
        )
        rec = build_nabi_recommendation(
            candidates=[mu, crm],
            portfolio_view=portfolio,
            allocation=plan,
            valuation_complete=True,
        )
        self.assertEqual(view.opportunity_leader, "MU")
        self.assertEqual(best_deploy_comparison(rec.comparisons).symbol, "CRM")
        self.assertEqual(view.deployment_symbol, "CRM")
        self.assertEqual(view.final_action, ACTION_CONSIDER_NEW_POSITION)


class ActionAwareAndSummaryTests(unittest.TestCase):
    def test_watch_and_wait_are_non_deployment_observations(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        watch = record_recommendation(
            _audit(final_action=ACTION_WATCH, recommendation_id="watch"),
            store,
            price_at_recommendation=50.0,
            price_currency="USD",
        )
        wait = record_recommendation(
            _audit(final_action=ACTION_WAIT, recommendation_id="wait", symbol="MU"),
            store,
            price_at_recommendation=50.0,
            price_currency="USD",
        )
        prices = DictPriceBook(
            {
                ("CRM", "2026-09-01"): PricePoint(55.0, "USD", as_of="2026-09-01", source_reference="f"),
                ("MU", "2026-09-01"): PricePoint(45.0, "USD", as_of="2026-09-01", source_reference="f"),
            }
        )
        watch_out = observe_window(watch, "7D", as_of=date(2026, 9, 1), prices=prices, store=store)
        wait_out = observe_window(wait, "7D", as_of=date(2026, 9, 1), prices=prices, store=store)
        self.assertEqual(watch_out.interpretation, INTERPRET_NON_DEPLOYMENT)
        self.assertEqual(wait_out.interpretation, INTERPRET_NON_DEPLOYMENT)
        self.assertEqual(wait_out.outcome_state, OUTCOME_NEGATIVE)

    def test_no_action_is_observation_only(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        record = record_recommendation(
            _audit(final_action=ACTION_NO_ACTION),
            store,
            price_at_recommendation=20.0,
            price_currency="USD",
        )
        prices = _book("CRM", "2026-09-01", 21.0)
        outcome = observe_window(record, "7D", as_of=date(2026, 9, 1), prices=prices, store=store)
        self.assertEqual(outcome.interpretation, INTERPRET_OBSERVATION_ONLY)

    def test_windows_are_canonical(self) -> None:
        self.assertEqual(OUTCOME_WINDOWS, ("7D", "30D", "90D", "365D"))

    def test_summary_marks_small_samples_and_no_global_score(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        record = record_recommendation(
            _audit(final_action=ACTION_CONSIDER_NEW_POSITION),
            store,
            price_at_recommendation=100.0,
            price_currency="USD",
        )
        prices = _book("CRM", "2026-09-01", 110.0)
        outcome = observe_window(record, "7D", as_of=date(2026, 9, 1), prices=prices, store=store)
        summary = summarize_outcomes(store.list_records(), (outcome,))
        self.assertEqual(summary.auto_policy_learning, "DISABLED")
        self.assertIn("does not prove causality", summary.limitation)
        self.assertTrue(all(bucket.small_sample for bucket in summary.buckets if bucket.count))
        self.assertFalse(hasattr(summary, "intelligence_score"))

    def test_history_presentation_answers_what_when_why_outcome(self) -> None:
        store = InMemoryRecommendationHistoryStore()
        record = record_recommendation(
            _audit(),
            store,
            why="Halal-approved but evidence is LOW.",
            price_at_recommendation=100.0,
            price_currency="USD",
        )
        prices = _book("CRM", "2026-09-01", 101.0)
        outcome = observe_window(record, "7D", as_of=date(2026, 9, 1), prices=prices, store=store)
        lines = "\n".join(present_history_rows((record,), (outcome,)))
        self.assertIn("RESEARCH_FIRST", lines)
        self.assertIn("2026-08-25", lines)
        self.assertIn("Why:", lines)
        self.assertIn("7D", lines)
        self.assertIn("mature", lines)
        self.assertTrue(present_tracking_status(store).startswith("Latest recorded recommendation"))
        self.assertEqual(present_tracking_status(None), TRACKING_READY)

    def test_identity_ignores_generated_at(self) -> None:
        first = logical_event_identity_from_audit(_audit())
        second = logical_event_identity_from_audit(
            _audit(generated_at="2026-08-26T00:00:00+00:00", recommendation_id="other")
        )
        self.assertEqual(first, second)

    def test_no_provider_coupling(self) -> None:
        for path in (HISTORY, OUTCOME):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("FMPClient", source)
            self.assertNotIn("openai", source.lower())


class FinalProductUATTests(unittest.TestCase):
    def test_halal_first_and_participation_fail_closed(self) -> None:
        item = evaluate_candidate_investment(
            _candidate("META", participation="Kontrol Et", score=99),
            now=NOW,
        )
        self.assertEqual(item.final_action, ACTION_BLOCKED_PARTICIPATION)

    def test_research_fail_closed(self) -> None:
        item = evaluate_candidate_investment(
            _candidate("CRM", score=95, confidence="DÜŞÜK"),
            now=NOW,
        )
        self.assertEqual(item.final_action, ACTION_RESEARCH_FIRST)
        self.assertNotEqual(item.final_action, ACTION_CONSIDER_NEW_POSITION)

    def test_goal_priority_and_residual_cash(self) -> None:
        view = build_nabi_decision_v3(
            candidates=[_candidate("CRM")],
            theses={"CRM": _thesis("CRM")},
            allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            presented_actions=_plan_gap_presented(),
            decision=_monitor_decision(),
            valuation_complete=True,
            now=NOW,
        )
        self.assertEqual(view.dashboard_primary, ACTION_REVIEW_GOAL_PLAN)
        plan = _plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new"))
        self.assertIsInstance(plan, AllocationPlan)
        self.assertGreater(plan.residual_cash, Decimal("0"))
        self.assertLess(plan.total_allocated, plan.input_amount)

    def test_auditability_and_tracking_ready(self) -> None:
        view = build_nabi_decision_v3(candidates=[_candidate("JNJ")], now=NOW)
        self.assertTrue(view.audit.recommendation_id)
        self.assertTrue(view.audit.logical_event_id)
        self.assertFalse(view.audit.persisted)
        self.assertFalse(view.persisted)
        self.assertIn("tracking_status", HOME.read_text(encoding="utf-8"))
        self.assertIn(
            TRACKING_READY,
            Path("services/nabi_recommendation_history_presentation.py").read_text(
                encoding="utf-8"
            ),
        )
        self.assertIn(
            "TRACKING_READY",
            Path("services/opportunity_center_presentation.py").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
