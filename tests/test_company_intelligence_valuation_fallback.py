from __future__ import annotations

import json
import unittest
from typing import Optional
from unittest.mock import MagicMock

from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_sec_valuation import build_sec_hybrid_valuation
from services.company_intelligence_valuation_alignment import (
    ALIGNMENT_ACCEPTABLE_LAG,
    ALIGNMENT_STALE,
    assess_sec_market_hybrid_alignment,
    ev_balance_sheet_aligned,
)
from services.company_report_participation_service import build_company_report_participation
from services.fmp_client import FMPError
from services.investment_thesis_service import InvestmentThesisService
from services.research_eligibility_contract import (
    RESEARCH_STATUS_FAIL,
    ResearchEligibilityResult,
)
from services.research_eligibility_service import (
    ResearchEligibilityBlockedError,
    research_eligibility_pass_fixture,
)
from tests.test_participation_aapl_forensic import _aapl_like_sec_financials


def _crm_like_sec_financials(**overrides):
    payload = {
        "revenue": 37_900_000_000.0,
        "free_cash_flow": 12_500_000_000.0,
        "operating_income": 8_200_000_000.0,
        "total_debt": 14_000_000_000.0,
        "cash": 12_000_000_000.0,
        "financial_period_end": "2026-01-31",
        "balance_sheet_period_end": "2026-01-31",
        "annual_periods_found": 5,
        "revenue_prior": 34_900_000_000.0,
        "comparison_period_end": "2025-01-31",
    }
    payload.update(overrides)
    return payload


def _crm_live_like_sec_financials(**overrides):
    payload = {
        "revenue": 41_525_000_000.0,
        "free_cash_flow": 14_402_000_000.0,
        "operating_income": 8_331_000_000.0,
        "total_debt": 14_439_000_000.0,
        "cash": 7_327_000_000.0,
        "financial_period_end": "2026-01-31",
        "balance_sheet_period_end": "2026-01-31",
        "annual_periods_found": 19,
        "revenue_prior": 37_895_000_000.0,
        "comparison_period_end": "2025-01-31",
        "operating_income_prior": 7_666_000_000.0,
        "free_cash_flow_prior": 12_000_000_000.0,
    }
    payload.update(overrides)
    return payload


CRM_SEC_LOOKUP = {
    "CRM": {"symbol": "CRM", "cik": "1108524", "company_name": "Salesforce, Inc."},
}


def _crm_candidate(**overrides):
    payload = {
        "symbol": "CRM",
        "company_name": "Salesforce Inc",
        "sector_theme": "Technology",
        "industry": "Software - Application",
        "market_cap": 160_700_000_000.0,
    }
    payload.update(overrides)
    return payload


def _jnj_live_like_sec_financials(**overrides):
    payload = {
        "revenue": 94_193_000_000.0,
        "revenue_prior": 88_821_000_000.0,
        "free_cash_flow": 19_698_000_000.0,
        "free_cash_flow_prior": 19_842_000_000.0,
        "operating_income": 21_590_000_000.0,
        "operating_income_prior": 16_412_000_000.0,
        "net_income": 26_804_000_000.0,
        "net_income_prior": 14_066_000_000.0,
        "total_debt": 49_933_000_000.0,
        "cash": 19_709_000_000.0,
        "financial_period_end": "2025-12-28",
        "balance_sheet_period_end": "2025-12-28",
        "comparison_period_end": "2024-12-29",
        "annual_periods_found": 10,
        "eps": 11.03,
        "eps_prior": 5.79,
    }
    payload.update(overrides)
    return payload


JNJ_SEC_LOOKUP = {
    "JNJ": {"symbol": "JNJ", "cik": "200406", "company_name": "Johnson & Johnson"},
}


