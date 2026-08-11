import unittest
from unittest.mock import MagicMock

from services.fmp_client import FMPError
from services.fund_analysis_contract import (
    ANALYSIS_KIND_FUND,
    DIMENSION_CONCENTRATION,
    DIMENSION_COST,
    DIMENSION_LIQUIDITY,
    LABEL_CONFIGURED_PARTICIPATION,
    LABEL_INCELEME_UYGUN,
    LABEL_VERI_YETERSIZ,
    LABEL_YOGUNLASMA_RISKI,
    LABEL_YUKSEK_MALIYET,
    PARTICIPATION_SOURCE_CONFIGURED,
)
from services.fund_analysis_service import (
    EXPENSE_HIGH_THRESHOLD_PCT,
    MIN_COMPLETENESS_FOR_DIMENSIONS,
    TOP10_CONCENTRATION_RISK_THRESHOLD_PCT,
    analyze_fund,
    score_concentration_dimension,
    score_cost_dimension,
    score_liquidity_dimension,
)
from services.symbol_resolver_service import ResolvedSecurity


def resolved_etf(symbol: str, **overrides):
    base = {
        "symbol": symbol,
        "company_name": symbol,
        "exchange": "NYSE Arca",
        "security_type": "ETF",
        "issuer_category": "FUND",
        "is_etf": True,
        "cik": None,
        "resolution_source": "config_etf",
        "resolution_confidence": "HIGH",
        "is_equity_eligible": False,
    }
    base.update(overrides)
    return ResolvedSecurity(**base)


def full_etf_info(symbol: str = "SPUS"):
    return {
        "symbol": symbol,
        "name": "SP Funds S&P 500 Sharia Industry Exclusions ETF",
        "etfCompany": "SP Funds",
        "exchange": "NYSE Arca",
        "assetClass": "Equity",
        "domicile": "US",
        "indexName": "S&P 500 Sharia Industry Exclusions",
        "inceptionDate": "2019-12-16",
        "expenseRatio": 0.49,
        "aum": 2_860_058_355,
        "holdingsCount": 200,
    }


def sample_holdings(count: int = 12):
    rows = []
    for index in range(count):
        rows.append({
            "asset": f"T{index}",
            "name": f"Ticker {index}",
            "weightPercentage": 10.0 if index < 5 else 2.0,
        })
    return rows


def sample_price_history(count: int = 70, *, start_price: float = 100.0, end_price: float = 110.0):
    from datetime import date, timedelta

    rows = []
    current = date(2024, 1, 2)
    for index in range(count):
        if count == 1:
            price = end_price
        else:
            price = start_price + (end_price - start_price) * index / (count - 1)
        rows.append({"date": current.isoformat(), "price": price})
        current += timedelta(days=1)
    return rows


class FundAnalysisServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fmp = MagicMock()
        self.fmp.historical_price_eod_light.return_value = []

    def test_spus_full_fund_result(self) -> None:
        self.fmp.etf_info.return_value = full_etf_info("SPUS")
        self.fmp.etf_holdings.return_value = sample_holdings()
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 56.33, "volume": 500_000}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.analysis_kind, ANALYSIS_KIND_FUND)
        self.assertEqual(result.symbol, "SPUS")
        self.assertEqual(result.participation_source, PARTICIPATION_SOURCE_CONFIGURED)
        self.assertEqual(result.participation_status, "Uygun")
        self.assertEqual(result.participation_score, 100)
        self.assertEqual(result.expense_ratio, 0.49)
        self.assertIsNotNone(result.top10_concentration_pct)
        self.assertGreaterEqual(result.data_completeness_pct, MIN_COMPLETENESS_FOR_DIMENSIONS)
        self.assertTrue(result.top_holdings)
        self.assertIn(LABEL_CONFIGURED_PARTICIPATION, result.labels)
        self.assertNotIn("nabi_score", result.to_dict())

    def test_hlal_configured_participation(self) -> None:
        self.fmp.etf_info.return_value = full_etf_info("HLAL")
        self.fmp.etf_holdings.return_value = sample_holdings(8)
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 69.9}

        result = analyze_fund(resolved_etf("HLAL"), fmp_client=self.fmp)

        self.assertEqual(result.participation_source, PARTICIPATION_SOURCE_CONFIGURED)
        self.assertEqual(result.participation_status, "Uygun")

    def test_spsk_sukuk_identity(self) -> None:
        self.fmp.etf_info.return_value = {
            **full_etf_info("SPSK"),
            "name": "SP Funds Dow Jones Global Sukuk ETF",
        }
        self.fmp.etf_holdings.return_value = sample_holdings(6)
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 17.8}

        result = analyze_fund(resolved_etf("SPSK"), fmp_client=self.fmp)

        self.assertIn("Sukuk", result.fund_name or "")

    def test_qqq_non_configured_participation(self) -> None:
        self.fmp.etf_info.return_value = full_etf_info("QQQ")
        self.fmp.etf_holdings.return_value = sample_holdings()
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 380.0}

        result = analyze_fund(resolved_etf("QQQ"), fmp_client=self.fmp)

        self.assertIsNone(result.participation_source)
        self.assertEqual(result.participation_status, "Kontrol Et")

    def test_rate_limited_etf_endpoints_partial_result(self) -> None:
        self.fmp.etf_info.side_effect = FMPError("limited", error_class="rate_limit")
        self.fmp.etf_holdings.side_effect = FMPError("limited", error_class="rate_limit")
        self.fmp.profile.return_value = {
            "companyName": "SP Funds S&P 500 Sharia Industry Exclusions ETF",
            "exchange": "NYSE Arca",
            "mktCap": 2_860_058_355,
            "price": 56.33,
        }
        self.fmp.quote.return_value = {"price": 56.33, "volume": 100_000}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.endpoint_status["fmp_etf_info"], "RATE_LIMIT")
        self.assertEqual(result.endpoint_status["fmp_etf_holdings"], "RATE_LIMIT")
        self.assertIsNone(result.expense_ratio)
        self.assertIsNone(result.top10_concentration_pct)
        dimensions = {item.dimension for item in result.dimension_scores}
        self.assertNotIn(DIMENSION_COST, dimensions)
        self.assertNotIn(DIMENSION_CONCENTRATION, dimensions)
        self.assertTrue(result.warnings)

    def test_plan_restricted_endpoint(self) -> None:
        self.fmp.etf_info.side_effect = FMPError(
            "denied",
            error_class="plan_restricted",
        )
        self.fmp.etf_holdings.side_effect = FMPError(
            "denied",
            error_class="plan_restricted",
        )
        self.fmp.profile.return_value = {"companyName": "SPUS", "price": 1.0}
        self.fmp.quote.return_value = {"price": 1.0}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.endpoint_status["fmp_etf_info"], "PLAN_RESTRICTED")
        self.assertTrue(any("plan erişimi" in warning for warning in result.warnings))

    def test_missing_holdings_no_concentration_score(self) -> None:
        self.fmp.etf_info.return_value = full_etf_info("SPUS")
        self.fmp.etf_holdings.return_value = []
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 56.0}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertIsNone(result.top10_concentration_pct)
        dimensions = {item.dimension for item in result.dimension_scores}
        self.assertNotIn(DIMENSION_CONCENTRATION, dimensions)

    def test_empty_holdings_no_fake_concentration(self) -> None:
        self.fmp.etf_info.return_value = full_etf_info("SPUS")
        self.fmp.etf_holdings.return_value = []
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 56.0}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertIsNone(result.top10_concentration_pct)
        self.assertEqual(result.top_holdings, [])

    def test_malformed_holdings_ignored(self) -> None:
        self.fmp.etf_info.return_value = full_etf_info("SPUS")
        self.fmp.etf_holdings.return_value = [
            {"asset": "AAPL", "weightPercentage": "bad"},
            {"asset": "MSFT", "weightPercentage": 0},
            {"name": "No weight"},
        ]
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 56.0}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.top_holdings, [])
        self.assertIsNone(result.top10_concentration_pct)

    def test_zero_expense_ratio_no_cost_score(self) -> None:
        self.fmp.etf_info.return_value = {**full_etf_info("SPUS"), "expenseRatio": 0}
        self.fmp.etf_holdings.return_value = sample_holdings(5)
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 56.0}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertIsNone(result.expense_ratio)
        dimensions = {item.dimension for item in result.dimension_scores}
        self.assertNotIn(DIMENSION_COST, dimensions)

    def test_invalid_expense_string_unsupported(self) -> None:
        self.fmp.etf_info.return_value = {**full_etf_info("SPUS"), "expenseRatio": "n/a"}
        self.fmp.etf_holdings.return_value = sample_holdings(5)
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 56.0}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertIsNone(result.expense_ratio)
        self.assertIn("expense_ratio", result.unsupported_fields)

    def test_high_expense_label(self) -> None:
        self.fmp.etf_info.return_value = {
            **full_etf_info("SPUS"),
            "expenseRatio": EXPENSE_HIGH_THRESHOLD_PCT + 0.1,
        }
        self.fmp.etf_holdings.return_value = sample_holdings(5)
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 56.0, "volume": 1_000_000}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertIn(LABEL_YUKSEK_MALIYET, result.labels)

    def test_concentration_risk_label(self) -> None:
        rows = [
            {"asset": "A", "weightPercentage": 30},
            {"asset": "B", "weightPercentage": 25},
        ]
        self.fmp.etf_info.return_value = full_etf_info("SPUS")
        self.fmp.etf_holdings.return_value = rows
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 56.0, "volume": 1_000_000}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertGreater(result.top10_concentration_pct or 0, TOP10_CONCENTRATION_RISK_THRESHOLD_PCT)
        self.assertIn(LABEL_YOGUNLASMA_RISKI, result.labels)

    def test_partial_metadata_veri_yetersiz(self) -> None:
        self.fmp.etf_info.return_value = {}
        self.fmp.etf_holdings.return_value = []
        self.fmp.profile.return_value = {"companyName": "SPUS"}
        self.fmp.quote.return_value = {}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertIn(LABEL_VERI_YETERSIZ, result.labels)
        self.assertNotIn(LABEL_INCELEME_UYGUN, result.labels)

    def test_malformed_provider_payloads_fail_soft(self) -> None:
        self.fmp.etf_info.return_value = None
        self.fmp.etf_holdings.return_value = {"bad": True}
        self.fmp.profile.return_value = "bad"
        self.fmp.quote.return_value = 123

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.analysis_kind, ANALYSIS_KIND_FUND)
        self.assertEqual(result.endpoint_status["fmp_etf_info"], "EMPTY")
        self.assertEqual(result.endpoint_status["fmp_etf_holdings"], "MALFORMED")
        self.assertEqual(result.endpoint_status["fmp_profile"], "MALFORMED")


