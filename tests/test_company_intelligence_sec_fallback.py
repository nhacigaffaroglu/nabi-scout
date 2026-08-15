from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.company_intelligence_sec_trends import (
    build_financial_trends_from_sec,
    sec_annual_yoy_available,
)
from services.fmp_client import FMPError
from services.research_eligibility_service import research_eligibility_pass_fixture
from tests.test_participation_aapl_forensic import _aapl_like_sec_financials


class SecAnnualTrendFallbackTests(unittest.TestCase):
    def test_sec_yoy_available_requires_two_periods(self) -> None:
        self.assertTrue(sec_annual_yoy_available(_aapl_like_sec_financials(
            revenue_prior=350_000_000_000.0,
            comparison_period_end="2024-09-28",
        )))
        self.assertFalse(sec_annual_yoy_available({"annual_periods_found": 1, "revenue": 1.0}))

    def test_build_trends_provenance_is_sec_annual(self) -> None:
        fin = _aapl_like_sec_financials(
            revenue_prior=385_000_000_000.0,
            comparison_period_end="2024-09-28",
            operating_income_prior=110_000_000_000.0,
            net_income_prior=95_000_000_000.0,
            eps_prior=6.0,
            operating_cash_flow_prior=100_000_000_000.0,
            capital_expenditure_prior=10_000_000_000.0,
            free_cash_flow_prior=90_000_000_000.0,
            cash_prior=30_000_000_000.0,
            total_debt_prior=95_000_000_000.0,
            gross_profit_prior=170_000_000_000.0,
        )
        section = build_financial_trends_from_sec(
            fin,
            symbol="AAPL",
            retrieved_at="2026-08-15T00:00:00Z",
        )
        assert section is not None
        self.assertEqual(section.provenance.provider, "sec")
        self.assertEqual(section.provenance.data_family, "financial_statements_annual")
        revenue = next(item for item in section.trends if item.metric == "revenue")
        self.assertIsNotNone(revenue.latest_value)
        self.assertIsNotNone(revenue.previous_value)
        self.assertIn("SEC", section.trends[0].limitations[1])

    def test_single_period_does_not_fabricate_ttm(self) -> None:
        section = build_financial_trends_from_sec(
            {"annual_periods_found": 1, "revenue": 100.0},
            symbol="TEST",
            retrieved_at="t",
        )
        self.assertIsNone(section)


class SecFallbackIntegrationTests(unittest.TestCase):
    def test_fmp_restricted_sec_fallback_populates_trends(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {"companyName": "Salesforce, Inc."}
        fmp.income_statement_quarterly.side_effect = FMPError(
            "restricted",
            error_class="plan_restricted",
            status_code=402,
        )
        fmp.balance_sheet_quarterly.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.cash_flow_quarterly.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.ratios_ttm.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.key_metrics_ttm.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.ratios.return_value = []
        fmp.key_metrics.return_value = []
        fmp.stock_peers.return_value = []
        fmp.stock_news.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []

        sec_fin = _aapl_like_sec_financials(
            revenue_prior=350_000_000_000.0,
            comparison_period_end="2024-09-28",
        )
        view = CompanyIntelligenceCoreService(fmp).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=sec_fin,
        )
        self.assertIsNotNone(view.financial_trends)
        assert view.data_quality is not None
        self.assertTrue(
            any("SEC yıllık" in warning for warning in view.data_quality.warnings)
        )
        self.assertTrue(view.data_quality.provider_diagnostic_details)
        serialized = json.dumps(view.data_quality.provider_diagnostic_details).lower()
        self.assertNotIn("api_key", serialized)


class AaplSecondRatioRegressionTests(unittest.TestCase):
    def test_aapl_cash_interest_rule_fail_with_full_evidence(self) -> None:
        from services.participation_financial_engine import evaluate_financial_rules
        from services.participation_sec_input_resolver import build_participation_inputs_from_sec
        from services.participation_intelligence_contract import (
            PARTICIPATION_STATUS_UYGUN_DEGIL,
            RULE_OUTCOME_FAIL,
            RULE_OUTCOME_INSUFFICIENT_DATA,
        )
        from services.participation_intelligence_service import build_combined_methodology_assessment
        from services.participation_business_contract import BusinessActivityScreenResult

        resolution = build_participation_inputs_from_sec(
            "AAPL",
            _aapl_like_sec_financials(),
            cik="320193",
        )
        screen = evaluate_financial_rules("msci_islamic_index_series", resolution.inputs)
        cash_rule = next(
            r for r in screen.rule_results
            if r.rule_id == "msci.cash_and_interest_bearing_to_total_assets"
        )
        self.assertEqual(cash_rule.outcome, RULE_OUTCOME_FAIL)
        self.assertAlmostEqual(cash_rule.ratio_pct or 0.0, 36.86, places=1)
        self.assertEqual(cash_rule.numerator_raw_value, 132_420_000_000.0)
        tags = _aapl_like_sec_financials()["interest_bearing_securities_tags"]
        self.assertIn("MarketableSecurities", tags)

        business = BusinessActivityScreenResult(
            symbol="AAPL",
            methodology_id="msci_islamic_index_series",
            methodology_version="2025-05",
            rule_results=(),
            overall_outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
        )
        assessment = build_combined_methodology_assessment(screen, business)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_missing_interest_bearing_is_insufficient_not_pass(self) -> None:
        from services.participation_financial_engine import evaluate_financial_rules
        from services.participation_sec_input_resolver import build_participation_inputs_from_sec
        from services.participation_intelligence_contract import RULE_OUTCOME_INSUFFICIENT_DATA

        resolution = build_participation_inputs_from_sec(
            "AAPL",
            _aapl_like_sec_financials(interest_bearing_securities=None),
        )
        cash_rule = next(
            r
            for r in evaluate_financial_rules(
                "msci_islamic_index_series",
                resolution.inputs,
            ).rule_results
            if r.rule_id == "msci.cash_and_interest_bearing_to_total_assets"
        )
        self.assertEqual(cash_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)


if __name__ == "__main__":
    unittest.main()