class ValuationAlignmentTests(unittest.TestCase):
    def test_missing_fiscal_period_rejects(self) -> None:
        assessment = assess_sec_market_hybrid_alignment(
            {"revenue": 100.0},
            market_cap=1_000_000.0,
            retrieved_at="2026-08-15T00:00:00Z",
        )
        self.assertIsNone(assessment)

    def test_missing_market_cap_rejects(self) -> None:
        assessment = assess_sec_market_hybrid_alignment(
            _crm_like_sec_financials(),
            market_cap=None,
            retrieved_at="2026-08-15T00:00:00Z",
        )
        self.assertIsNone(assessment)

    def test_missing_market_as_of_rejects(self) -> None:
        assessment = assess_sec_market_hybrid_alignment(
            _crm_like_sec_financials(),
            market_cap=250_000_000_000.0,
            retrieved_at="",
        )
        self.assertIsNone(assessment)

    def test_stale_market_rejects_hybrid(self) -> None:
        assessment = assess_sec_market_hybrid_alignment(
            _crm_like_sec_financials(financial_period_end="2024-01-31"),
            market_cap=250_000_000_000.0,
            retrieved_at="2026-08-15T00:00:00Z",
        )
        assert assessment is not None
        self.assertEqual(assessment.status, ALIGNMENT_STALE)

    def test_acceptable_lag_hybrid(self) -> None:
        assessment = assess_sec_market_hybrid_alignment(
            _crm_like_sec_financials(),
            market_cap=250_000_000_000.0,
            retrieved_at="2026-08-15T00:00:00Z",
        )
        assert assessment is not None
        self.assertEqual(assessment.status, ALIGNMENT_ACCEPTABLE_LAG)
        self.assertIn("TTM", assessment.limitations[0])

    def test_mixed_period_blocks_ev(self) -> None:
        sec = _crm_like_sec_financials(
            financial_period_end="2026-01-31",
            balance_sheet_period_end="2025-01-31",
        )
        self.assertFalse(ev_balance_sheet_aligned(sec))


class SecHybridValuationBuilderTests(unittest.TestCase):
    def _bundle(
        self,
        *,
        sec: dict,
        market_cap: float = 250_000_000_000.0,
        ratios_ttm: Optional[dict] = None,
        retrieved_at: str = "2026-08-15T12:00:00Z",
    ) -> CompanyProviderBundle:
        bundle = CompanyProviderBundle(symbol="CRM")
        bundle.sec_financials = sec
        bundle.profile = {"marketCap": market_cap, "companyName": "Salesforce"}
        bundle.ratios_ttm = ratios_ttm or {}
        bundle.retrieved_at = retrieved_at
        return bundle

    def test_produces_ps_pfcf_ev_ebit_when_safe(self) -> None:
        section = build_sec_hybrid_valuation(self._bundle(sec=_crm_like_sec_financials()))
        assert section is not None
        codes = {metric.code for metric in section.metrics}
        self.assertIn("price_to_sales", codes)
        self.assertIn("price_to_fcf", codes)
        self.assertIn("ev_to_ebit", codes)
        ps = next(m for m in section.metrics if m.code == "price_to_sales")
        self.assertAlmostEqual(ps.current_value or 0.0, 250_000_000_000 / 37_900_000_000, places=2)
        self.assertEqual(ps.alignment_status, ALIGNMENT_ACCEPTABLE_LAG)
        self.assertIsNotNone(ps.fundamental_period_end)

    def test_missing_debt_omits_ev(self) -> None:
        sec = _crm_like_sec_financials(total_debt=None)
        section = build_sec_hybrid_valuation(self._bundle(sec=sec))
        assert section is not None
        codes = {metric.code for metric in section.metrics}
        self.assertNotIn("ev_to_ebit", codes)

    def test_missing_cash_omits_ev(self) -> None:
        sec = _crm_like_sec_financials(cash=None)
        section = build_sec_hybrid_valuation(self._bundle(sec=sec))
        assert section is not None
        self.assertNotIn(
            "ev_to_ebit",
            {metric.code for metric in section.metrics},
        )

    def test_zero_revenue_omits_ps(self) -> None:
        sec = _crm_like_sec_financials(revenue=0.0)
        section = build_sec_hybrid_valuation(self._bundle(sec=sec))
        if section is not None:
            self.assertNotIn(
                "price_to_sales",
                {metric.code for metric in section.metrics},
            )
        else:
            self.assertIsNone(section)

    def test_negative_denominator_omits_ratio(self) -> None:
        sec = _crm_like_sec_financials(free_cash_flow=-1.0)
        section = build_sec_hybrid_valuation(self._bundle(sec=sec))
        assert section is not None
        self.assertNotIn(
            "price_to_fcf",
            {metric.code for metric in section.metrics},
        )

    def test_stale_rejects_all_metrics(self) -> None:
        sec = _crm_like_sec_financials(financial_period_end="2023-01-31")
        section = build_sec_hybrid_valuation(self._bundle(sec=sec))
        self.assertIsNone(section)