class FundDimensionThresholdTests(unittest.TestCase):
    def test_cost_dimension_thresholds(self) -> None:
        low = score_cost_dimension(0.08)
        high = score_cost_dimension(EXPENSE_HIGH_THRESHOLD_PCT + 0.2)
        missing = score_cost_dimension(None)

        self.assertIsNotNone(low)
        self.assertIsNotNone(high)
        self.assertIsNone(missing)
        assert low is not None and high is not None
        self.assertGreater(low.score, high.score)

    def test_liquidity_dimension_missing_inputs(self) -> None:
        self.assertIsNone(score_liquidity_dimension(None, None, None))

    def test_concentration_dimension_missing(self) -> None:
        self.assertIsNone(score_concentration_dimension(None))


class FundAnalysisRoutingTests(unittest.TestCase):
    @unittest.mock.patch("services.manual_analysis_service.run_scan")
    @unittest.mock.patch("services.manual_analysis_service.analyze_fund")
    @unittest.mock.patch("services.manual_analysis_service.resolve_symbol")
    def test_etf_never_calls_run_scan(
        self,
        mock_resolve,
        mock_analyze_fund,
        mock_run_scan,
    ) -> None:
        from services.fund_analysis_contract import FundAnalysisResult
        from services.manual_analysis_service import analyze_security

        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = FundAnalysisResult(symbol="SPUS")

        result = analyze_security(
            "SPUS",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            scan_repo=MagicMock(),
            fmp_client=MagicMock(),
            sec_client=MagicMock(),
        )

        mock_run_scan.assert_not_called()
        mock_analyze_fund.assert_called_once()
        self.assertEqual(result.analysis_kind, "fund")

    @unittest.mock.patch("services.manual_analysis_service.analyze_fund")
    @unittest.mock.patch("services.manual_analysis_service.run_scan")
    @unittest.mock.patch("services.manual_analysis_service.resolve_symbol")
    def test_equity_never_calls_fund_analyzer(
        self,
        mock_resolve,
        mock_run_scan,
        mock_analyze_fund,
    ) -> None:
        from services.manual_analysis_service import analyze_security
        from services.symbol_resolver_service import ResolvedSecurity

        mock_resolve.return_value = ResolvedSecurity(
            symbol="NVDA",
            company_name="NVIDIA",
            exchange="NASDAQ",
            security_type="COMMON_STOCK",
            issuer_category="OPERATING_COMPANY",
            is_etf=False,
            cik=1,
            resolution_source="fmp",
            resolution_confidence="HIGH",
            is_equity_eligible=True,
        )
        mock_run_scan.return_value = MagicMock(
            candidates=[{"symbol": "NVDA", "nabi_score": 80.0}],
            fmp_rate_limited=False,
        )

        result = analyze_security(
            "NVDA",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            scan_repo=MagicMock(),
            fmp_client=MagicMock(),
            sec_client=MagicMock(),
        )

        mock_analyze_fund.assert_not_called()
        mock_run_scan.assert_called_once()
        self.assertEqual(result.analysis_kind, "equity")

    @unittest.mock.patch("services.manual_analysis_service.analyze_fund")
    @unittest.mock.patch("services.manual_analysis_service.run_scan")
    @unittest.mock.patch("services.manual_analysis_service.resolve_symbol")
    def test_unresolved_calls_neither(
        self,
        mock_resolve,
        mock_run_scan,
        mock_analyze_fund,
    ) -> None:
        from services.manual_analysis_service import analyze_security
        from services.symbol_resolver_service import SECURITY_TYPE_UNRESOLVED, ResolvedSecurity

        mock_resolve.return_value = ResolvedSecurity(
            symbol="QQQ",
            company_name="QQQ TRUST",
            exchange="NASDAQ",
            security_type=SECURITY_TYPE_UNRESOLVED,
            issuer_category="UNKNOWN",
            is_etf=False,
            cik=1067839,
            resolution_source="sec",
            resolution_confidence="LOW",
            is_equity_eligible=False,
        )

        result = analyze_security(
            "QQQ",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            scan_repo=MagicMock(),
            fmp_client=MagicMock(),
            sec_client=MagicMock(),
        )

        mock_run_scan.assert_not_called()
        mock_analyze_fund.assert_not_called()
        self.assertEqual(result.analysis_kind, "unresolved")

    @unittest.mock.patch("services.manual_analysis_service.analyze_fund")
    @unittest.mock.patch("services.manual_analysis_service.resolve_symbol")
    def test_legacy_candidate_nabi_not_in_fund_result(
        self,
        mock_resolve,
        mock_analyze_fund,
    ) -> None:
        from services.fund_analysis_contract import FundAnalysisResult
        from services.manual_analysis_service import analyze_security

        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = FundAnalysisResult(
            symbol="SPUS",
            fund_name="SPUS ETF",
            data_completeness_pct=70.0,
        )
        legacy_candidate = {
            "id": "legacy",
            "symbol": "SPUS",
            "nabi_score": 33.3,
            "asset_type": "ETF",
        }

        result = analyze_security(
            "SPUS",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=legacy_candidate)),
            scan_repo=MagicMock(),
            fmp_client=MagicMock(),
            sec_client=MagicMock(),
        )

        self.assertEqual(result.analysis_kind, "fund")
        self.assertIsNone(result.candidate)
        self.assertNotEqual(getattr(result.fund_result, "nabi_score", None), 33.3)
        payload = result.fund_result.to_dict()
        self.assertNotIn("nabi_score", payload)
        self.assertNotIn("decision_label", payload)


class FundAnalysisPerformanceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fmp = MagicMock()
        self.fmp.etf_info.return_value = full_etf_info("SPUS")
        self.fmp.etf_holdings.return_value = sample_holdings()
        self.fmp.profile.return_value = {}
        self.fmp.quote.return_value = {"price": 110.0, "volume": 500_000}

    def test_available_history_attaches_metrics(self) -> None:
        self.fmp.historical_price_eod_light.return_value = sample_price_history(70)

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.price_history_status, "OK")
        self.assertIsNotNone(result.performance_metrics)
        self.assertIsNotNone(result.risk_metrics)
        self.assertTrue(result.has_performance_or_risk_metrics())
        self.assertIsNotNone(result.performance_metrics.return_1m_pct)

    def test_rate_limit_history_leaves_metrics_none(self) -> None:
        self.fmp.historical_price_eod_light.side_effect = FMPError(
            "limited",
            error_class="rate_limit",
        )

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.price_history_status, "RATE_LIMIT")
        self.assertIsNone(result.performance_metrics)
        self.assertIsNone(result.risk_metrics)
        self.assertTrue(result.expense_ratio is not None)
        self.assertTrue(any("Fiyat geçmişi" in warning for warning in result.performance_warnings))

    def test_plan_restricted_history_leaves_metrics_none(self) -> None:
        self.fmp.historical_price_eod_light.side_effect = FMPError(
            "denied",
            error_class="plan_restricted",
        )

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.price_history_status, "PLAN_RESTRICTED")
        self.assertIsNone(result.performance_metrics)

    def test_malformed_history_safe(self) -> None:
        self.fmp.historical_price_eod_light.return_value = {"bad": True}

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.price_history_status, "MALFORMED")
        self.assertIsNone(result.performance_metrics)

    def test_5b1_expense_holdings_unaffected(self) -> None:
        self.fmp.historical_price_eod_light.return_value = sample_price_history(70)

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(result.expense_ratio, 0.49)
        self.assertTrue(result.top_holdings)

    def test_fmp_call_budget_bounded(self) -> None:
        self.fmp.historical_price_eod_light.return_value = sample_price_history(70)

        analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertEqual(self.fmp.etf_info.call_count, 1)
        self.assertEqual(self.fmp.etf_holdings.call_count, 1)
        self.assertEqual(self.fmp.profile.call_count, 1)
        self.assertEqual(self.fmp.quote.call_count, 1)
        self.assertEqual(self.fmp.historical_price_eod_light.call_count, 1)

    def test_spus_synthetic_full_path(self) -> None:
        self.fmp.historical_price_eod_light.return_value = sample_price_history(80, end_price=120.0)

        result = analyze_fund(resolved_etf("SPUS"), fmp_client=self.fmp)

        self.assertIsNotNone(result.performance_metrics)
        self.assertIsNotNone(result.performance_metrics.return_1y_pct)

    def test_spsk_fixed_income_label_guard(self) -> None:
        self.fmp.etf_info.return_value = {
            **full_etf_info("SPSK"),
            "assetClass": "Fixed Income Sukuk",
            "name": "SP Funds Dow Jones Global Sukuk ETF",
        }
        self.fmp.historical_price_eod_light.return_value = sample_price_history(80)

        result = analyze_fund(resolved_etf("SPSK"), fmp_client=self.fmp)

        self.assertIsNotNone(result.risk_metrics)
        self.assertIsNotNone(result.risk_metrics.annualized_volatility_pct)
        self.assertIsNone(result.risk_metrics.volatility_label)

    def test_qqq_fund_path_with_history(self) -> None:
        self.fmp.etf_info.return_value = full_etf_info("QQQ")
        self.fmp.historical_price_eod_light.return_value = sample_price_history(70)

        result = analyze_fund(resolved_etf("QQQ"), fmp_client=self.fmp)

        self.assertEqual(result.symbol, "QQQ")
        self.assertIsNone(result.participation_source)


if __name__ == "__main__":
    unittest.main()
