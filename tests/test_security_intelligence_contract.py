from __future__ import annotations

import unittest
from pathlib import Path

from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.nabi_score_v4 import calculate_nabi_score_v4
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.security_intelligence_contract import (
    DIM_VALUATION,
    ENGINE_VERSION,
    SecurityFacts,
    SecurityParticipationContext,
    SecurityPortfolioContext,
    STATE_ATTRACTIVE,
    STATE_AVOID,
    STATE_CAUTION,
    STATE_INSUFFICIENT_DATA,
    STATE_WATCH,
    STATUS_INSUFFICIENT_DATA,
    STATUS_STRONG,
    STATUS_VERY_STRONG,
    snapshot_from_view,
    proposed_snapshot_schema,
)
from services.security_intelligence_engine import (
    compare_snapshots,
    evaluate_security_intelligence,
    resolve_investment_state,
    weighted_or_none,
)
from services.security_intelligence_service import (
    SecurityIntelligenceService,
    facts_from_candidate,
)


ENGINE = Path("services/security_intelligence_engine.py")
SERVICE = Path("services/security_intelligence_service.py")
CONTRACT = Path("services/security_intelligence_contract.py")
SCORE = Path("services/nabi_score_v4.py")


def _rich_facts(**overrides) -> SecurityFacts:
    payload = dict(
        symbol="TEST",
        roic=20,
        roe=22,
        roa=10,
        revenue_growth_yoy=12,
        revenue_cagr_3y=14,
        eps_growth_yoy=15,
        eps_cagr_3y=16,
        fcf_cagr_3y=11,
        gross_margin=50,
        operating_margin=22,
        net_margin=18,
        fcf_margin=15,
        pe=16,
        price_to_sales=3,
        price_to_book=3,
        debt_to_equity=0.4,
        net_debt_to_fcf=1.0,
        current_ratio=1.8,
        interest_coverage=12,
        return_3m=8,
        return_6m=10,
        return_1y=18,
        drawdown=8,
        price=100,
        market_cap=80_000_000_000,
        revenue=10_000_000_000,
        free_cash_flow=2_000_000_000,
    )
    payload.update(overrides)
    return SecurityFacts(**payload)