class ValuationFallbackIntegrationTests(unittest.TestCase):
    def _restricted_fmp(self) -> MagicMock:
        fmp = MagicMock()
        fmp.profile.return_value = {
            "companyName": "Salesforce, Inc.",
            "marketCap": 250_000_000_000.0,
        }
        restricted = FMPError("restricted", error_class="plan_restricted", status_code=402)
        for attr in (
            "income_statement_quarterly",
            "balance_sheet_quarterly",
            "cash_flow_quarterly",
            "ratios_ttm",
            "key_metrics_ttm",
            "stock_news",
        ):
            getattr(fmp, attr).side_effect = restricted
        fmp.ratios.return_value = []
        fmp.key_metrics.return_value = []
        fmp.stock_peers.return_value = []
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []
        return fmp

    def test_fmp_restricted_sec_fallback_populates_valuation(self) -> None:
        view = CompanyIntelligenceCoreService(self._restricted_fmp()).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=_crm_like_sec_financials(),
        )
        assert view.valuation is not None
        assert view.data_quality is not None
        self.assertTrue(view.data_quality.valuation_available)
        self.assertFalse(view.data_quality.historical_valuation_available)
        self.assertTrue(
            any("hibrit değerleme" in warning for warning in view.data_quality.warnings)
        )
        codes = {metric.code for metric in view.valuation.metrics}
        self.assertIn("price_to_sales", codes)

    def test_fmp_wins_when_ratios_available(self) -> None:
        fmp = self._restricted_fmp()
        fmp.ratios_ttm.return_value = {"priceToSalesRatioTTM": 9.5}
        fmp.ratios_ttm.side_effect = None
        view = CompanyIntelligenceCoreService(fmp).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=_crm_like_sec_financials(),
        )
        assert view.valuation is not None
        ps = next(m for m in view.valuation.metrics if m.code == "price_to_sales")
        self.assertEqual(ps.current_value, 9.5)
        self.assertIsNone(ps.data_family)

    def test_empty_ratios_shell_uses_sec_hybrid(self) -> None:
        fmp = self._restricted_fmp()
        fmp.ratios_ttm.side_effect = None
        fmp.ratios_ttm.return_value = {"symbol": "CRM"}
        view = CompanyIntelligenceCoreService(fmp).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=_crm_like_sec_financials(),
        )
        assert view.valuation is not None
        self.assertEqual(view.valuation.provenance.data_family, "sec_annual_market_hybrid")

    def test_aapl_firewall_blocks_ci_valuation(self) -> None:
        service = CompanyIntelligenceCoreService(self._restricted_fmp())
        blocked = ResearchEligibilityResult(
            symbol="AAPL",
            status=RESEARCH_STATUS_FAIL,
            research_allowed=False,
            participation_status="Uygun Değil",
            reason_codes=("participation_fail",),
            limitations=("Participation fail.",),
            provenance=(("gate", "test"),),
        )
        with self.assertRaises(ResearchEligibilityBlockedError):
            service.build_view(
                "AAPL",
                research_eligibility=blocked,
                sec_financials=_aapl_like_sec_financials(),
            )

    def test_serialization_has_no_secrets(self) -> None:
        view = CompanyIntelligenceCoreService(self._restricted_fmp()).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=_crm_like_sec_financials(),
        )
        assert view.valuation is not None
        payload = json.dumps(view.valuation.to_dict()).lower()
        self.assertNotIn("api_key", payload)
        self.assertNotIn("authorization", payload)

    def test_thesis_keeps_limited_valuation_context(self) -> None:
        ci = CompanyIntelligenceCoreService(self._restricted_fmp()).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=_crm_like_sec_financials(),
        )
        thesis = InvestmentThesisService().build_view(
            ci,
            candidate={"symbol": "CRM"},
            research_eligibility=research_eligibility_pass_fixture("CRM"),
        )
        self.assertEqual(thesis.valuation_context, "VALUATION_UNAVAILABLE")
        self.assertNotEqual(thesis.confidence, "HIGH")

    def test_scanner_metric_not_used_without_sec_evidence(self) -> None:
        view = CompanyIntelligenceCoreService(self._restricted_fmp()).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=_crm_like_sec_financials(
                revenue=None,
                free_cash_flow=None,
                operating_income=None,
            ),
        )
        self.assertIsNone(view.valuation)


