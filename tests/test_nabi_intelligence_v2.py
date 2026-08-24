from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from services.nabi_opportunity_comparison import (
    RANKING_POLICY,
    best_deploy_comparison,
    build_opportunity_comparisons,
    compare_with_alternative,
)
from services.nabi_portfolio_fit import (
    FIT_GOOD,
    FIT_POOR,
    FIT_REASON_CONCENTRATION_LIMIT,
    assess_portfolio_fit,
    simulate_post_allocation_weight,
)
from services.nabi_recommendation import (
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    ACTION_NO_ACTION,
    ACTION_RESEARCH_OPPORTUNITY,
    ACTION_REVIEW_GOAL_PLAN,
    DEPLOY_EXISTING,
    DEPLOY_NEW,
    FIT_UNKNOWN,
    NO_APPROVED_HALAL_OPPORTUNITY,
    OUTCOME_HORIZONS,
    OUTCOME_STATES,
    OUTCOME_TRACKING_LIMITATION,
    RANKING_LIMITATION,
    build_nabi_recommendation,
    present_recommendation_card,
    rank_recommendation_opportunities,
    recommendation_halal_eligible,
)
from services.opportunity_center_presentation import (
    build_opportunity_center,
    present_comparison_cards,
)
from services.participation_intelligence_contract import CONFIDENCE_MEDIUM
from services.portfolio_decision_intelligence import (
    DecisionAction,
    DecisionActionStatus,
    DecisionCategory,
    DecisionPriority,
    PortfolioDecisionView,
)
from services.wealth_new_money_allocation import (
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_STRONG_CANDIDATE,
    AllocationPlan,
    AllocationRecommendation,
)

HOME = Path("components/nabi_home_dashboard.py")
FIRSATLAR = Path("pages/5_Firsatlar.py")
WEALTH = Path("pages/10_Wealth.py")
CENTER_UI = Path("components/opportunity_center_ui.py")
ENGINE = Path("services/nabi_recommendation.py")
COMPARE = Path("services/nabi_opportunity_comparison.py")
FIT = Path("services/nabi_portfolio_fit.py")
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
    research: str = "TAMAMLANDI",
    risk: str = "Tek müşteri riski",
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
        "critical_risk": risk,
        "last_scanned_at": "2026-08-20T10:00:00+00:00" if completeness is not None else None,
    }


def _decision() -> PortfolioDecisionView:
    action = DecisionAction(
        id="continue_observation",
        category=DecisionCategory.MONITOR,
        priority=DecisionPriority.INFO,
        title="Gözlem",
        explanation="Gözlem",
        evidence=(),
        status=DecisionActionStatus.OPEN,
    )
    return PortfolioDecisionView(
        actions=(action,),
        primary_action=action,
        evidence_complete=True,
        limitations=(),
        generated_from=("test",),
    )


def _rec(
    symbol: str,
    *,
    existing_or_new: str,
    reason: str,
    price: str = "100",
    currency: str = "TRY",
    quantity: str = "1",
    allocated: str = "100",
) -> AllocationRecommendation:
    return AllocationRecommendation(
        symbol=symbol,
        existing_or_new=existing_or_new,
        layer="equity",
        decision="GÜÇLÜ ADAY",
        price=Decimal(price),
        price_currency=currency,
        quantity=Decimal(quantity),
        allocated_amount=Decimal(allocated),
        reason_code=reason,
        reason_text=reason,
    )


