import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from services.alpha_vantage_cache import (
    AlphaCacheKey,
    AlphaVantageFundCache,
    NEGATIVE_CACHE_TTL_SECONDS,
    SUCCESS_ETF_PROFILE_TTL_SECONDS,
    SUCCESS_TIME_SERIES_TTL_SECONDS,
    reset_fund_cache,
)
from services.alpha_vantage_client import (
    STATUS_OK,
    STATUS_RATE_LIMIT,
    AlphaVantageError,
)
from services.fund_analysis_service import analyze_fund
from services.manual_analysis_service import analyze_security
from services.symbol_resolver_service import RESOLUTION_HIGH, ResolvedSecurity
from tests.test_fund_analysis import (
    make_alpha_client,
    resolved_etf,
    sample_alpha_etf_profile,
    sample_alpha_time_series,
)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def stale_alpha_time_series(count: int = 100) -> dict:
    series = {}
    end = date.today() - timedelta(days=10)
    current = end - timedelta(days=count - 1)
    for index in range(count):
        series[current.isoformat()] = {
            "4. close": f"{100 + index * 0.1:.4f}",
            "5. volume": "100000",
        }
        current += timedelta(days=1)
    return {
        "Meta Data": {"2. Symbol": "SPUS", "4. Output Size": "Compact"},
        "Time Series (Daily)": series,
    }


class AlphaCacheContractTests(unittest.TestCase):
    def test_cache_key_includes_symbol_endpoint_and_params(self) -> None:
        key_a = AlphaCacheKey.build("time_series_daily", "spus", outputsize="compact")
        key_b = AlphaCacheKey.build("time_series_daily", "SPUS", outputsize="compact")
        key_c = AlphaCacheKey.build("time_series_daily", "SPUS", outputsize="full")
        key_d = AlphaCacheKey.build("time_series_daily", "HLAL", outputsize="compact")

        self.assertEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_c)
        self.assertNotEqual(key_a, key_d)

    def test_success_ttl_values(self) -> None:
        self.assertEqual(SUCCESS_ETF_PROFILE_TTL_SECONDS, 3600)
        self.assertEqual(SUCCESS_TIME_SERIES_TTL_SECONDS, 900)
        self.assertEqual(NEGATIVE_CACHE_TTL_SECONDS, 60)


class AlphaCacheHitMissTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_fund_cache()

    def test_first_spus_analyze_max_two_alpha_calls(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(clock=clock.now)
        alpha = make_alpha_client()

        analyze_fund(
            resolved_etf("SPUS"),
            alpha_vantage_client=alpha,
            alpha_cache=cache,
        )

        self.assertEqual(alpha.etf_profile.call_count, 1)
        self.assertEqual(alpha.time_series_daily.call_count, 1)

    def test_second_spus_analyze_within_ttl_zero_alpha_calls(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(clock=clock.now)
        alpha = make_alpha_client()
        resolved = resolved_etf("SPUS")

        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)

        self.assertEqual(alpha.etf_profile.call_count, 1)
        self.assertEqual(alpha.time_series_daily.call_count, 1)

    def test_profile_hit_history_miss_only_one_history_call(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(clock=clock.now)
        alpha = make_alpha_client()
        resolved = resolved_etf("SPUS")

        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        cache._entries = {
            key: entry
            for key, entry in cache._entries.items()
            if key.endpoint == "etf_profile"
        }
        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)

        self.assertEqual(alpha.etf_profile.call_count, 1)
        self.assertEqual(alpha.time_series_daily.call_count, 2)

    def test_history_hit_profile_miss_only_one_profile_call(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(clock=clock.now)
        alpha = make_alpha_client()
        resolved = resolved_etf("SPUS")

        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        cache._entries = {
            key: entry
            for key, entry in cache._entries.items()
            if key.endpoint == "time_series_daily"
        }
        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)

        self.assertEqual(alpha.etf_profile.call_count, 2)
        self.assertEqual(alpha.time_series_daily.call_count, 1)

    def test_profile_ttl_expiry_refetches_profile_only(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(
            clock=clock.now,
            profile_ttl_seconds=100,
            history_ttl_seconds=10_000,
        )
        alpha = make_alpha_client()
        resolved = resolved_etf("SPUS")

        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        clock.advance(101)
        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)

        self.assertEqual(alpha.etf_profile.call_count, 2)
        self.assertEqual(alpha.time_series_daily.call_count, 1)

    def test_history_ttl_expiry_refetches_history_only(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(
            clock=clock.now,
            profile_ttl_seconds=10_000,
            history_ttl_seconds=100,
        )
        alpha = make_alpha_client()
        resolved = resolved_etf("SPUS")

        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        clock.advance(101)
        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)

        self.assertEqual(alpha.etf_profile.call_count, 1)
        self.assertEqual(alpha.time_series_daily.call_count, 2)

    def test_different_symbols_do_not_collide(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(clock=clock.now)
        alpha = make_alpha_client(
            profile=sample_alpha_etf_profile("SPUS"),
            history=sample_alpha_time_series(100, anchor_end_to_today=True),
        )

        analyze_fund(resolved_etf("SPUS"), alpha_vantage_client=alpha, alpha_cache=cache)
        analyze_fund(resolved_etf("HLAL"), alpha_vantage_client=alpha, alpha_cache=cache)

        self.assertEqual(alpha.etf_profile.call_count, 2)
        self.assertEqual(alpha.time_series_daily.call_count, 2)

    def test_rate_limit_not_cached_with_success_ttl(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(clock=clock.now)
        alpha = make_alpha_client(
            history_error=AlphaVantageError(
                "rate limit",
                error_class="rate_limit",
                status=STATUS_RATE_LIMIT,
            ),
        )
        resolved = resolved_etf("SPUS")

        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        clock.advance(NEGATIVE_CACHE_TTL_SECONDS - 1)
        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        self.assertEqual(alpha.time_series_daily.call_count, 1)

        clock.advance(2)
        analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        self.assertEqual(alpha.time_series_daily.call_count, 2)


class AlphaCacheSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_fund_cache()

    def test_cached_compact_history_still_omits_1y(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(clock=clock.now)
        alpha = make_alpha_client(
            history=sample_alpha_time_series(100, anchor_end_to_today=True),
        )
        resolved = resolved_etf("SPUS")

        first = analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        second = analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)

        self.assertEqual(alpha.etf_profile.call_count, 1)
        self.assertEqual(alpha.time_series_daily.call_count, 1)
        for result in (first, second):
            performance = result.performance_metrics
            self.assertIsNotNone(performance)
            assert performance is not None
            self.assertIsNone(performance.return_1y_pct)
            self.assertFalse(performance.history_is_full_year)

    def test_cached_stale_history_still_is_stale(self) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(clock=clock.now)
        alpha = make_alpha_client(history=stale_alpha_time_series())
        resolved = resolved_etf("SPUS")

        first = analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)
        second = analyze_fund(resolved, alpha_vantage_client=alpha, alpha_cache=cache)

        self.assertEqual(alpha.time_series_daily.call_count, 1)
        for result in (first, second):
            performance = result.performance_metrics
            self.assertIsNotNone(performance)
            assert performance is not None
            self.assertTrue(performance.is_stale)


class AlphaCacheIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_fund_cache()

    @patch("services.manual_analysis_service.resolve_symbol")
    def test_nvda_equity_does_not_touch_fund_cache(self, mock_resolve) -> None:
        clock = FakeClock()
        cache = AlphaVantageFundCache(clock=clock.now)
        mock_resolve.return_value = ResolvedSecurity(
            symbol="NVDA",
            company_name="NVIDIA",
            exchange="NASDAQ",
            security_type="EQUITY",
            issuer_category="OPERATING",
            is_etf=False,
            cik=1045810,
            resolution_source="fmp_profile",
            resolution_confidence=RESOLUTION_HIGH,
            is_equity_eligible=True,
        )
        candidate_repo = MagicMock(get_by_symbol=MagicMock(return_value=None))
        scan_repo = MagicMock()

        with patch("services.manual_analysis_service.run_scan") as mock_run_scan:
            mock_run_scan.return_value = MagicMock(
                candidates=[{"symbol": "NVDA", "nabi_score": 80.0}],
                fmp_rate_limited=False,
            )
            analyze_security(
                "NVDA",
                candidate_repo=candidate_repo,
                scan_repo=scan_repo,
                fmp_client=MagicMock(),
                alpha_vantage_client=MagicMock(),
                sec_client=MagicMock(),
            )

        self.assertEqual(len(cache._entries), 0)

    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_fund_persistence_isolation(self, mock_resolve, mock_analyze_fund) -> None:
        from services.fund_analysis_contract import FundAnalysisResult

        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = FundAnalysisResult(symbol="SPUS")
        candidate_repo = MagicMock(get_by_symbol=MagicMock(return_value=None))

        with patch("services.manual_analysis_service.run_scan") as mock_run_scan:
            analyze_security(
                "SPUS",
                candidate_repo=candidate_repo,
                scan_repo=MagicMock(),
                fmp_client=MagicMock(),
                alpha_vantage_client=MagicMock(),
                sec_client=MagicMock(),
            )
            mock_run_scan.assert_not_called()

        candidate_repo.upsert_by_symbol.assert_not_called()


class AlphaCacheImportSmokeTests(unittest.TestCase):
    def test_fresh_process_imports(self) -> None:
        import importlib
        import sys

        if "services.alpha_vantage_cache" in sys.modules:
            del sys.modules["services.alpha_vantage_cache"]
        importlib.import_module("services.alpha_vantage_cache")

        import services.alpha_vantage_client
        import services.alpha_vantage_adapter
        import services.fund_analysis_service as fund_analysis_service
        import services.manual_analysis_service as manual_analysis_service

        self.assertTrue(hasattr(services.alpha_vantage_client, "AlphaVantageClient"))
        self.assertTrue(hasattr(services.alpha_vantage_adapter, "normalize_alpha_expense_ratio"))
        self.assertTrue(hasattr(fund_analysis_service, "analyze_fund"))
        self.assertTrue(hasattr(manual_analysis_service, "analyze_security"))

        import py_compile

        py_compile.compile("pages/1_Dashboard.py", doraise=True)


if __name__ == "__main__":
    unittest.main()
