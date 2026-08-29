from __future__ import annotations

import math
import unittest
from pathlib import Path

from services.security_facts_service import SecurityFactsService, finite_number
from services.security_intelligence_contract import (
    AUTHORITY_CANDIDATE,
    AUTHORITY_DERIVED,
    AUTHORITY_PARTICIPATION,
    AUTHORITY_SEC,
    PERIOD_FY,
    PERIOD_MIXED,
)
from services.security_intelligence_engine import evaluate_security_intelligence
from services.security_intelligence_service import (
    SecurityIntelligenceService,
    facts_from_candidate,
    participation_from_sources,
)
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.nabi_score_v4 import calculate_nabi_score_v4
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN


PAGE = Path("pages/4_Company_Report.py")
FACADE = Path("services/nabi_intelligence_facade.py")
SCORE = Path("services/nabi_score_v4.py")


class FiniteNumberTests(unittest.TestCase):
    def test_null_nan_inf(self) -> None:
        self.assertIsNone(finite_number(None))
        self.assertIsNone(finite_number(""))
        self.assertIsNone(finite_number("x"))
        self.assertIsNone(finite_number(math.nan))
        self.assertIsNone(finite_number(math.inf))
        self.assertIsNone(finite_number(-math.inf))
        self.assertEqual(finite_number("12.5"), 12.5)


class FactPrecedenceTests(unittest.TestCase):
    def test_sec_wins_over_candidate_and_participation(self) -> None:
        facts = SecurityFactsService().build(
            "CRM",
            candidate={"symbol": "CRM", "revenue": 1, "roic": 1, "currency": "USD"},
            participation_snapshot={
                "assessment_payload": {
                    "financial_inputs": {"total_revenue": 2, "total_assets": 9}
                }
            },
            sec_financials={
                "revenue": 100,
                "roic": 20,
                "financial_period_end": "2025-01-31",
                "financial_currency": "USD",
            },
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.revenue, 100)
        self.assertEqual(facts.roic, 20)
        self.assertEqual(facts.total_assets, 9)
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["revenue"].authority, AUTHORITY_SEC)
        self.assertEqual(by_field["revenue"].period_kind, PERIOD_FY)
        self.assertEqual(by_field["total_assets"].authority, AUTHORITY_PARTICIPATION)

    def test_candidate_used_when_sec_absent(self) -> None:
        facts = SecurityFactsService().build(
            "AAPL",
            candidate={"symbol": "AAPL", "pe_ratio": 28, "roic": 40, "revenue": 400},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.pe, 28)
        self.assertEqual(facts.roic, 40)
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["pe"].authority, AUTHORITY_CANDIDATE)

    def test_provenance_is_traceable(self) -> None:
        facts = SecurityFactsService().build(
            "AAPL",
            sec_financials={
                "revenue": 400,
                "free_cash_flow": 100,
                "financial_period_end": "2025-09-27",
                "financial_currency": "USD",
            },
            candidate={"current_price": 220, "market_cap": 3_400_000_000_000},
            allow_sec_cache_replay=False,
        )
        fcf_yield = next(item for item in facts.provenance if item.field == "fcf_yield")
        self.assertEqual(fcf_yield.authority, AUTHORITY_DERIVED)
        self.assertEqual(fcf_yield.period_kind, PERIOD_MIXED)
        self.assertEqual(facts.as_of, "2025-09-27")
        self.assertIsNone(facts.eps)
        self.assertIsNone(facts.pe)

    def test_ratio_percent_only_for_company_intelligence_fallback(self) -> None:
        class _Trend:
            def __init__(self):
                self.metric = "operating_margin"
                self.latest_value = 0.22
                self.period = "TTM"

        class _Trends:
            trends = (_Trend(),)

        class _View:
            business_snapshot = None
            financial_trends = _Trends()
            valuation = None

        facts = SecurityFactsService().build(
            "X",
            company_intelligence=_View(),
            allow_sec_cache_replay=False,
        )
        self.assertAlmostEqual(facts.operating_margin, 22.0)
        prov = next(item for item in facts.provenance if item.field == "operating_margin")
        self.assertEqual(prov.normalization, "RATIO_TO_PERCENT")

    def test_incompatible_periods_are_marked_not_silently_compared(self) -> None:
        facts = SecurityFactsService().build(
            "X",
            sec_financials={"revenue": 10, "financial_period_end": "2025-01-01"},
            company_intelligence=type(
                "V",
                (),
                {
                    "business_snapshot": None,
                    "financial_trends": type("T", (), {"trends": ()})(),
                    "valuation": type(
                        "Val",
                        (),
                        {
                            "metrics": (
                                type(
                                    "M",
                                    (),
                                    {
                                        "code": "pe",
                                        "current_value": 18,
                                        "fundamental_period_end": "TTM",
                                    },
                                )(),
                            )
                        },
                    )(),
                },
            )(),
            allow_sec_cache_replay=False,
        )
        self.assertIn(facts.period_compatibility, {PERIOD_MIXED, "TTM", PERIOD_FY})
        if facts.pe is not None:
            pe = next(item for item in facts.provenance if item.field == "pe")
            self.assertIn(pe.period_kind, {PERIOD_MIXED, "TTM"})

    def test_sparse_facts_do_not_become_fifty_or_neutral_good(self) -> None:
        facts = SecurityFactsService().build(
            "UPS",
            candidate={"symbol": "UPS", "current_price": 100},
            participation_snapshot={
                "assessment_payload": {
                    "financial_inputs": {"total_revenue": 90_000_000_000}
                }
            },
            allow_sec_cache_replay=False,
        )
        self.assertIsNone(facts.roic)
        self.assertIsNone(facts.pe)
        view = evaluate_security_intelligence(facts)
        self.assertIsNone(view.overall_score)
        self.assertEqual(view.quality.status, "INSUFFICIENT_DATA")
        self.assertFalse(view.strengths)
        self.assertNotEqual(view.quality.status, "NEUTRAL")
        self.assertNotEqual(view.data_quality.score, 50)

    def test_participation_snapshot_status_is_read(self) -> None:
        ctx = participation_from_sources(
            queue_or_snapshot={"status": "Uygun", "assessed_at": "2026-01-01"},
        )
        self.assertEqual(ctx.status, "Uygun")


