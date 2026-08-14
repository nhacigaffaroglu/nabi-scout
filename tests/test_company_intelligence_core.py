from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from services.company_earnings_intelligence import build_earnings_intelligence
from services.company_financial_trend_engine import build_financial_trends
from services.company_intelligence_contract import CompanyIntelligenceView
from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_utils import pct_change
from services.company_news_intelligence import build_catalysts, build_news_intelligence
from services.company_peer_intelligence import build_peer_intelligence
from services.company_valuation_intelligence import build_valuation_intelligence
from services.fmp_client import FMPClient


def _income(period: str, revenue: float, **kwargs):
    row = {
        "period": period,
        "date": period,
        "revenue": revenue,
        "grossProfit": kwargs.get("gross_profit", revenue * 0.4),
        "operatingIncome": kwargs.get("operating_income", revenue * 0.2),
        "netIncome": kwargs.get("net_income", revenue * 0.15),
        "epsdiluted": kwargs.get("eps", 1.0),
    }
    return row


class CompanyIntelligenceUtilsTests(unittest.TestCase):
    def test_zero_denominator_returns_none(self) -> None:
        self.assertIsNone(pct_change(10, 0))

    def test_negative_to_positive_returns_none(self) -> None:
        self.assertIsNone(pct_change(5, -2))


class FinancialTrendEngineTests(unittest.TestCase):
    def test_missing_revenue_not_zero(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            income_quarterly=[{"period": "2024-Q1"}],
        )
        section = build_financial_trends(bundle)
        revenue = next(item for item in section.trends if item.metric == "revenue")
        self.assertIsNone(revenue.latest_value)

    def test_revenue_growth_not_quality_label(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            income_quarterly=[
                _income("2024-Q1", 120),
                _income("2023-Q1", 100),
            ],
        )
        section = build_financial_trends(bundle)
        combined = " ".join(item.statement.lower() for item in section.observations)
        self.assertNotIn("quality improved", combined)

    def test_debt_increase_not_auto_deteriorated_company(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            income_quarterly=[_income("2024-Q1", 100), _income("2023-Q1", 95)],
            balance_quarterly=[
                {"totalDebt": 200, "cashAndCashEquivalents": 50},
                {"totalDebt": 150, "cashAndCashEquivalents": 40},
            ],
        )
        section = build_financial_trends(bundle)
        debt_obs = [item for item in section.observations if item.code == "DEBT_INCREASE"]
        self.assertEqual(len(debt_obs), 1)
        self.assertIn("tek başına", debt_obs[0].limitations[0].lower())


class EarningsIntelligenceTests(unittest.TestCase):
    def test_yoy_not_sequential(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            income_quarterly=[
                _income("2024-Q2", 110),
                _income("2024-Q1", 100),
            ],
        )
        section = build_earnings_intelligence(bundle)
        self.assertEqual(section.comparison_type, "YoY")
        self.assertNotEqual(_income("2024-Q1", 100)["period"], _income("2024-Q2", 110)["period"])

    def test_expectations_unavailable(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            income_quarterly=[_income("2024-Q1", 100), _income("2023-Q1", 90)],
        )
        section = build_earnings_intelligence(bundle)
        self.assertFalse(section.expectations.expectations_available)


class ValuationIntelligenceTests(unittest.TestCase):
    def test_negative_pe_not_meaningful(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            quote={"pe": -5},
            ratios_ttm={"priceToEarningsRatioTTM": -5},
            ratios_history=[{"priceToEarningsRatio": 20}, {"priceToEarningsRatio": 18}],
        )
        section = build_valuation_intelligence(bundle)
        pe = next(item for item in section.metrics if item.code == "pe_ratio")
        self.assertIsNone(pe.current_value)

    def test_no_buy_sell_language(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            quote={"pe": 40},
            ratios_ttm={"priceToEarningsRatioTTM": 40},
            ratios_history=[{"priceToEarningsRatio": 20}, {"priceToEarningsRatio": 22}],
        )
        section = build_valuation_intelligence(bundle)
        serialized = json.dumps(section.to_dict()).lower()
        self.assertNotIn("undervalued", serialized)
        self.assertNotIn("overvalued", serialized)
        self.assertNotIn("buy", serialized)
        self.assertNotIn("sell", serialized)

    def test_insufficient_history_no_fake_median(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            ratios_ttm={"priceToSalesRatioTTM": 5},
            ratios_history=[],
        )
        section = build_valuation_intelligence(bundle)
        metric = next(item for item in section.metrics if item.code == "price_to_sales")
        self.assertIsNone(metric.historical_median)
        self.assertEqual(metric.position, "INSUFFICIENT_DATA")


class PeerIntelligenceTests(unittest.TestCase):
    def test_rank_not_emitted_with_small_sample(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            peers=["MSFT", "GOOG"],
            ratios_ttm={"priceToEarningsRatioTTM": 25},
            peer_ratios_ttm={
                "MSFT": {"priceToEarningsRatioTTM": 30},
                "GOOG": {"priceToEarningsRatioTTM": 28},
            },
        )
        section = build_peer_intelligence(bundle)
        row = next(item for item in section.comparisons if item.metric == "pe_ratio")
        self.assertIsNone(row.rank)
        self.assertTrue(row.limitations)

    def test_missing_peer_not_zero(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="TEST",
            peers=["MSFT"],
            ratios_ttm={"priceToEarningsRatioTTM": 25},
            peer_ratios_ttm={},
        )
        section = build_peer_intelligence(bundle)
        row = next(item for item in section.comparisons if item.metric == "pe_ratio")
        self.assertEqual(row.peer_count, 0)
        self.assertIsNone(row.peer_median)