class ContractTests(unittest.TestCase):
    def test_dimension_determinism(self) -> None:
        first = evaluate_security_intelligence(
            _rich_facts(),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        second = evaluate_security_intelligence(
            _rich_facts(),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertIsNotNone(first.overall_score)
        self.assertIn(first.quality.status, {STATUS_STRONG, STATUS_VERY_STRONG})

    def test_missing_data_is_insufficient_not_neutral(self) -> None:
        view = evaluate_security_intelligence(SecurityFacts(symbol="EMPTY"))
        self.assertIsNone(view.overall_score)
        self.assertEqual(view.overall_status, STATUS_INSUFFICIENT_DATA)
        self.assertEqual(view.valuation.status, STATUS_INSUFFICIENT_DATA)
        self.assertEqual(view.momentum.status, STATUS_INSUFFICIENT_DATA)
        self.assertEqual(view.investment_state, STATE_INSUFFICIENT_DATA)
        self.assertFalse(view.investable)
        self.assertIsNone(weighted_or_none([(None, 1.0)]))

    def test_stale_and_partial_do_not_become_attractive(self) -> None:
        stale = evaluate_security_intelligence(
            _rich_facts(stale=True),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        self.assertNotEqual(stale.overall_status, STATUS_VERY_STRONG)
        self.assertIn("STALE_DATA", stale.risk_flags)
        partial = evaluate_security_intelligence(
            SecurityFacts(symbol="PE", pe=12),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        self.assertEqual(partial.overall_status, STATUS_INSUFFICIENT_DATA)
        self.assertFalse(partial.investable)

    def test_score_status_separation(self) -> None:
        view = evaluate_security_intelligence(
            _rich_facts(pe=55, price_to_sales=12, price_to_book=12),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        self.assertIsNotNone(view.valuation.score)
        self.assertLess(view.valuation.score, 45)
        self.assertIn(view.valuation.status, {STATUS_INSUFFICIENT_DATA, "WEAK", "VERY_WEAK", "NEUTRAL"})
        self.assertIn("VALUATION_EXPENSIVE", view.valuation.reason_codes)
        self.assertNotEqual(view.valuation.score, view.valuation.status)

    def test_participation_firewall(self) -> None:
        rich = _rich_facts()
        uygun = evaluate_security_intelligence(
            rich,
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        fail = evaluate_security_intelligence(
            rich,
            SecurityParticipationContext(
                status=PARTICIPATION_STATUS_UYGUN_DEGIL, research_allowed=False
            ),
        )
        kontrol = evaluate_security_intelligence(
            rich,
            SecurityParticipationContext(
                status=PARTICIPATION_STATUS_KONTROL_ET, research_allowed=False
            ),
        )
        self.assertEqual(fail.investment_state, STATE_AVOID)
        self.assertFalse(fail.investable)
        self.assertNotEqual(kontrol.investment_state, STATE_ATTRACTIVE)
        self.assertFalse(kontrol.investable)
        self.assertEqual(fail.quality.score, uygun.quality.score)

    def test_research_allowed_firewall(self) -> None:
        view = evaluate_security_intelligence(
            _rich_facts(),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=False),
        )
        self.assertFalse(view.investable)
        self.assertNotIn(view.investment_state, {STATE_ATTRACTIVE, STATE_WATCH})
        self.assertEqual(
            resolve_investment_state(
                participation_status=PARTICIPATION_STATUS_UYGUN,
                research_allowed=False,
                overall_status=STATUS_VERY_STRONG,
            ),
            (STATE_CAUTION, False),
        )

    def test_portfolio_fit_is_separated(self) -> None:
        source = SERVICE.read_text(encoding="utf-8") + ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("portfolio_fit", source)
        context = SecurityPortfolioContext(is_held=True, portfolio_weight=12.0)
        view = SecurityIntelligenceService().evaluate(
            _rich_facts(),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        self.assertTrue(hasattr(context, "new_money_eligibility"))
        self.assertNotIn("portfolio_weight", view.to_dict())

    def test_change_detection_contract(self) -> None:
        first = evaluate_security_intelligence(
            _rich_facts(),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        weaker = evaluate_security_intelligence(
            _rich_facts(revenue_cagr_3y=-8, revenue_growth_yoy=-6, eps_cagr_3y=-5),
            SecurityParticipationContext(
                status=PARTICIPATION_STATUS_KONTROL_ET, research_allowed=False
            ),
            previous=snapshot_from_view(first, as_of="2025-12-31"),
        )
        self.assertTrue(weaker.change_flags)
        self.assertTrue(
            any(flag in weaker.change_flags for flag in ("GROWTH_SLOWING", "PARTICIPATION_CHANGED"))
        )
        self.assertEqual(compare_snapshots(None, snapshot_from_view(first)), ())

    def test_no_llm_dependency(self) -> None:
        text = ENGINE.read_text(encoding="utf-8") + SERVICE.read_text(encoding="utf-8")
        for token in ("openai", "anthropic", "chat.completions", "gpt-4", "litellm"):
            self.assertNotIn(token, text.lower())
        self.assertNotIn("import openai", text)
        self.assertNotIn("wealth_adviser_llm", text)

    def test_existing_score_compatibility(self) -> None:
        source = SCORE.read_text(encoding="utf-8")
        self.assertIn("del participation_score, participation_status", source)
        v4 = calculate_nabi_score_v4(
            revenue_growth_1y=12,
            revenue_cagr_3y=14,
            eps_growth_1y=15,
            eps_cagr_3y=16,
            fcf_cagr_3y=11,
            gross_margin=50,
            operating_margin=22,
            net_margin=18,
            fcf_margin=15,
            roic=20,
            roe=22,
            roa=10,
            current_ratio=1.8,
            debt_to_equity=0.4,
            net_debt_to_fcf=1.0,
            interest_coverage=12,
            pe_ratio=16,
            price_to_sales=3,
            price_to_book=3,
            share_change_3y=None,
            payout_ratio=None,
            market_cap=80_000_000_000,
            average_volume=None,
            portfolio_fit=80,
            participation_score=100,
            participation_status=PARTICIPATION_STATUS_UYGUN,
            completeness=90,
        )
        view = evaluate_security_intelligence(
            _rich_facts(),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        self.assertAlmostEqual(view.growth.score, v4["growth_score"], places=1)
        self.assertAlmostEqual(view.profitability.score, v4["profitability_score"], places=1)
        self.assertNotEqual(view.overall_score, v4["nabi_score"])
        self.assertIn("NABI Score v4 remains the Scanner", CONTRACT.read_text(encoding="utf-8"))

    def test_hybrid_remains_off(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        self.assertNotIn("enable_hybrid", ENGINE.read_text(encoding="utf-8"))

    def test_facts_from_candidate_do_not_invent(self) -> None:
        facts = facts_from_candidate({"symbol": "AAPL", "pe_ratio": 28}, symbol="AAPL")
        self.assertEqual(facts.pe, 28.0)
        self.assertIsNone(facts.roic)
        self.assertIn("roic", facts.missing_fields)

    def test_canonical_service_entry(self) -> None:
        view = SecurityIntelligenceService().evaluate(
            _rich_facts(),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        self.assertEqual(view.engine_version, ENGINE_VERSION)
        self.assertIn("table", proposed_snapshot_schema())
        self.assertEqual(view.dimension(DIM_VALUATION).name, DIM_VALUATION)

    def test_uygun_strong_is_attractive(self) -> None:
        view = evaluate_security_intelligence(
            _rich_facts(),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN, research_allowed=True),
        )
        self.assertIn(view.overall_status, {STATUS_STRONG, STATUS_VERY_STRONG})
        self.assertEqual(view.investment_state, STATE_ATTRACTIVE)
        self.assertTrue(view.investable)


if __name__ == "__main__":
    unittest.main()
