import unittest
from unittest.mock import MagicMock

from services.alpha_vantage_client import (
    STATUS_PREMIUM_REQUIRED,
    STATUS_RATE_LIMIT,
    AlphaVantageError,
)
from services.fund_analysis_contract import (
    ANALYSIS_KIND_FUND,
    DATA_PROVIDER_ALPHA_VANTAGE,
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


def sample_alpha_etf_profile(symbol: str = "SPUS", **overrides):
    payload = {
        "net_assets": "2860058355",
        "net_expense_ratio": "0.0049",
        "portfolio_turnover": "0.25",
        "dividend_yield": "0.012",
        "inception_date": "2019-12-16",
        "leveraged": "NO",
        "sectors": [],
        "holdings": sample_alpha_holdings(12),
    }
    payload.update(overrides)
    return payload


def sample_alpha_holdings(count: int = 12):
    rows = []
    for index in range(count):
        weight = "0.1000" if index < 5 else "0.0200"
        rows.append({
            "symbol": f"T{index}",
            "description": f"Ticker {index}",
            "weight": weight,
        })
    return rows


def sample_alpha_time_series(
    count: int = 280,
    *,
    start_price: float = 100.0,
    end_price: float = 110.0,
    anchor_end_to_today: bool = False,
):
    from datetime import date, timedelta

    series = {}
    end = date.today() if anchor_end_to_today else date(2024, 1, 2) + timedelta(days=count - 1)
    current = end - timedelta(days=count - 1)
    for index in range(count):
        if count == 1:
            price = end_price
        else:
            price = start_price + (end_price - start_price) * index / (count - 1)
        series[current.isoformat()] = {
            "4. close": f"{price:.4f}",
            "5. volume": "100000",
        }
        current += timedelta(days=1)
    output_size = "Compact" if count <= 100 else "Full"
    return {
        "Meta Data": {
            "2. Symbol": "SPUS",
            "4. Output Size": output_size,
        },
        "Time Series (Daily)": series,
    }


def make_alpha_client(
    *,
    profile=None,
    history=None,
    profile_error=None,
    history_error=None,
):
    client = MagicMock()
    if profile_error is not None:
        client.etf_profile.side_effect = profile_error
    else:
        client.etf_profile.return_value = profile if profile is not None else sample_alpha_etf_profile()
    if history_error is not None:
        client.time_series_daily.side_effect = history_error
    else:
        client.time_series_daily.return_value = history if history is not None else sample_alpha_time_series()
    return client


class FundAnalysisServiceTests(unittest.TestCase):
    def test_spus_full_fund_result(self) -> None:
        alpha = make_alpha_client(profile=sample_alpha_etf_profile("SPUS"))

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(result.analysis_kind, ANALYSIS_KIND_FUND)
        self.assertEqual(result.symbol, "SPUS")
        self.assertEqual(result.data_provider, DATA_PROVIDER_ALPHA_VANTAGE)
        self.assertEqual(result.participation_source, PARTICIPATION_SOURCE_CONFIGURED)
        self.assertEqual(result.participation_status, "Uygun")
        self.assertEqual(result.participation_score, 100)
        self.assertEqual(result.expense_ratio, 0.49)
        self.assertIsNotNone(result.top10_concentration_pct)
        self.assertGreaterEqual(result.data_completeness_pct, MIN_COMPLETENESS_FOR_DIMENSIONS)
        self.assertTrue(result.top_holdings)
        self.assertIn(LABEL_CONFIGURED_PARTICIPATION, result.labels)
        self.assertNotIn("nabi_score", result.to_dict())
        self.assertIsNone(result.benchmark)
        self.assertIsNone(result.sector_weights)

    def test_hlal_configured_participation(self) -> None:
        alpha = make_alpha_client(profile=sample_alpha_etf_profile("HLAL"))

        result = analyze_fund(resolved_etf("HLAL"), alpha_vantage_client=alpha)

        self.assertEqual(result.participation_source, PARTICIPATION_SOURCE_CONFIGURED)
        self.assertEqual(result.participation_status, "Uygun")

    def test_spsk_sukuk_identity(self) -> None:
        alpha = make_alpha_client(
            profile=sample_alpha_etf_profile("SPSK", holdings=sample_alpha_holdings(6)),
        )

        result = analyze_fund(
            resolved_etf("SPSK", company_name="SP Funds Dow Jones Global Sukuk ETF"),
            alpha_vantage_client=alpha,
        )

        self.assertIn("Sukuk", result.fund_name or "")

    def test_qqq_non_configured_participation(self) -> None:
        alpha = make_alpha_client(profile=sample_alpha_etf_profile("QQQ"))

        result = analyze_fund(resolved_etf("QQQ"), alpha_vantage_client=alpha)

        self.assertIsNone(result.participation_source)
        self.assertEqual(result.participation_status, "Kontrol Et")

    def test_rate_limited_profile_partial_result(self) -> None:
        alpha = make_alpha_client(
            profile_error=AlphaVantageError("limited", error_class="rate_limit", status=STATUS_RATE_LIMIT),
            history_error=AlphaVantageError("limited", error_class="rate_limit", status=STATUS_RATE_LIMIT),
        )

        result = analyze_fund(
            resolved_etf("SPUS", company_name="SP Funds S&P 500 Sharia Industry Exclusions ETF"),
            alpha_vantage_client=alpha,
        )

        self.assertEqual(result.endpoint_status["alpha_etf_profile"], STATUS_RATE_LIMIT)
        self.assertIsNone(result.expense_ratio)
        self.assertIsNone(result.top10_concentration_pct)
        dimensions = {item.dimension for item in result.dimension_scores}
        self.assertNotIn(DIMENSION_COST, dimensions)
        self.assertNotIn(DIMENSION_CONCENTRATION, dimensions)
        self.assertTrue(result.warnings)

    def test_premium_required_profile_partial(self) -> None:
        alpha = make_alpha_client(
            profile_error=AlphaVantageError(
                "premium",
                error_class="premium_required",
                status=STATUS_PREMIUM_REQUIRED,
            ),
            history=sample_alpha_time_series(280),
        )

        result = analyze_fund(resolved_etf("QQQ"), alpha_vantage_client=alpha)

        self.assertEqual(result.endpoint_status["alpha_etf_profile"], STATUS_PREMIUM_REQUIRED)
        self.assertTrue(any("mevcut plan" in warning for warning in result.warnings))

    def test_missing_holdings_no_concentration_score(self) -> None:
        alpha = make_alpha_client(profile=sample_alpha_etf_profile("SPUS", holdings=[]))

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertIsNone(result.top10_concentration_pct)
        dimensions = {item.dimension for item in result.dimension_scores}
        self.assertNotIn(DIMENSION_CONCENTRATION, dimensions)

    def test_empty_holdings_no_fake_concentration(self) -> None:
        alpha = make_alpha_client(profile=sample_alpha_etf_profile("SPUS", holdings=[]))

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertIsNone(result.top10_concentration_pct)
        self.assertEqual(result.top_holdings, [])

    def test_malformed_holdings_ignored(self) -> None:
        alpha = make_alpha_client(
            profile=sample_alpha_etf_profile(
                "SPUS",
                holdings=[
                    {"symbol": "AAPL", "weight": "bad"},
                    {"symbol": "MSFT", "weight": "0"},
                    {"description": "No weight"},
                ],
            )
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(result.top_holdings, [])
        self.assertIsNone(result.top10_concentration_pct)

    def test_zero_expense_ratio_no_cost_score(self) -> None:
        alpha = make_alpha_client(
            profile=sample_alpha_etf_profile("SPUS", net_expense_ratio="0"),
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertIsNone(result.expense_ratio)
        dimensions = {item.dimension for item in result.dimension_scores}
        self.assertNotIn(DIMENSION_COST, dimensions)

    def test_invalid_expense_string_unsupported(self) -> None:
        alpha = make_alpha_client(
            profile=sample_alpha_etf_profile("SPUS", net_expense_ratio="n/a"),
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertIsNone(result.expense_ratio)
        self.assertIn("expense_ratio", result.unsupported_fields)

    def test_high_expense_label(self) -> None:
        alpha = make_alpha_client(
            profile=sample_alpha_etf_profile(
                "SPUS",
                net_expense_ratio=f"{(EXPENSE_HIGH_THRESHOLD_PCT + 0.1) / 100:.4f}",
            ),
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertIn(LABEL_YUKSEK_MALIYET, result.labels)

    def test_concentration_risk_label(self) -> None:
        alpha = make_alpha_client(
            profile=sample_alpha_etf_profile(
                "SPUS",
                holdings=[
                    {"symbol": "A", "description": "A", "weight": "0.30"},
                    {"symbol": "B", "description": "B", "weight": "0.25"},
                ],
            )
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertGreater(result.top10_concentration_pct or 0, TOP10_CONCENTRATION_RISK_THRESHOLD_PCT)
        self.assertIn(LABEL_YOGUNLASMA_RISKI, result.labels)

    def test_partial_metadata_veri_yetersiz(self) -> None:
        alpha = make_alpha_client(
            profile={},
            history={"Meta Data": {}, "Time Series (Daily)": {}},
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertIn(LABEL_VERI_YETERSIZ, result.labels)
        self.assertNotIn(LABEL_INCELEME_UYGUN, result.labels)

    def test_malformed_provider_payloads_fail_soft(self) -> None:
        alpha = make_alpha_client(
            profile_error=AlphaVantageError(
                "bad",
                error_class="malformed",
                status="MALFORMED",
            ),
            history_error=AlphaVantageError(
                "bad",
                error_class="malformed",
                status="MALFORMED",
            ),
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(result.analysis_kind, ANALYSIS_KIND_FUND)
        self.assertEqual(result.endpoint_status["alpha_etf_profile"], "MALFORMED")


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
            alpha_vantage_client=MagicMock(),
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
            alpha_vantage_client=MagicMock(),
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
            alpha_vantage_client=MagicMock(),
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
            alpha_vantage_client=MagicMock(),
            sec_client=MagicMock(),
        )

        self.assertEqual(result.analysis_kind, "fund")
        self.assertIsNone(result.candidate)
        payload = result.fund_result.to_dict()
        self.assertNotIn("nabi_score", payload)
        self.assertNotIn("decision_label", payload)


class FundAnalysisPerformanceIntegrationTests(unittest.TestCase):
    def test_available_history_attaches_metrics(self) -> None:
        alpha = make_alpha_client()

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(result.price_history_status, "OK")
        self.assertIsNotNone(result.performance_metrics)
        self.assertIsNotNone(result.risk_metrics)
        self.assertTrue(result.has_performance_or_risk_metrics())
        self.assertIsNotNone(result.performance_metrics.return_1m_pct)

    def test_rate_limit_history_leaves_metrics_none(self) -> None:
        alpha = make_alpha_client(
            history_error=AlphaVantageError("limited", error_class="rate_limit", status=STATUS_RATE_LIMIT),
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(result.price_history_status, STATUS_RATE_LIMIT)
        self.assertIsNone(result.performance_metrics)
        self.assertIsNone(result.risk_metrics)
        self.assertTrue(result.expense_ratio is not None)
        self.assertTrue(any("Fiyat geçmişi" in warning for warning in result.performance_warnings))

    def test_premium_history_leaves_metrics_none(self) -> None:
        alpha = make_alpha_client(
            history_error=AlphaVantageError(
                "premium",
                error_class="premium_required",
                status=STATUS_PREMIUM_REQUIRED,
            ),
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(result.price_history_status, STATUS_PREMIUM_REQUIRED)
        self.assertIsNone(result.performance_metrics)

    def test_malformed_history_safe(self) -> None:
        alpha = make_alpha_client(history={"Meta Data": {}, "Time Series (Daily)": {}})

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(result.price_history_status, "EMPTY")
        self.assertIsNone(result.performance_metrics)

    def test_profile_fields_unaffected_by_history(self) -> None:
        alpha = make_alpha_client()

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(result.expense_ratio, 0.49)
        self.assertTrue(result.top_holdings)

    def test_alpha_call_budget_bounded(self) -> None:
        alpha = make_alpha_client()

        analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(alpha.etf_profile.call_count, 1)
        self.assertEqual(alpha.time_series_daily.call_count, 1)
        alpha.time_series_daily.assert_called_once_with("SPUS", outputsize="compact")

    def test_compact_history_suppresses_degraded_1y(self) -> None:
        alpha = make_alpha_client(
            history=sample_alpha_time_series(100, anchor_end_to_today=True),
        )

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertEqual(result.price_history_status, "OK")
        performance = result.performance_metrics
        self.assertIsNotNone(performance)
        assert performance is not None
        self.assertIsNotNone(performance.return_1m_pct)
        self.assertIsNone(performance.return_1y_pct)
        self.assertFalse(performance.history_is_full_year)
        self.assertFalse(performance.return_1y_full_confidence)
        self.assertEqual(performance.observation_count, 100)
        self.assertIsNotNone(result.risk_metrics)
        self.assertIsNotNone(result.risk_metrics.annualized_volatility_pct)
        self.assertIsNotNone(result.risk_metrics.max_drawdown_pct)

    def test_full_year_history_keeps_1y(self) -> None:
        alpha = make_alpha_client(history=sample_alpha_time_series(220, anchor_end_to_today=True))

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        performance = result.performance_metrics
        self.assertIsNotNone(performance)
        assert performance is not None
        self.assertIsNotNone(performance.return_1y_pct)
        self.assertTrue(performance.history_is_full_year)
        self.assertTrue(performance.return_1y_full_confidence)

    def test_no_fmp_fund_calls(self) -> None:
        alpha = make_alpha_client()
        fmp = MagicMock()

        analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        fmp.etf_info.assert_not_called()
        fmp.etf_holdings.assert_not_called()
        fmp.historical_price_eod_light.assert_not_called()
        fmp.profile.assert_not_called()
        fmp.quote.assert_not_called()

    def test_spus_synthetic_full_path(self) -> None:
        alpha = make_alpha_client(history=sample_alpha_time_series(280, end_price=120.0))

        result = analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha)

        self.assertIsNotNone(result.performance_metrics)
        self.assertIsNotNone(result.performance_metrics.return_1y_pct)

    def test_spsk_fixed_income_label_guard(self) -> None:
        alpha = make_alpha_client(
            profile=sample_alpha_etf_profile(
                "SPSK",
                asset_class="Fixed Income Sukuk",
            ),
        )

        result = analyze_fund(
            resolved_etf("SPSK", company_name="SP Funds Dow Jones Global Sukuk ETF"),
            alpha_vantage_client=alpha,
        )

        self.assertIsNotNone(result.risk_metrics)
        self.assertIsNotNone(result.risk_metrics.annualized_volatility_pct)
        self.assertIsNone(result.risk_metrics.volatility_label)

    def test_qqq_fund_path_with_history(self) -> None:
        alpha = make_alpha_client(
            profile_error=AlphaVantageError(
                "premium",
                error_class="premium_required",
                status=STATUS_PREMIUM_REQUIRED,
            ),
            history=sample_alpha_time_series(280),
        )

        result = analyze_fund(resolved_etf("QQQ"), alpha_vantage_client=alpha)

        self.assertEqual(result.symbol, "QQQ")
        self.assertIsNone(result.participation_source)
        self.assertIsNotNone(result.performance_metrics)


if __name__ == "__main__":
    unittest.main()
