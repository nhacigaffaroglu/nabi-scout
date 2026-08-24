from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from components.portfolio_decision_center_ui import (
    CONTRIBUTION_PLAN_TITLE,
    HEALTHY_MESSAGE,
    ActionCenterPresentation,
    PresentedAction,
)
from services.candidate_pipeline_presentation import is_actionable_opportunity
from services.nabi_recommendation import (
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    ACTION_NO_ACTION,
    ACTION_RESEARCH_OPPORTUNITY,
    ACTION_REVIEW_GOAL_PLAN,
    ACTION_REVIEW_NEW_MONEY,
    FIT_POOR,
    NO_APPROVED_HALAL_OPPORTUNITY,
    RANKING_LIMITATION,
    SECTION_RECOMMENDATION,
    build_nabi_recommendation,
    opportunity_intelligence_summary,
    present_recommendation_card,
    rank_recommendation_opportunities,
    recommendation_halal_eligible,
)
from services.participation_intelligence_contract import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
)
from services.portfolio_decision_intelligence import (
    DecisionAction,
    DecisionActionStatus,
    DecisionCategory,
    DecisionPriority,
    PortfolioDecisionView,
)
from services.wealth_new_money_allocation import (
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_OVERWEIGHT_LAYER,
    AllocationPlan,
    AllocationRecommendation,
    AllocationSkip,
)

HOME = Path("components/nabi_home_dashboard.py")
TODAY = Path("services/nabi_today_presentation.py")
ENGINE = Path("services/nabi_recommendation.py")
FIRSATLAR = Path("pages/5_Firsatlar.py")
CENTER = Path("services/opportunity_center_presentation.py")
WEALTH = Path("pages/10_Wealth.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "TwelveData",
    "BorsaIstanbul",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    "capture_portfolio_snapshot",
    "save_planning_fx_schedule",
    "save_policy",
    ".insert(",
    ".upsert(",
    ".delete(",
)


def _candidate(
    symbol: str,
    *,
    decision: str = "GÜÇLÜ ADAY",
    participation: str = "Uygun",
    score: float = 88.0,
    price: float | None = 120.0,
    completeness: float | None = 88.0,
    research: str = "YENI",
) -> dict:
    return {
        "symbol": symbol,
        "company_name": symbol,
        "decision": decision,
        "participation_status": participation,
        "research_status": research,
        "nabi_score": score,
        "current_price": price,
        "data_completeness": completeness,
        "data_source": "scanner",
        "main_reason": "Kaliteli büyüme",
        "last_scanned_at": "2026-08-20T10:00:00+00:00" if completeness is not None else None,
    }


def _action(
    action_id: str,
    *,
    category: DecisionCategory,
    priority: DecisionPriority,
    title: str = "Konu",
) -> DecisionAction:
    return DecisionAction(
        id=action_id,
        category=category,
        priority=priority,
        title=title,
        explanation=title,
        evidence=(),
        status=DecisionActionStatus.OPEN,
    )


def _decision(*actions: DecisionAction, complete: bool = True) -> PortfolioDecisionView:
    rows = actions or (
        _action(
            "continue_observation",
            category=DecisionCategory.MONITOR,
            priority=DecisionPriority.INFO,
            title="Gözlem",
        ),
    )
    return PortfolioDecisionView(
        actions=rows,
        primary_action=rows[0],
        evidence_complete=complete,
        limitations=(),
        generated_from=("test",),
    )


def _plan_gap_presented() -> ActionCenterPresentation:
    return ActionCenterPresentation(
        heading="NABI Karar Merkezi",
        healthy=False,
        healthy_message=None,
        disclaimer="",
        visible_actions=(
            PresentedAction(
                id="contribution_plan_below_required",
                category_label="Hedef",
                priority_label="Yüksek",
                priority_tone="warning",
                title=CONTRIBUTION_PLAN_TITLE,
                explanation="2031 hedefi mevcut katkı planıyla yakalanamıyor.",
                evidence_lines=("Mevcut aylık katkı: 60,000 TL",),
                limitation=None,
                direction=None,
                options=(),
            ),
        ),
        hidden_count=0,
        evidence_summary=(),
        action_ids=("contribution_plan_below_required",),
        status_summary="konular",
        actionable_count=1,
        highest_severity_label="Yüksek",
    )


def _goal():
    return SimpleNamespace(
        current_plan=SimpleNamespace(starting_monthly_label="60,000 TL / ay"),
        required=SimpleNamespace(required_label="177,946 TL"),
        target_date_alternative=SimpleNamespace(reach_year=2035, reach_date_label="2035"),
    )


def _topup_plan() -> AllocationPlan:
    return AllocationPlan(
        input_amount=Decimal("60000"),
        currency="TRY",
        recommendations=(
            AllocationRecommendation(
                symbol="AAPL",
                existing_or_new="existing",
                layer="equity",
                decision=None,
                price=Decimal("180"),
                price_currency="USD",
                quantity=Decimal("1"),
                allocated_amount=Decimal("45000"),
                reason_code=REASON_EXISTING_HOLDING_TOPUP,
                reason_text="Mevcut pozisyon, açık katmanda tamamlanır.",
            ),
        ),
        total_allocated=Decimal("45000"),
        residual_cash=Decimal("15000"),
        skipped=(),
        limitations=(),
    )


