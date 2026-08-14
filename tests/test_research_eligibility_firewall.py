from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.company_intelligence_utils import find_yoy_pair, fiscal_period_key
from services.company_report_participation_service import CompanyReportParticipationView
from services.investment_thesis_service import InvestmentThesisService
from services.participation_assessment_service import ParticipationAssessmentResult
from services.participation_intelligence_contract import (
    CONFIDENCE_MEDIUM,
    METHODOLOGY_COMPLETENESS_COMPLETE,
    PARTICIPATION_SOURCE_METHODOLOGY,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    ParticipationAssessment,
)
from services.research_eligibility_contract import (
    RESEARCH_STATUS_FAIL,
    RESEARCH_STATUS_INSUFFICIENT_DATA,
    RESEARCH_STATUS_PASS,
    RESEARCH_STATUS_UNKNOWN,
)
from services.research_eligibility_service import (
    ResearchEligibilityBlockedError,
    evaluate_research_eligibility_from_assessment,
    evaluate_research_eligibility_from_participation_view,
    require_research_allowed,
    research_eligibility_pass_fixture,
)
from services.unified_research_service import UnifiedResearchService


def _assessment_result(
    *,
    status: str,
    sec_available: bool = True,
    errors: tuple[str, ...] = (),
) -> ParticipationAssessmentResult:
    return ParticipationAssessmentResult(
        symbol="TEST",
        methodology_id="aaoifi_v1",
        resolved_methodology_version="1",
        participation_assessment=ParticipationAssessment(
            symbol="TEST",
            asset_kind="equity",
            status=status,
            source=PARTICIPATION_SOURCE_METHODOLOGY,
            confidence=CONFIDENCE_MEDIUM,
            methodology_completeness=METHODOLOGY_COMPLETENESS_COMPLETE,
        ),
        sec_available=sec_available,
        errors=errors,
    )


class ResearchEligibilityGateTests(unittest.TestCase):
    def test_compliant_symbol_allows_research(self) -> None:
        result = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_UYGUN)
        )
        self.assertTrue(result.research_allowed)
        self.assertEqual(result.status, RESEARCH_STATUS_PASS)

    def test_non_compliant_denies_research(self) -> None:
        result = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        self.assertFalse(result.research_allowed)
        self.assertEqual(result.status, RESEARCH_STATUS_FAIL)

    def test_kontrol_et_with_sec_denies_research(self) -> None:
        result = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_KONTROL_ET, sec_available=False)
        )
        self.assertFalse(result.research_allowed)
        self.assertEqual(result.status, RESEARCH_STATUS_INSUFFICIENT_DATA)

    def test_kontrol_et_with_complete_sec_is_unknown(self) -> None:
        result = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_KONTROL_ET, sec_available=True)
        )
        self.assertFalse(result.research_allowed)
        self.assertEqual(result.status, RESEARCH_STATUS_UNKNOWN)

    def test_provider_error_denies_research(self) -> None:
        result = evaluate_research_eligibility_from_assessment(
            _assessment_result(
                status=PARTICIPATION_STATUS_KONTROL_ET,
                errors=("SEC fetch failed",),
            )
        )
        self.assertFalse(result.research_allowed)

    def test_unavailable_participation_view_denies(self) -> None:
        view = CompanyReportParticipationView(
            symbol="TEST",
            available=False,
            error_message="broken",
        )
        result = evaluate_research_eligibility_from_participation_view(view)
        self.assertFalse(result.research_allowed)

    def test_missing_gate_raises(self) -> None:
        with self.assertRaises(ResearchEligibilityBlockedError):
            require_research_allowed(None, symbol="TEST")

    def test_blocked_gate_raises(self) -> None:
        blocked = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        with self.assertRaises(ResearchEligibilityBlockedError):
            require_research_allowed(blocked)