class SecurityIntelligenceUiTests(unittest.TestCase):
    def test_ui_does_not_relabel_nabi_score(self) -> None:
        source = Path("components/security_intelligence_ui.py").read_text(encoding="utf-8")
        self.assertIn("NABI Skoru v4", source)
        self.assertIn("SI overall ≠ NABI Skoru v4", source)
        self.assertNotIn("evaluate_security_intelligence", source)


class CanonicalConsumptionTests(unittest.TestCase):
    def test_company_report_uses_canonical_si(self) -> None:
        source = PAGE.read_text(encoding="utf-8")
        self.assertIn("build_canonical_security_intelligence_inputs", source)
        self.assertIn("SecurityIntelligenceService", source)
        self.assertIn("render_security_intelligence_section", source)
        self.assertIn("render_signal_intelligence_section", source)
        self.assertNotIn("evaluate_security_intelligence(", source)
        self.assertIn("build_company_intelligence", source)

    def test_facade_uses_canonical_si(self) -> None:
        source = FACADE.read_text(encoding="utf-8")
        self.assertIn("SecurityIntelligenceService", source)
        self.assertIn("SignalIntelligenceService", source)
        self.assertIn("build_canonical_security_intelligence_inputs", source)
        self.assertNotIn("nabi_score_v4", source)
        self.assertNotIn(".insert(", source)

    def test_nabi_score_v4_unchanged_and_hybrid_off(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
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
        self.assertIn("nabi_score", v4)
        facts = facts_from_candidate({"pe_ratio": 16, "roic": 20}, symbol="X")
        view = SecurityIntelligenceService().evaluate(facts)
        self.assertNotEqual(view.overall_score, v4["nabi_score"])


if __name__ == "__main__":
    unittest.main()