class RankingPolicyTests(unittest.TestCase):
    def test_case_a_higher_score_poor_fit_still_leads_company_rank(self) -> None:
        high = _candidate("MU", score=90)
        low = _candidate("CRM", score=88)
        portfolio = SimpleNamespace(
            priced_positions=(SimpleNamespace(symbol="MU", weight_pct=25.0),)
        )
        rec = build_nabi_recommendation(
            candidates=[high, low],
            decision=_decision(),
            portfolio_view=portfolio,
            valuation_complete=True,
        )
        self.assertEqual([item.symbol for item in rec.comparisons], ["MU", "CRM"])
        self.assertEqual(rec.symbol, "MU")
        self.assertEqual(rec.comparisons[0].portfolio_fit, FIT_POOR)
        self.assertIn(FIT_REASON_CONCENTRATION_LIMIT, rec.comparisons[0].fit_reason_codes)
        self.assertNotEqual(rec.comparisons[1].portfolio_fit, FIT_POOR)
        deploy = best_deploy_comparison(rec.comparisons)
        self.assertIsNotNone(deploy)
        self.assertEqual(deploy.symbol, "CRM")
        self.assertIn("CRM", rec.alternative_line or "")
        self.assertIn("dengeli", rec.alternative_line or "")
        self.assertEqual(rec.action_code, ACTION_CONSIDER_NEW_POSITION)
        self.assertIn("CRM", rec.why_now)
        self.assertIn("değiştirmez", RANKING_POLICY)
        self.assertNotIn("NABI Opportunity Score", ENGINE.read_text(encoding="utf-8"))
        self.assertNotIn("82.7", COMPARE.read_text(encoding="utf-8"))

    def test_case_b_kontrol_et_never_enters_comparison(self) -> None:
        trap = _candidate("META", participation="Kontrol Et", score=99.0)
        approved = _candidate("JNJ", score=72.0, decision="ADAY")
        rec = build_nabi_recommendation(
            candidates=[trap, approved],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertFalse(recommendation_halal_eligible(trap))
        self.assertEqual([item.symbol for item in rec.comparisons], ["JNJ"])
        self.assertNotIn("META", [item.symbol for item in rec.comparisons])
        self.assertEqual(rank_recommendation_opportunities([trap, approved])[0]["symbol"], "JNJ")

    def test_case_c_existing_top_up_vs_new_follows_allocation(self) -> None:
        held = _candidate("MU", score=86)
        newbie = _candidate("CRM", score=84)
        portfolio = SimpleNamespace(
            priced_positions=(SimpleNamespace(symbol="MU", weight_pct=8.0),)
        )
        existing_plan = AllocationPlan(
            input_amount=Decimal("60000"),
            currency="TRY",
            recommendations=(_rec("MU", existing_or_new="existing", reason=REASON_EXISTING_HOLDING_TOPUP, allocated="20000"),),
            total_allocated=Decimal("20000"),
            residual_cash=Decimal("40000"),
            skipped=(),
        )
        rec_existing = build_nabi_recommendation(
            candidates=[held, newbie],
            decision=_decision(),
            portfolio_view=portfolio,
            allocation=existing_plan,
            valuation_complete=True,
        )
        self.assertEqual(rec_existing.deploy_decision, DEPLOY_EXISTING)
        self.assertEqual(rec_existing.action_code, ACTION_CONSIDER_TOP_UP)
        self.assertIn("mevcut pozisyonu artırmak", rec_existing.existing_vs_new or "")

        new_plan = AllocationPlan(
            input_amount=Decimal("60000"),
            currency="TRY",
            recommendations=(_rec("CRM", existing_or_new="new", reason=REASON_STRONG_CANDIDATE, allocated="20000"),),
            total_allocated=Decimal("20000"),
            residual_cash=Decimal("40000"),
            skipped=(),
        )
        rec_new = build_nabi_recommendation(
            candidates=[held, newbie],
            decision=_decision(),
            portfolio_view=portfolio,
            allocation=new_plan,
            valuation_complete=True,
        )
        self.assertEqual(rec_new.deploy_decision, DEPLOY_NEW)
        self.assertEqual(rec_new.action_code, ACTION_CONSIDER_NEW_POSITION)
        self.assertIn("CRM", rec_new.why_now)

    def test_case_d_no_action_when_nothing_attractive(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertEqual(rec.action_code, ACTION_NO_ACTION)
        self.assertEqual(rec.opportunity_line, NO_APPROVED_HALAL_OPPORTUNITY)
        self.assertEqual(rec.comparisons, ())
        self.assertIsNone(rec.symbol)
        card = present_recommendation_card(rec)
        self.assertIsNone(card.featured_symbol)

    def test_case_e_incomplete_research_reduces_confidence(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[_candidate("ADSK", research="YENI")],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertEqual(rec.action_code, ACTION_RESEARCH_OPPORTUNITY)
        self.assertEqual(rec.confidence, CONFIDENCE_MEDIUM)
        self.assertFalse(rec.comparisons[0].research_complete)
        self.assertIn("incomplete_research", rec.risk_flags)


class PortfolioFitAndAuditTests(unittest.TestCase):
    def test_post_allocation_concentration_same_currency_only(self) -> None:
        portfolio = SimpleNamespace(
            base_currency="TRY",
            priced_total_market_value=100000.0,
            priced_positions=(
                SimpleNamespace(symbol="MU", weight_pct=18.0, market_value=18000.0),
            ),
        )
        plan = AllocationPlan(
            input_amount=Decimal("60000"),
            currency="TRY",
            recommendations=(
                _rec(
                    "MU",
                    existing_or_new="existing",
                    reason=REASON_EXISTING_HOLDING_TOPUP,
                    price="100",
                    currency="TRY",
                    quantity="50",
                    allocated="5000",
                ),
            ),
            total_allocated=Decimal("5000"),
            residual_cash=Decimal("55000"),
            skipped=(),
        )
        post, limits = simulate_post_allocation_weight(
            "MU", portfolio_view=portfolio, allocation=plan
        )
        self.assertIsNotNone(post)
        self.assertGreaterEqual(post, 20.0)
        self.assertEqual(limits, ())
        fit = assess_portfolio_fit(
            _candidate("MU"), portfolio_view=portfolio, allocation=plan
        )
        self.assertEqual(fit.fit, FIT_POOR)
        self.assertIn(FIT_REASON_CONCENTRATION_LIMIT, fit.reason_codes)

        fx_plan = AllocationPlan(
            input_amount=Decimal("60000"),
            currency="TRY",
            recommendations=(
                _rec(
                    "MU",
                    existing_or_new="existing",
                    reason=REASON_EXISTING_HOLDING_TOPUP,
                    currency="USD",
                ),
            ),
            total_allocated=Decimal("100"),
            residual_cash=Decimal("59900"),
            skipped=(),
        )
        fx_post, fx_limits = simulate_post_allocation_weight(
            "MU", portfolio_view=portfolio, allocation=fx_plan
        )
        self.assertIsNone(fx_post)
        self.assertIn("POST_WEIGHT_REQUIRES_SAME_CURRENCY", fx_limits)

    def test_audit_record_is_in_memory_only(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[_candidate("JNJ")],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertIsNotNone(rec.audit)
        self.assertFalse(rec.audit.persisted)
        self.assertIsNone(rec.audit.generated_at)
        self.assertTrue(rec.audit.recommendation_id)
        self.assertEqual(rec.audit.primary_action, rec.action_code)
        self.assertEqual(OUTCOME_HORIZONS, ("7D", "30D", "90D", "1Y"))
        self.assertIn("INSUFFICIENT_HISTORY", OUTCOME_STATES)
        self.assertIn("No benchmark", OUTCOME_TRACKING_LIMITATION)

    def test_ranking_is_deterministic(self) -> None:
        rows = [
            _candidate("ADAY1", decision="ADAY", score=90, research="YENI"),
            _candidate("STRONG", score=82, research="TAMAMLANDI"),
            _candidate("ADAY2", decision="ADAY", score=91, research="YENI"),
        ]
        first = [row["symbol"] for row in rank_recommendation_opportunities(rows)]
        second = [row["symbol"] for row in rank_recommendation_opportunities(list(reversed(rows)))]
        self.assertEqual(first, ["STRONG", "ADAY2", "ADAY1"])
        self.assertEqual(first, second)
        complete_first = rank_recommendation_opportunities(
            [
                _candidate("OPEN", score=88, research="YENI"),
                _candidate("DONE", score=88, research="TAMAMLANDI"),
            ]
        )
        self.assertEqual(complete_first[0]["symbol"], "DONE")
        self.assertIn("çapraz faktör", RANKING_LIMITATION.casefold())

    def test_pending_and_uygun_degil_blocked(self) -> None:
        for row in (
            _candidate("X", participation="Pending"),
            _candidate("Y", participation="Uygun Değil"),
            _candidate("Z", participation=""),
        ):
            self.assertFalse(recommendation_halal_eligible(row))
            self.assertEqual(build_opportunity_comparisons([row]), ())


class SurfaceTests(unittest.TestCase):
    def test_dashboard_keeps_single_featured_slot(self) -> None:
        home = HOME.read_text(encoding="utf-8")
        self.assertIn("Öne çıkan fırsat", home)
        self.assertIn("Portföy uyumu", home)
        self.assertIn("Alternative", home)
        self.assertNotIn("for card in today.opportunities.cards", home)
        self.assertIn("NABI ÖNERİSİ", ENGINE.read_text(encoding="utf-8"))

    def test_firsatlar_comparison_cards_from_fixture(self) -> None:
        rows = [_candidate("MU", score=90), _candidate("CRM", score=88), _candidate("JNJ", score=80, decision="ADAY")]
        rec = build_nabi_recommendation(
            candidates=rows,
            decision=_decision(),
            valuation_complete=True,
        )
        view = build_opportunity_center(
            candidates=rows,
            comparisons=rec.comparisons,
            comparison_note=rec.alternative_line,
        )
        self.assertEqual(len(view.comparison_cards), 3)
        self.assertEqual(view.comparison_cards[0].symbol, "MU")
        self.assertTrue(view.comparison_cards[0].rank_reason)
        self.assertTrue(view.comparison_cards[0].strength)
        cards = present_comparison_cards(rec.comparisons)
        self.assertEqual(len(cards), 3)
        ui = CENTER_UI.read_text(encoding="utf-8")
        self.assertIn("OTHER_OPPORTUNITIES_LABEL", ui)
        self.assertIn("_render_comparison_card", ui)
        page = FIRSATLAR.read_text(encoding="utf-8")
        self.assertIn("comparisons=recommendation.comparisons", page)

    def test_wealth_freeze_and_v1_plan_gap_compat(self) -> None:
        wealth = WEALTH.read_text(encoding="utf-8")
        self.assertNotIn("nabi_recommendation", wealth)
        self.assertNotIn("nabi_opportunity_comparison", wealth)
        rec = build_nabi_recommendation(
            candidates=[],
            presented_actions=SimpleNamespace(
                healthy=False,
                visible_actions=(
                    SimpleNamespace(
                        id="contribution_plan_below_required",
                        title="Katkı planı hedefe yetmiyor",
                    ),
                ),
            ),
            valuation_complete=True,
        )
        self.assertEqual(rec.action_code, ACTION_REVIEW_GOAL_PLAN)
        self.assertEqual(rec.opportunity_line, NO_APPROVED_HALAL_OPPORTUNITY)

    def test_no_providers_or_writes(self) -> None:
        for path in (ENGINE, COMPARE, FIT, HOME, FIRSATLAR, CENTER_UI):
            source = path.read_text(encoding="utf-8")
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token, source)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)

    def test_compare_helper_requires_two_symbols(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[_candidate("MU")],
            decision=_decision(),
            valuation_complete=True,
        )
        self.assertIsNone(compare_with_alternative(rec.comparisons[0], rec.comparisons[0]))
        self.assertEqual(rec.portfolio_fit, FIT_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