class CrmProductionPathWiringTests(unittest.TestCase):
    def _mock_sec_client(self, sec_payload: dict) -> MagicMock:
        client = MagicMock()
        client.company_facts.return_value = {"facts": {"us-gaap": {}}}
        client.extract_financials.return_value = sec_payload
        client.resolve_entity_metadata.return_value = (
            {"sic_code": "7372", "sic_description": "Services-Prepackaged Software"},
            (("sic_source", "sec_submissions"),),
        )
        return client

    def _restricted_fmp(self) -> MagicMock:
        fmp = MagicMock()
        fmp.profile.return_value = {
            "companyName": "Salesforce, Inc.",
            "marketCap": 160_700_000_000.0,
        }
        restricted = FMPError("restricted", error_class="plan_restricted", status_code=402)
        for attr in (
            "income_statement_quarterly",
            "balance_sheet_quarterly",
            "cash_flow_quarterly",
            "ratios_ttm",
            "key_metrics_ttm",
            "stock_news",
            "ratios",
            "key_metrics",
        ):
            getattr(fmp, attr).side_effect = restricted
        fmp.stock_peers.return_value = []
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []
        return fmp

    def test_missing_sec_financials_wiring_keeps_valuation_unavailable(self) -> None:
        participation = build_company_report_participation(
            _crm_candidate(),
            sec_client=self._mock_sec_client(_crm_live_like_sec_financials()),
            fmp_client=self._restricted_fmp(),
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        assert participation.result is not None
        self.assertIsNotNone(participation.result.sec_financials)

        view = CompanyIntelligenceCoreService(self._restricted_fmp()).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
        )
        self.assertIsNone(view.financial_trends)
        self.assertIsNone(view.valuation)

    def test_company_report_path_passes_sec_financials_to_ci(self) -> None:
        fmp = self._restricted_fmp()
        participation = build_company_report_participation(
            _crm_candidate(),
            sec_client=self._mock_sec_client(_crm_live_like_sec_financials()),
            fmp_client=fmp,
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        assert participation.result is not None
        self.assertIsNotNone(participation.result.sec_financials)

        view = CompanyIntelligenceCoreService(fmp).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=participation.result.sec_financials,
        )
        self.assertIsNotNone(view.financial_trends)
        assert view.valuation is not None
        codes = {metric.code for metric in view.valuation.metrics}
        self.assertIn("price_to_sales", codes)
        self.assertIn("price_to_fcf", codes)
        self.assertIn("ev_to_ebit", codes)
        self.assertEqual(view.valuation.provenance.data_family, "sec_annual_market_hybrid")


