from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.company_intelligence_contract import ValuationMetric
from services.company_intelligence_core_service import _build_factual_risks
from services.company_intelligence_data import (
    CompanyProviderBundle,
    load_company_provider_bundle,
    load_sec_hybrid_historical_prices,
    max_expected_provider_calls,
)
from services.company_intelligence_historical_hybrid_valuation import (
    align_price_on_or_before,
    build_historical_hybrid_samples,
    enrich_sec_hybrid_metrics,
)
from services.company_intelligence_sec_valuation import build_sec_hybrid_valuation
from services.fmp_client import FMPError
from services.sec_financial_client import SECFinancialClient


def _annual_history():
    return [
        {"period_end": "2025-01-31", "revenue": 40.0, "free_cash_flow": 10.0, "weighted_average_shares": 10.0},
        {"period_end": "2024-01-31", "revenue": 32.0, "free_cash_flow": 8.0, "weighted_average_shares": 10.0},
        {"period_end": "2023-01-31", "revenue": 25.0, "free_cash_flow": 5.0, "weighted_average_shares": 10.0},
    ]


def _prices():
    return [
        {"date": "2025-01-31", "price": 20.0},
        {"date": "2024-01-30", "price": 16.0},
        {"date": "2023-01-27", "price": 10.0},
    ]