class ResearchFirewallDownstreamTests(unittest.TestCase):
    def test_non_compliant_zero_company_intelligence_calls(self) -> None:
        fmp = MagicMock()
        blocked = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        service = CompanyIntelligenceCoreService(fmp)
        with self.assertRaises(ResearchEligibilityBlockedError):
            service.build_view("TEST", research_eligibility=blocked)
        fmp.profile.assert_not_called()

    def test_unknown_zero_company_intelligence_calls(self) -> None:
        fmp = MagicMock()
        blocked = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_KONTROL_ET, sec_available=False)
        )
        service = CompanyIntelligenceCoreService(fmp)
        with self.assertRaises(ResearchEligibilityBlockedError):
            service.load_bundle("TEST", research_eligibility=blocked)
        self.assertEqual(fmp.method_calls, [])

    def test_non_compliant_zero_thesis_build(self) -> None:
        blocked = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        with patch("services.investment_thesis_service.build_investment_thesis_view") as mocked:
            InvestmentThesisService().blocked_view(
                symbol="TEST",
                research_eligibility=blocked,
            )
            mocked.assert_not_called()

    def test_unified_research_blocked_without_ci(self) -> None:
        blocked = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        with self.assertRaises(ResearchEligibilityBlockedError):
            UnifiedResearchService().build_context(
                symbol="TEST",
                research_eligibility=blocked,
            )

    def test_cached_ci_cannot_bypass_denied_eligibility(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {"companyName": "Apple"}
        fmp.income_statement_quarterly.return_value = []
        fmp.balance_sheet_quarterly.return_value = []
        fmp.cash_flow_quarterly.return_value = []
        fmp.ratios_ttm.return_value = {}
        fmp.key_metrics_ttm.return_value = {}
        fmp.ratios.return_value = []
        fmp.key_metrics.return_value = []
        fmp.stock_peers.return_value = []
        fmp.stock_news.return_value = []
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []
        service = CompanyIntelligenceCoreService(fmp)
        allowed = research_eligibility_pass_fixture("TEST")
        service.build_view("TEST", research_eligibility=allowed)
        blocked = evaluate_research_eligibility_from_assessment(
            _assessment_result(status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        with self.assertRaises(ResearchEligibilityBlockedError):
            service.build_view("TEST", research_eligibility=blocked)
        self.assertEqual(fmp.profile.call_count, 1)


class YoYPairingTests(unittest.TestCase):
    def test_true_yoy_pair_by_calendar_year_and_period(self) -> None:
        rows = [
            {"calendarYear": 2026, "period": "Q2", "revenue": 110},
            {"calendarYear": 2026, "period": "Q1", "revenue": 100},
            {"calendarYear": 2025, "period": "Q4", "revenue": 95},
            {"calendarYear": 2025, "period": "Q3", "revenue": 90},
            {"calendarYear": 2025, "period": "Q2", "revenue": 80},
        ]
        latest, previous = find_yoy_pair(rows)
        self.assertEqual(fiscal_period_key(latest), (2026, "Q2"))
        self.assertEqual(fiscal_period_key(previous), (2025, "Q2"))

    def test_q2_not_compared_to_q1(self) -> None:
        rows = [
            {"calendarYear": 2026, "period": "Q2", "revenue": 110},
            {"calendarYear": 2026, "period": "Q1", "revenue": 100},
        ]
        latest, previous = find_yoy_pair(rows)
        self.assertIsNotNone(latest)
        self.assertIsNone(previous)


class FinancialTrendYoYIntegrationTests(unittest.TestCase):
    def test_yoy_revenue_change_uses_prior_year_quarter(self) -> None:
        from services.company_financial_trend_engine import build_financial_trends
        from services.company_intelligence_data import CompanyProviderBundle

        bundle = CompanyProviderBundle(
            symbol="TEST",
            income_quarterly=[
                {"calendarYear": 2026, "period": "Q2", "revenue": 120},
                {"calendarYear": 2026, "period": "Q1", "revenue": 100},
                {"calendarYear": 2025, "period": "Q4", "revenue": 95},
                {"calendarYear": 2025, "period": "Q3", "revenue": 90},
                {"calendarYear": 2025, "period": "Q2", "revenue": 100},
            ],
        )
        section = build_financial_trends(bundle)
        revenue = next(item for item in section.trends if item.metric == "revenue")
        self.assertEqual(revenue.latest_value, 120)
        self.assertEqual(revenue.previous_value, 100)


if __name__ == "__main__":
    unittest.main()