class GenericEligibleSymbolOrchestrationTests(unittest.TestCase):
    """SEC fallback + hybrid valuation must work for any eligible symbol, not CRM-only."""

    def _restricted_fmp(self, *, market_cap: float, company_name: str) -> MagicMock:
        fmp = MagicMock()
        fmp.profile.return_value = {
            "companyName": company_name,
            "marketCap": market_cap,
        }
        restricted = FMPError("restricted", error_class="plan_restricted", status_code=402)
        for attr in (
            "income_statement_quarterly",
            "balance_sheet_quarterly",
            "cash_flow_quarterly",
            "ratios_ttm",
            "key_metrics_ttm",
            "stock_news",
            "ratios",
            "key_metrics",
        ):
            getattr(fmp, attr).side_effect = restricted
        fmp.stock_peers.return_value = []
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []
        return fmp

    def test_jnj_generic_sec_trends_and_hybrid_valuation_path(self) -> None:
        fmp = self._restricted_fmp(
            market_cap=380_000_000_000.0,
            company_name="Johnson & Johnson",
        )
        sec_fin = _jnj_live_like_sec_financials()
        view = CompanyIntelligenceCoreService(fmp).build_view(
            "JNJ",
            research_eligibility=research_eligibility_pass_fixture("JNJ"),
            sec_financials=sec_fin,
        )
        self.assertIsNotNone(view.financial_trends)
        assert view.financial_trends is not None
        self.assertEqual(
            view.financial_trends.provenance.data_family,
            "financial_statements_annual",
        )
        self.assertIsNotNone(view.valuation)
        assert view.valuation is not None
        codes = {metric.code for metric in view.valuation.metrics}
        self.assertIn("price_to_sales", codes)
        self.assertIn("price_to_fcf", codes)
        self.assertIn("ev_to_ebit", codes)
        self.assertEqual(view.valuation.provenance.data_family, "sec_annual_market_hybrid")

    def test_jnj_thesis_uses_same_downstream_logic(self) -> None:
        fmp = self._restricted_fmp(
            market_cap=380_000_000_000.0,
            company_name="Johnson & Johnson",
        )
        view = CompanyIntelligenceCoreService(fmp).build_view(
            "JNJ",
            research_eligibility=research_eligibility_pass_fixture("JNJ"),
            sec_financials=_jnj_live_like_sec_financials(),
        )
        thesis = InvestmentThesisService().build_view(
            view,
            candidate={"symbol": "JNJ"},
            research_eligibility=research_eligibility_pass_fixture("JNJ"),
        )
        self.assertEqual(thesis.valuation_context, "VALUATION_UNAVAILABLE")
        self.assertNotEqual(thesis.confidence, "HIGH")

    def test_jnj_production_participation_wires_sec_into_ci(self) -> None:
        fmp = self._restricted_fmp(
            market_cap=380_000_000_000.0,
            company_name="Johnson & Johnson",
        )
        sec_client = MagicMock()
        sec_client.company_facts.return_value = {"facts": {"us-gaap": {}}}
        sec_client.extract_financials.return_value = _jnj_live_like_sec_financials()
        sec_client.resolve_entity_metadata.return_value = (
            {"sic_code": "2834", "sic_description": "Pharmaceutical Preparations"},
            (("sic_source", "sec_submissions"),),
        )
        participation = build_company_report_participation(
            {
                "symbol": "JNJ",
                "company_name": "Johnson & Johnson",
                "sector_theme": "Healthcare",
            },
            sec_client=sec_client,
            fmp_client=fmp,
            sec_ticker_lookup=JNJ_SEC_LOOKUP,
        )
        assert participation.result is not None
        self.assertIsNotNone(participation.result.sec_financials)
        view = CompanyIntelligenceCoreService(fmp).build_view(
            "JNJ",
            research_eligibility=research_eligibility_pass_fixture("JNJ"),
            sec_financials=participation.result.sec_financials,
        )
        self.assertIsNotNone(view.financial_trends)
        self.assertIsNotNone(view.valuation)


