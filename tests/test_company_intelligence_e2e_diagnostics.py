from __future__ import annotations

import json
import unittest
from datetime import date
from unittest.mock import MagicMock

from components.company_intelligence_ui import render_company_intelligence_sections
from services.company_intelligence_contract import CompanyIntelligenceView, DataQualitySection
from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_earnings_calendar import (
    build_earnings_catalysts,
    filter_earnings_calendar_for_symbol,
)
from services.company_intelligence_provider_diagnostics import (
    build_provider_diagnostics,
    diagnostic_from_fmp_error,
    format_fmp_exception_limitation,
)
from services.company_news_intelligence import build_catalysts
from services.fmp_client import FMPClient, FMPError
from services.investment_thesis_service import InvestmentThesisService
from services.research_eligibility_contract import RESEARCH_STATUS_FAIL
from services.research_eligibility_service import (
    ResearchEligibilityResult,
    research_eligibility_pass_fixture,
)
from services.unified_research_service import UnifiedResearchService
from services.wealth_adviser_output_validator import BUY_SELL_PATTERNS


def _market_wide_earnings_calendar() -> list:
    """Reproduce live FMP contamination: symbol param ignored, market-wide rows."""
    rows = []
    symbols = ["AAPL", "MSFT", "GOOGL", "META", "CRM", "NVDA"]
    dates = [
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-10",
        "2026-08-12",
        "2026-08-03",
    ]
    for idx, sym in enumerate(symbols):
        rows.append({"symbol": sym, "date": dates[idx % len(dates)]})
    return rows


class EarningsCalendarFilterTests(unittest.TestCase):
    def test_foreign_symbol_rows_removed(self) -> None:
        rows = _market_wide_earnings_calendar()
        filtered, stats = filter_earnings_calendar_for_symbol(rows, "CRM")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["symbol"], "CRM")
        self.assertEqual(stats["foreign_symbol_rows"], 5)

    def test_missing_symbol_rows_not_assumed(self) -> None:
        rows = [{"date": "2026-08-04"}, {"symbol": "CRM", "date": "2026-08-05"}]
        filtered, stats = filter_earnings_calendar_for_symbol(rows, "CRM")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(stats["missing_symbol_rows"], 1)

    def test_peer_earnings_cannot_enter_crm_catalysts(self) -> None:
        filtered, _ = filter_earnings_calendar_for_symbol(
            _market_wide_earnings_calendar(),
            "CRM",
        )
        bundle = CompanyProviderBundle(symbol="CRM", earnings_calendar=filtered)
        catalysts = build_catalysts(bundle, ())
        self.assertLessEqual(len(catalysts), 1)
        for item in catalysts:
            self.assertEqual(item.related_symbols, ("CRM",))

    def test_duplicate_same_date_collapses(self) -> None:
        rows = [
            {"symbol": "CRM", "date": "2026-08-05", "id": "a"},
            {"symbol": "CRM", "date": "2026-08-05", "id": "a"},
        ]
        catalysts = build_earnings_catalysts(
            symbol="CRM",
            calendar_rows=rows,
            today=date(2026, 8, 1),
        )
        self.assertEqual(len(catalysts), 1)
        self.assertEqual(catalysts[0].date, "2026-08-05")

    def test_conflicting_dates_become_uncertain_not_multiple_high_confidence(self) -> None:
        rows = [
            {"symbol": "CRM", "date": "2026-08-04"},
            {"symbol": "CRM", "date": "2026-08-12"},
        ]
        catalysts = build_earnings_catalysts(
            symbol="CRM",
            calendar_rows=rows,
            today=date(2026, 8, 1),
        )
        self.assertEqual(len(catalysts), 1)
        self.assertEqual(catalysts[0].status, "UNCERTAIN")
        self.assertEqual(catalysts[0].confidence, "LOW")
        self.assertIn("2026-08-04", catalysts[0].description)
        self.assertIn("2026-08-12", catalysts[0].description)

    def test_past_dates_not_upcoming_catalysts(self) -> None:
        rows = [{"symbol": "CRM", "date": "2020-01-15"}]
        catalysts = build_earnings_catalysts(
            symbol="CRM",
            calendar_rows=rows,
            today=date(2026, 8, 1),
        )
        self.assertEqual(catalysts, ())