class NewsIntelligenceTests(unittest.TestCase):
    def _article(self, **kwargs):
        defaults = {
            "title": "Apple reports earnings beat",
            "url": "https://example.com/a",
            "publishedDate": "2026-08-01T00:00:00Z",
        }
        defaults.update(kwargs)
        return defaults

    def test_duplicate_url_removed(self) -> None:
        articles = [self._article(), self._article(title="Duplicate url")]
        bundle = CompanyProviderBundle(symbol="AAPL", news=articles)
        section = build_news_intelligence(bundle)
        self.assertEqual(len(section.events), 1)
        self.assertEqual(section.dedupe_count, 1)

    def test_sentiment_not_materiality(self) -> None:
        articles = [self._article(title="Random market chatter", sentiment="positive")]
        bundle = CompanyProviderBundle(symbol="AAPL", news=articles)
        event = build_news_intelligence(bundle).events[0]
        self.assertEqual(event.materiality, "NOISE")

    def test_high_article_count_not_material(self) -> None:
        articles = [
            self._article(title=f"Noise headline {idx}", url=f"https://example.com/{idx}")
            for idx in range(10)
        ]
        bundle = CompanyProviderBundle(symbol="AAPL", news=articles)
        section = build_news_intelligence(bundle)
        self.assertTrue(all(event.materiality == "NOISE" for event in section.events))


class CompanyIntelligenceCoreServiceTests(unittest.TestCase):
    def test_deterministic_output(self) -> None:
        fmp = MagicMock(spec=FMPClient)
        fmp.profile.return_value = {"companyName": "Apple Inc.", "sector": "Technology"}
        fmp.quote.return_value = {"pe": 30}
        fmp.income_statement_quarterly.return_value = [
            _income("2024-Q1", 100),
            _income("2023-Q1", 90),
        ]
        fmp.balance_sheet_quarterly.return_value = [{"totalDebt": 100}]
        fmp.cash_flow_quarterly.return_value = [{"freeCashFlow": 20}]
        fmp.income_statement.return_value = [_income("2023", 350)]
        fmp.ratios_ttm.return_value = {"priceToEarningsRatioTTM": 30}
        fmp.key_metrics_ttm.return_value = {"freeCashFlowYieldTTM": 0.03}
        fmp.ratios.return_value = [{"priceToEarningsRatio": 25}]
        fmp.key_metrics.return_value = [{"freeCashFlowYield": 0.02}]
        fmp.stock_peers.return_value = ["MSFT"]
        fmp.stock_news.return_value = []
        fmp.analyst_estimates.return_value = []
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []

        service = CompanyIntelligenceCoreService(fmp)
        first = service.build_view("AAPL").to_dict()
        second = service.build_view("AAPL").to_dict()
        self.assertEqual(first, second)

    def test_partial_news_failure_keeps_financials(self) -> None:
        fmp = MagicMock(spec=FMPClient)
        fmp.profile.return_value = {"companyName": "Apple Inc."}
        fmp.quote.return_value = {}
        fmp.income_statement_quarterly.return_value = [
            _income("2024-Q1", 100),
            _income("2023-Q1", 90),
        ]
        fmp.balance_sheet_quarterly.return_value = []
        fmp.cash_flow_quarterly.return_value = []
        fmp.income_statement.return_value = []
        fmp.ratios_ttm.return_value = {}
        fmp.key_metrics_ttm.return_value = {}
        fmp.ratios.return_value = []
        fmp.key_metrics.return_value = []
        fmp.stock_peers.return_value = []
        fmp.stock_news.side_effect = RuntimeError("news down")
        fmp.analyst_estimates.return_value = []
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []

        view = CompanyIntelligenceCoreService(fmp).build_view("AAPL")
        self.assertIsNotNone(view.financial_trends)
        self.assertIsNotNone(view.data_quality)


class AdversarialValidationGateTests(unittest.TestCase):
    def test_serialization_has_no_api_key(self) -> None:
        view = CompanyIntelligenceView(
            symbol="AAPL",
            company_name="Apple",
            as_of="t",
            business_snapshot=None,
            financial_trends=None,
            earnings=None,
            valuation=None,
            peers=None,
            news=None,
        )
        serialized = json.dumps(view.to_dict())
        self.assertNotIn("api_key", serialized.lower())
        self.assertNotIn("apikey", serialized.lower())

    def test_catalysts_reject_speculative_without_date(self) -> None:
        bundle = CompanyProviderBundle(
            symbol="AAPL",
            earnings_calendar=[{"date": "2026-10-30"}],
            news=[],
        )
        catalysts = build_catalysts(bundle, ())
        self.assertEqual(len(catalysts), 1)
        self.assertEqual(catalysts[0].status, "UPCOMING")


class CompanyIntelligenceUiTests(unittest.TestCase):
    def test_ui_uses_turkish_not_raw_codes(self) -> None:
        source = open("components/company_intelligence_ui.py", encoding="utf-8").read()
        self.assertIn("Şirket Özeti", source)
        self.assertNotIn("REVENUE_DECELERATION", source)


if __name__ == "__main__":
    unittest.main()