class HistoricalHybridValuationTests(unittest.TestCase):
    def test_price_alignment_uses_last_price_on_or_before_period_end(self) -> None:
        price, aligned_date, lag = align_price_on_or_before(
            [{"date": "2025-02-01", "price": 99}, {"date": "2025-01-30", "price": 20}],
            "2025-01-31",
        )
        self.assertEqual(price, 20.0)
        self.assertEqual(aligned_date, "2025-01-30")
        self.assertEqual(lag, 1)

    def test_stale_price_is_rejected(self) -> None:
        price, _, _ = align_price_on_or_before(
            [{"date": "2025-01-20", "price": 20}],
            "2025-01-31",
        )
        self.assertIsNone(price)

    def test_builds_ps_and_pfcf_samples(self) -> None:
        samples = build_historical_hybrid_samples(_annual_history(), _prices())
        self.assertEqual(len(samples["price_to_sales"]), 3)
        self.assertEqual(len(samples["price_to_fcf"]), 3)
        self.assertAlmostEqual(samples["price_to_sales"][0], 5.0)
        self.assertAlmostEqual(samples["price_to_fcf"][0], 20.0)


    def test_exact_historical_median_is_not_misclassified_by_tied_percentile(self) -> None:
        metric = ValuationMetric(
            code="price_to_sales",
            label="P/S",
            current_value=5.0,
            historical_median=None,
            premium_to_median_pct=None,
            position="INSUFFICIENT_DATA",
        )
        history = [
            {"period_end": "2025-01-31", "revenue": 40.0, "free_cash_flow": 10.0, "weighted_average_shares": 10.0},
            {"period_end": "2024-01-31", "revenue": 32.0, "free_cash_flow": 8.0, "weighted_average_shares": 10.0},
            {"period_end": "2023-01-31", "revenue": 20.0, "free_cash_flow": 5.0, "weighted_average_shares": 10.0},
        ]
        prices = [
            {"date": "2025-01-31", "price": 20.0},
            {"date": "2024-01-31", "price": 16.0},
            {"date": "2023-01-31", "price": 10.0},
        ]
        enriched = enrich_sec_hybrid_metrics(
            (metric,),
            annual_history=history,
            historical_prices=prices,
        )
        self.assertEqual(enriched[0].historical_median, 5.0)
        self.assertEqual(enriched[0].position, "NEAR_HISTORICAL_MEDIAN")

    def test_builder_enriches_only_ps_and_pfcf_history(self) -> None:
        bundle = CompanyProviderBundle(symbol="CRM")
        bundle.profile = {"marketCap": 250.0}
        bundle.retrieved_at = "2025-02-15T00:00:00Z"
        bundle.sec_financials = {
            "revenue": 40.0,
            "free_cash_flow": 10.0,
            "operating_income": 8.0,
            "total_debt": 12.0,
            "cash": 2.0,
            "financial_period_end": "2025-01-31",
            "balance_sheet_period_end": "2025-01-31",
            "annual_periods_found": 3,
            "annual_history": _annual_history(),
        }
        bundle.historical_prices = _prices()
        section = build_sec_hybrid_valuation(bundle)
        assert section is not None
        by_code = {metric.code: metric for metric in section.metrics}
        self.assertIsNotNone(by_code["price_to_sales"].historical_median)
        self.assertIsNotNone(by_code["price_to_fcf"].historical_median)
        self.assertIsNone(by_code["ev_to_ebit"].historical_median)

    def test_historical_loader_is_one_bounded_call(self) -> None:
        bundle = CompanyProviderBundle(symbol="CRM")
        bundle.sec_financials = {"annual_history": _annual_history()}
        fmp = MagicMock()
        fmp.historical_price_eod_light.return_value = _prices()
        load_sec_hybrid_historical_prices(fmp, bundle)
        load_sec_hybrid_historical_prices(fmp, bundle)
        self.assertEqual(fmp.historical_price_eod_light.call_count, 1)
        self.assertEqual(bundle.historical_prices, _prices())

    def test_sec_hybrid_history_respects_fmp_call_budget(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {"companyName": "CRM"}
        fmp.income_statement_quarterly.return_value = []
        fmp.balance_sheet_quarterly.return_value = []
        fmp.cash_flow_quarterly.return_value = []
        fmp.ratios_ttm.return_value = {}
        fmp.key_metrics_ttm.return_value = {}
        fmp.stock_peers.return_value = ["A", "B", "C"]
        fmp.stock_news.return_value = []
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []
        fmp.historical_price_eod_light.return_value = _prices()

        bundle = load_company_provider_bundle(
            fmp,
            "CRM",
            sec_financials={"annual_history": _annual_history()},
        )
        self.assertNotIn("ratios_history", bundle.call_counts)
        self.assertNotIn("key_metrics_history", bundle.call_counts)
        load_sec_hybrid_historical_prices(fmp, bundle)
        self.assertLessEqual(sum(bundle.call_counts.values()), 15)
        self.assertLessEqual(max_expected_provider_calls(peer_count=4), 15)
        self.assertEqual(fmp.historical_price_eod_light.call_count, 1)


    def test_historical_loader_refreshes_when_sec_history_scope_changes(self) -> None:
        bundle = CompanyProviderBundle(symbol="CRM")
        bundle.sec_financials = {"annual_history": _annual_history()}
        fmp = MagicMock()
        fmp.historical_price_eod_light.return_value = _prices()

        load_sec_hybrid_historical_prices(fmp, bundle)
        first_scope = bundle.historical_price_scope
        self.assertEqual(fmp.historical_price_eod_light.call_count, 1)

        shifted = [
            {**row, "period_end": str(int(row["period_end"][:4]) + 1) + row["period_end"][4:]}
            for row in _annual_history()
        ]
        bundle.sec_financials = {"annual_history": shifted}
        load_sec_hybrid_historical_prices(fmp, bundle)

        self.assertEqual(fmp.historical_price_eod_light.call_count, 2)
        self.assertNotEqual(bundle.historical_price_scope, first_scope)

    def test_historical_loader_skips_nonviable_history(self) -> None:
        bundle = CompanyProviderBundle(symbol="CRM")
        bundle.sec_financials = {
            "annual_history": [
                {"period_end": "2025-01-31", "revenue": 40.0, "free_cash_flow": 10.0, "weighted_average_shares": None},
                {"period_end": "2024-01-31", "revenue": 32.0, "free_cash_flow": 8.0, "weighted_average_shares": None},
                {"period_end": "2023-01-31", "revenue": 25.0, "free_cash_flow": 5.0, "weighted_average_shares": None},
            ]
        }
        fmp = MagicMock()
        load_sec_hybrid_historical_prices(fmp, bundle)
        fmp.historical_price_eod_light.assert_not_called()


    def test_historical_price_failure_keeps_current_hybrid_available(self) -> None:
        bundle = CompanyProviderBundle(symbol="CRM")
        bundle.profile = {"marketCap": 250.0}
        bundle.retrieved_at = "2025-02-15T00:00:00Z"
        bundle.sec_financials = {
            "revenue": 40.0,
            "free_cash_flow": 10.0,
            "operating_income": 8.0,
            "total_debt": 12.0,
            "cash": 2.0,
            "financial_period_end": "2025-01-31",
            "balance_sheet_period_end": "2025-01-31",
            "annual_periods_found": 3,
            "annual_history": _annual_history(),
        }
        fmp = MagicMock()
        fmp.historical_price_eod_light.side_effect = FMPError(
            "restricted",
            error_class="plan_restricted",
            endpoint="historical-price-eod/light",
        )

        load_sec_hybrid_historical_prices(fmp, bundle)
        self.assertEqual(bundle.historical_prices, [])
        self.assertIn("historical_price_eod_light:plan_restricted", bundle.failures)

        section = build_sec_hybrid_valuation(bundle)
        assert section is not None
        self.assertTrue(any(metric.current_value is not None for metric in section.metrics))
        self.assertTrue(all(metric.historical_median is None for metric in section.metrics))

    def test_hybrid_valuation_risk_preserves_metric_provenance(self) -> None:
        bundle = CompanyProviderBundle(symbol="CRM")
        bundle.profile = {"marketCap": 250.0}
        bundle.retrieved_at = "2025-02-15T00:00:00Z"
        bundle.sec_financials = {
            "revenue": 40.0,
            "free_cash_flow": 10.0,
            "operating_income": 8.0,
            "total_debt": 12.0,
            "cash": 2.0,
            "financial_period_end": "2025-01-31",
            "balance_sheet_period_end": "2025-01-31",
            "annual_periods_found": 3,
            "annual_history": _annual_history(),
        }
        bundle.historical_prices = _prices()
        section = build_sec_hybrid_valuation(bundle)
        assert section is not None
        premium_metric = next(
            metric
            for metric in section.metrics
            if metric.position in {"ABOVE_HISTORICAL_RANGE", "ABOVE_HISTORICAL_MEDIAN"}
        )
        risks = _build_factual_risks(None, None, section, None, None)
        risk = next(item for item in risks if item.code == "RISK_VALUATION_PREMIUM")
        self.assertEqual(risk.source, premium_metric.source_provider)
        self.assertEqual(risk.confidence, premium_metric.confidence)


class SecAnnualHistoryExtractionTests(unittest.TestCase):
    def test_build_annual_history_requires_ocf_and_capex_for_fcf(self) -> None:
        client = SECFinancialClient(contact_email="test@example.com")
        rows = client._build_annual_history(
            revenue=[
                {"end": "2025-01-31", "value": 100.0},
                {"end": "2024-01-31", "value": 90.0},
            ],
            operating_cash=[
                {"end": "2025-01-31", "value": 20.0},
                {"end": "2024-01-31", "value": 18.0},
            ],
            capex=[{"end": "2025-01-31", "value": 5.0}],
            shares=[
                {"end": "2025-01-31", "value": 10.0},
                {"end": "2024-01-31", "value": 10.0},
            ],
        )
        self.assertEqual(rows[0]["free_cash_flow"], 15.0)
        self.assertIsNone(rows[1]["free_cash_flow"])
        self.assertEqual(rows[0]["weighted_average_shares"], 10.0)


if __name__ == "__main__":
    unittest.main()