class ProviderDiagnosticsTests(unittest.TestCase):
    def test_plan_restricted_message_is_user_friendly(self) -> None:
        exc = FMPError(
            "restricted",
            error_class="plan_restricted",
            status_code=403,
            endpoint="income-statement",
        )
        message = diagnostic_from_fmp_error("income_quarterly", exc).user_message_tr
        self.assertIn("Çeyreklik gelir tablosu", message)
        self.assertIn("abonelik plan", message.lower())
        self.assertNotIn("api_key", message.lower())

    def test_api_key_never_in_diagnostic_serialization(self) -> None:
        exc = FMPError("auth", error_class="auth", endpoint="profile")
        payload = diagnostic_from_fmp_error("profile", exc).to_dict()
        serialized = json.dumps(payload).lower()
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("apikey", serialized)

    def test_foreign_calendar_failure_token_produces_diagnostic(self) -> None:
        diagnostics = build_provider_diagnostics(
            ["earnings_calendar:foreign_symbol_rows:77"]
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("yabancı sembol", diagnostics[0].user_message_tr.lower())

    def test_fmp_error_not_class_name_only_in_participation_limitation(self) -> None:
        exc = FMPError("down", error_class="plan_restricted", endpoint="historical-price-eod/light")
        message = format_fmp_exception_limitation("historical_price_eod_light", exc)
        self.assertNotEqual(message, "FMPError")
        self.assertIn("Tarihsel fiyat", message)


class CompanyIntelligenceFirewallTests(unittest.TestCase):
    def test_blocked_participation_zero_ci_calls(self) -> None:
        fmp = MagicMock(spec=FMPClient)
        service = CompanyIntelligenceCoreService(fmp)
        blocked = ResearchEligibilityResult(
            symbol="CRM",
            status=RESEARCH_STATUS_FAIL,
            research_allowed=False,
            participation_status="Uygun Değil",
            reason_codes=("participation_fail",),
            limitations=("Katılım uygun değil.",),
            provenance=(("gate", "test"),),
        )
        with self.assertRaises(Exception):
            service.build_view("CRM", research_eligibility=blocked)
        fmp.profile.assert_not_called()


class CompanyIntelligencePartialSectionTests(unittest.TestCase):
    def test_profile_only_bundle_marks_partial_sections(self) -> None:
        fmp = MagicMock(spec=FMPClient)
        fmp.profile.return_value = {"companyName": "Salesforce, Inc.", "sector": "Technology"}
        fmp.income_statement_quarterly.side_effect = FMPError(
            "restricted",
            error_class="plan_restricted",
        )
        fmp.balance_sheet_quarterly.side_effect = FMPError(
            "restricted",
            error_class="plan_restricted",
        )
        fmp.cash_flow_quarterly.side_effect = FMPError(
            "restricted",
            error_class="plan_restricted",
        )
        fmp.ratios_ttm.side_effect = FMPError("restricted", error_class="plan_restricted")
        fmp.key_metrics_ttm.side_effect = FMPError("restricted", error_class="plan_restricted")
        fmp.ratios.return_value = []
        fmp.key_metrics.return_value = []
        fmp.stock_peers.return_value = []
        fmp.stock_news.side_effect = FMPError("restricted", error_class="plan_restricted")
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = _market_wide_earnings_calendar()

        view = CompanyIntelligenceCoreService(fmp).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
        )
        self.assertIsNotNone(view.business_snapshot)
        self.assertIsNone(view.financial_trends)
        self.assertIsNone(view.valuation)
        self.assertEqual(view.catalysts, ())
        assert view.data_quality is not None
        self.assertIn("financial_trends", view.data_quality.partial_sections)
        self.assertTrue(view.data_quality.provider_diagnostic_details)

    def test_trends_not_fabricated_without_income(self) -> None:
        fmp = MagicMock(spec=FMPClient)
        fmp.profile.return_value = {"companyName": "Salesforce, Inc."}
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
        view = CompanyIntelligenceCoreService(fmp).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
        )
        self.assertIsNone(view.financial_trends)