class LiveStyleAndPrecedenceTests(unittest.TestCase):
    def test_goal_gap_and_no_opportunity_reviews_plan(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[],
            presented_actions=_plan_gap_presented(),
            goal_dashboard=_goal(),
            allocation=_topup_plan(),
            valuation_complete=True,
        )
        self.assertEqual(rec.action_code, ACTION_REVIEW_GOAL_PLAN)
        self.assertEqual(rec.opportunity_line, NO_APPROVED_HALAL_OPPORTUNITY)
        self.assertEqual(rec.confidence, CONFIDENCE_HIGH)
        self.assertIn("60,000", rec.evidence_refs[0])
        self.assertIn("177,946", rec.evidence_refs[1])

    def test_strong_halal_opportunity_good_fit_is_research_or_new(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[_candidate("MSFT", research="YENI")],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertEqual(rec.action_code, ACTION_RESEARCH_OPPORTUNITY)
        self.assertEqual(rec.symbol, "MSFT")
        self.assertEqual(rec.confidence, CONFIDENCE_MEDIUM)
        done = build_nabi_recommendation(
            candidates=[_candidate("MSFT", research="TAMAMLANDI")],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertEqual(done.action_code, ACTION_CONSIDER_NEW_POSITION)

    def test_kontrol_et_never_recommended(self) -> None:
        row = _candidate("META", participation="Kontrol Et", score=99.0)
        self.assertFalse(is_actionable_opportunity(row))
        self.assertFalse(recommendation_halal_eligible(row))
        rec = build_nabi_recommendation(
            candidates=[row],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertIsNone(rec.symbol)
        self.assertNotIn(rec.action_code, {ACTION_RESEARCH_OPPORTUNITY, ACTION_CONSIDER_NEW_POSITION})
        self.assertEqual(rank_recommendation_opportunities([row]), ())

    def test_uygun_degil_never_recommended(self) -> None:
        row = _candidate("HON", participation="Uygun Değil", score=95.0)
        rec = build_nabi_recommendation(
            candidates=[row],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertFalse(recommendation_halal_eligible(row))
        self.assertIsNone(rec.symbol)
        self.assertNotIn("HON", rec.opportunity_line)

    def test_poor_fit_is_not_primary_add(self) -> None:
        row = _candidate("AVGO", research="TAMAMLANDI")
        portfolio = SimpleNamespace(
            priced_positions=(SimpleNamespace(symbol="AVGO", weight_pct=25.0),)
        )
        rec = build_nabi_recommendation(
            candidates=[row],
            decision=_decision(),
            portfolio_view=portfolio,
            valuation_complete=True,
        )
        self.assertEqual(rec.portfolio_fit, FIT_POOR)
        self.assertNotIn(
            rec.action_code,
            {ACTION_RESEARCH_OPPORTUNITY, ACTION_CONSIDER_NEW_POSITION, ACTION_CONSIDER_TOP_UP},
        )
        self.assertIn("birincil ekleme değil", rec.opportunity_line)

    def test_no_opportunity_with_underweight_holding_reviews_new_money(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[],
            decision=_decision(),
            allocation=_topup_plan(),
            valuation_complete=True,
        )
        self.assertEqual(rec.action_code, ACTION_REVIEW_NEW_MONEY)
        self.assertEqual(rec.new_money.top_up_symbols, ("AAPL",))
        self.assertIn("AAPL", rec.new_money_line)

    def test_incomplete_valuation_is_safety_limitation(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[_candidate("MSFT")],
            decision=_decision(
                _action(
                    "incomplete_valuation",
                    category=DecisionCategory.DATA,
                    priority=DecisionPriority.HIGH,
                    title="Değerleme eksik",
                )
            ),
            valuation_complete=False,
        )
        self.assertEqual(rec.action_code, ACTION_NO_ACTION)
        self.assertEqual(rec.confidence, CONFIDENCE_LOW)
        self.assertIn("incomplete_valuation", rec.risk_flags)
        self.assertTrue(any("eksik" in item.casefold() for item in rec.limitations))

    def test_incomplete_research_reduces_confidence(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[_candidate("ADSK", research="YENI")],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertEqual(rec.action_code, ACTION_RESEARCH_OPPORTUNITY)
        self.assertEqual(rec.confidence, CONFIDENCE_MEDIUM)
        self.assertIn("incomplete_research", rec.risk_flags)

    def test_no_action_when_nothing_crosses_threshold(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertEqual(rec.action_code, ACTION_NO_ACTION)
        self.assertIn("işlem yok", rec.why_now.casefold())

    def test_allocation_is_not_forced_to_100_percent(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[],
            decision=_decision(),
            allocation=_topup_plan(),
            valuation_complete=True,
        )
        self.assertTrue(rec.new_money.leave_residual)
        self.assertTrue(rec.new_money.use_some)
        self.assertFalse(rec.new_money.use_all)
        self.assertFalse(rec.new_money.forced_full_allocation)
        self.assertEqual(rec.new_money.residual_label, "15000")

    def test_old_numeric_score_cannot_bypass_participation(self) -> None:
        trap = _candidate("TSM", participation="Kontrol Et", score=99.4)
        approved = _candidate("MU", score=72.0, decision="ADAY", completeness=80)
        ranked = rank_recommendation_opportunities([trap, approved])
        self.assertEqual([row["symbol"] for row in ranked], ["MU"])
        rec = build_nabi_recommendation(
            candidates=[trap, approved],
            presented_actions=_plan_gap_presented(),
            valuation_complete=True,
        )
        self.assertEqual(rec.action_code, ACTION_REVIEW_GOAL_PLAN)
        self.assertNotEqual(rec.symbol, "TSM")
        self.assertEqual(rec.symbol, "MU")

    def test_dashboard_and_firsatlar_reuse_same_object(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[],
            presented_actions=_plan_gap_presented(),
            goal_dashboard=_goal(),
            valuation_complete=True,
        )
        card = present_recommendation_card(rec)
        self.assertEqual(card.section_title, SECTION_RECOMMENDATION)
        self.assertEqual(card.opportunity, opportunity_intelligence_summary(rec))
        self.assertEqual(card.today, rec.summary)
        self.assertEqual(card.why, rec.why_now)
        self.assertIn("Wealth", (card.wealth_cta, card.firsatlar_cta))
        self.assertIn("Fırsatlar", (card.wealth_cta, card.firsatlar_cta))


class RankingAndFitTests(unittest.TestCase):
    def test_lexicographic_rank_uses_existing_decision_then_score(self) -> None:
        rows = [
            _candidate("ADAY1", decision="ADAY", score=90, completeness=99),
            _candidate("STRONG", decision="GÜÇLÜ ADAY", score=82, completeness=60),
            _candidate("ADAY2", decision="ADAY", score=91, completeness=80),
        ]
        ranked = rank_recommendation_opportunities(rows)
        self.assertEqual([row["symbol"] for row in ranked], ["STRONG", "ADAY2", "ADAY1"])
        self.assertIn("çapraz faktör", RANKING_LIMITATION.casefold())

    def test_overweight_skip_is_poor_fit(self) -> None:
        plan = AllocationPlan(
            input_amount=Decimal("60000"),
            currency="TRY",
            recommendations=(),
            total_allocated=Decimal("0"),
            residual_cash=Decimal("60000"),
            skipped=(
                AllocationSkip(
                    symbol="NVDA",
                    reason_code=REASON_OVERWEIGHT_LAYER,
                    reason_text="Katman fazla ağırlıkta.",
                ),
            ),
        )
        rec = build_nabi_recommendation(
            candidates=[_candidate("NVDA", research="TAMAMLANDI")],
            decision=_decision(),
            allocation=plan,
            valuation_complete=True,
        )
        self.assertEqual(rec.portfolio_fit, FIT_POOR)
        self.assertNotEqual(rec.action_code, ACTION_CONSIDER_NEW_POSITION)


class SurfaceAndSafetyTests(unittest.TestCase):
    def test_dashboard_consolidates_priority_and_actions(self) -> None:
        home = HOME.read_text(encoding="utf-8")
        self.assertIn("present_recommendation_card", home)
        self.assertIn("Bugün:", home)
        self.assertNotIn("SECTION_PRIORITY", home)
        self.assertNotIn("SECTION_ACTIONS", home)
        self.assertIn("build_nabi_recommendation", TODAY.read_text(encoding="utf-8"))

    def test_firsatlar_reuses_recommendation_summary(self) -> None:
        page = FIRSATLAR.read_text(encoding="utf-8")
        self.assertIn("build_nabi_recommendation", page)
        self.assertIn("opportunity_intelligence_summary", page)
        self.assertIn("intelligence_summary", CENTER.read_text(encoding="utf-8"))
        self.assertNotIn("nabi_today_presentation", page)

    def test_wealth_freeze_untouched(self) -> None:
        wealth = WEALTH.read_text(encoding="utf-8")
        self.assertIn("render_wealth_command_center", wealth)
        self.assertNotIn("nabi_recommendation", wealth)
        self.assertNotIn("nabi_today_presentation", wealth)

    def test_no_llm_providers_or_writes(self) -> None:
        for path in (ENGINE, HOME, TODAY, CENTER, FIRSATLAR):
            source = path.read_text(encoding="utf-8")
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token, source)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)

    def test_healthy_message_not_forced_trade(self) -> None:
        rec = build_nabi_recommendation(decision=_decision(), valuation_complete=True)
        self.assertEqual(rec.action_code, ACTION_NO_ACTION)
        card = present_recommendation_card(rec)
        self.assertNotIn("BUY", card.today)
        self.assertNotIn("STRONG_BUY", ENGINE.read_text(encoding="utf-8"))
        self.assertNotIn(HEALTHY_MESSAGE, card.today)


if __name__ == "__main__":
    unittest.main()