class CrmProfileRateLimitHybridFallbackTests(unittest.TestCase):
    def _mock_sec_client(self, sec_payload: dict) -> MagicMock:
        client = MagicMock()
        client.company_facts.return_value = {"facts": {"us-gaap": {}}}
        client.extract_financials.return_value = sec_payload
        client.resolve_entity_metadata.return_value = (
            {"sic_code": "7372", "sic_description": "Services-Prepackaged Software"},
            (("sic_source", "sec_submissions"),),
        )
        return client

    def _rate_limited_fmp(self) -> MagicMock:
        fmp = MagicMock()
        fmp.profile.side_effect = FMPError("rate limit", error_class="rate_limit", status_code=429)
        restricted = FMPError("restricted", error_class="plan_restricted", status_code=402)
        for attr in (
            "income_statement_quarterly",
            "balance_sheet_quarterly",
            "cash_flow_quarterly",
            "ratios_ttm",
            "key_metrics_ttm",
            "stock_news",
            "ratios",
            "key_metrics",
        ):
            getattr(fmp, attr).side_effect = restricted
        fmp.stock_peers.return_value = []
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []
        return fmp

    def test_profile_rate_limit_without_fallback_has_no_hybrid_metrics(self) -> None:
        participation = build_company_report_participation(
            _crm_candidate(),
            sec_client=self._mock_sec_client(_crm_live_like_sec_financials()),
            fmp_client=self._rate_limited_fmp(),
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        assert participation.result is not None
        view = CompanyIntelligenceCoreService(self._rate_limited_fmp()).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=participation.result.sec_financials,
        )
        self.assertIsNone(view.valuation)
        self.assertFalse(view.data_quality.valuation_available)
        self.assertIn("profile:RATE_LIMIT", view.data_quality.provider_failures)

    def test_profile_rate_limit_with_candidate_market_cap_fallback_builds_hybrid_metrics(
        self,
    ) -> None:
        participation = build_company_report_participation(
            _crm_candidate(),
            sec_client=self._mock_sec_client(_crm_live_like_sec_financials()),
            fmp_client=self._rate_limited_fmp(),
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        assert participation.result is not None
        view = CompanyIntelligenceCoreService(self._rate_limited_fmp()).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=participation.result.sec_financials,
            market_cap_fallback=_crm_candidate()["market_cap"],
        )
        assert view.valuation is not None
        codes = {metric.code for metric in view.valuation.metrics}
        self.assertIn("price_to_sales", codes)
        self.assertIn("price_to_fcf", codes)
        self.assertIn("ev_to_ebit", codes)
        self.assertTrue(view.data_quality.valuation_available)
        self.assertTrue(
            any(
                "aday kaydındaki piyasa değeri" in limitation
                for metric in view.valuation.metrics
                for limitation in metric.limitations
            )
        )

    def test_rate_limited_profile_metrics_propagate_to_ai_generation_context(self) -> None:
        from services.ai_research_summary_valuation_semantics import derive_valuation_semantics
        from services.unified_research_service import UnifiedResearchService

        participation = build_company_report_participation(
            _crm_candidate(),
            sec_client=self._mock_sec_client(_crm_live_like_sec_financials()),
            fmp_client=self._rate_limited_fmp(),
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        assert participation.result is not None
        fmp = self._rate_limited_fmp()
        ci = CompanyIntelligenceCoreService(fmp).build_view(
            "CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            sec_financials=participation.result.sec_financials,
            market_cap_fallback=_crm_candidate()["market_cap"],
        )
        thesis = InvestmentThesisService().build_view(
            ci,
            research_eligibility=research_eligibility_pass_fixture("CRM"),
        )
        unified = UnifiedResearchService().build_context(
            symbol="CRM",
            research_eligibility=research_eligibility_pass_fixture("CRM"),
            company_intelligence_view=ci,
            investment_thesis_view=thesis,
            candidate=_crm_candidate(),
        )
        semantics = derive_valuation_semantics(unified)
        self.assertTrue(semantics.current_metrics_available)
        self.assertGreaterEqual(len(semantics.available_metrics), 3)
        serialized = unified.company_intelligence or {}
        self.assertGreaterEqual(len(serialized.get("valuation_metrics") or []), 3)


class ValuationUiSmokeTests(unittest.TestCase):
    def test_hybrid_metric_contract_fields(self) -> None:
        bundle = CompanyProviderBundle(symbol="CRM")
        bundle.sec_financials = _crm_like_sec_financials()
        bundle.profile = {"marketCap": 250_000_000_000.0}
        bundle.retrieved_at = "2026-08-15T12:00:00Z"
        section = build_sec_hybrid_valuation(bundle)
        assert section is not None
        metric = section.metrics[0]
        self.assertTrue(metric.limitations)
        self.assertEqual(metric.source_provider, "sec+fmp")


if __name__ == "__main__":
    unittest.main()