class CacheIsolationTests(unittest.TestCase):
    def test_bundle_cache_does_not_mix_symbols(self) -> None:
        fmp = MagicMock(spec=FMPClient)

        def profile_side_effect(symbol: str):
            return {"companyName": f"Company-{symbol}"}

        fmp.profile.side_effect = profile_side_effect
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
        eligibility = research_eligibility_pass_fixture("CRM")
        crm_view = service.build_view("CRM", research_eligibility=eligibility)
        aapl_view = service.build_view("AAPL", research_eligibility=research_eligibility_pass_fixture("AAPL"))
        self.assertEqual(crm_view.company_name, "Company-CRM")
        self.assertEqual(aapl_view.company_name, "Company-AAPL")


class ThesisAndUnifiedResearchTests(unittest.TestCase):
    def _partial_crm_view(self) -> CompanyIntelligenceView:
        fmp = MagicMock(spec=FMPClient)
        fmp.profile.return_value = {"companyName": "Salesforce, Inc."}
        fmp.income_statement_quarterly.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.balance_sheet_quarterly.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.cash_flow_quarterly.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.ratios_ttm.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.key_metrics_ttm.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.ratios.return_value = []
        fmp.key_metrics.return_value = []
        fmp.stock_peers.return_value = []
        fmp.stock_news.side_effect = FMPError("x", error_class="plan_restricted")
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = _market_wide_earnings_calendar()
        return CompanyIntelligenceCoreService(fmp).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
        )

    def test_incomplete_ci_limits_thesis_evidence(self) -> None:
        view = self._partial_crm_view()
        thesis = InvestmentThesisService().build_view(
            view,
            candidate={"symbol": "CRM"},
            research_eligibility=research_eligibility_pass_fixture("CRM"),
        )
        self.assertEqual(thesis.thesis_status, "INSUFFICIENT_DATA")
        self.assertEqual(thesis.confidence, "LOW")

    def test_unified_research_json_safe_without_secrets(self) -> None:
        view = self._partial_crm_view()
        context = UnifiedResearchService().build_context(
            symbol="CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            company_intelligence_view=view,
            candidate={"symbol": "CRM"},
        )
        serialized = json.dumps(context.to_dict())
        self.assertNotIn("api_key", serialized.lower())
        self.assertNotIn("apikey", serialized.lower())


class AdviserValidatorTests(unittest.TestCase):
    def test_exact_trade_pattern_matches_crm_buy_today(self) -> None:
        answer = "Bugün CRM al."
        matched = any(pattern.search(answer) for pattern in BUY_SELL_PATTERNS)
        self.assertTrue(matched)


class CompanyReportRenderSmokeTests(unittest.TestCase):
    def test_company_intelligence_ui_render_smoke(self) -> None:
        view = CompanyIntelligenceView(
            symbol="CRM",
            company_name="Salesforce",
            as_of="t",
            business_snapshot=None,
            financial_trends=None,
            earnings=None,
            valuation=None,
            peers=None,
            news=None,
            data_quality=DataQualitySection(
                company_profile_available=True,
                financial_history_available=False,
                quarterly_comparison_available=False,
                earnings_expectations_available=False,
                valuation_available=False,
                historical_valuation_available=False,
                peer_data_available=False,
                news_available=False,
                catalyst_data_available=False,
                warnings=("Finansal geçmiş eksik.",),
                provider_failures=("income_quarterly:PLAN_RESTRICTED",),
                provider_diagnostic_details=(
                    {
                        "provider": "fmp",
                        "operation": "income_quarterly",
                        "failure_category": "PLAN_RESTRICTED",
                        "user_message_tr": "Çeyreklik gelir tablosu: plan.",
                    },
                ),
                partial_sections=("financial_trends",),
                as_of="t",
            ),
        )
        mock_st = MagicMock()
        from unittest.mock import patch

        with patch("components.company_intelligence_ui.st", mock_st):
            render_company_intelligence_sections(view)
        self.assertTrue(mock_st.subheader.called)


if __name__ == "__main__":
    unittest.main()
