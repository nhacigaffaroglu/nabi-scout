import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from services.scan_run_health_service import (
    ScanRunHealth,
    classify_result_row,
    derive_scan_run_health,
    is_excluded_result_row,
    resolve_scheduled_health,
)
from services.scan_runner_service import ScanRunResult, run_scan
from services.ui_formatters import format_scheduled_run_detail, resolve_scheduled_run_status


def equity_row(symbol: str, *, warnings=None, endpoint_status=None):
    return {
        "symbol": symbol,
        "status": "YETERLİ VERİ",
        "decision": "ARAŞTIRMA ADAYI",
        "errors": warnings or [],
        "endpoint_status": endpoint_status or {"fmp_profile": "OK", "fmp_quote": "OK"},
    }


def excluded_row(symbol: str):
    return {
        "symbol": symbol,
        "status": "ELENDİ",
        "decision": "ELE",
        "errors": [],
        "endpoint_status": {},
    }


def production_fixture_results():
    equities = [
        "NVDA", "GOOGL", "AVGO", "MSFT", "AAPL",
        "META", "AMZN", "CRM", "TSM", "ASML",
    ]
    rows = [
        equity_row(
            symbol,
            warnings=[f"FMP profile: rate limit"],
            endpoint_status={
                "fmp_profile": "RATE_LIMIT",
                "fmp_quote": "RATE_LIMIT",
                "sec_companyfacts": "OK",
            },
        )
        for symbol in equities
    ]
    rows.extend([
        excluded_row("HLAL"),
        excluded_row("SPSK"),
        excluded_row("SPUS"),
    ])
    return rows


class ScanRunHealthServiceTests(unittest.TestCase):
    def test_clean_usable_symbol(self) -> None:
        run = {"total_symbols": 1, "status": "COMPLETED", "error_count": 0}
        health = derive_scan_run_health(run, [equity_row("AAPL")])
        self.assertEqual(health.usable_symbols, 1)
        self.assertEqual(health.clean_symbols, 1)
        self.assertEqual(health.warning_symbols, 0)
        self.assertEqual(health.hard_failures, 0)
        self.assertEqual(health.excluded_symbols, 0)
        self.assertFalse(health.has_warnings)

    def test_warning_bearing_usable_symbol(self) -> None:
        run = {"total_symbols": 1, "status": "COMPLETED", "error_count": 1}
        health = derive_scan_run_health(
            run,
            [equity_row("AAPL", warnings=["FMP quote: timeout"])],
        )
        self.assertEqual(health.usable_symbols, 1)
        self.assertEqual(health.warning_symbols, 1)
        self.assertEqual(health.clean_symbols, 0)
        self.assertTrue(health.has_warnings)
        self.assertEqual(health.legacy_error_count, 1)

    def test_hard_failure_from_missing_row(self) -> None:
        run = {"total_symbols": 2, "status": "FAILED", "error_count": 2}
        health = derive_scan_run_health(run, [equity_row("AAPL")])
        self.assertEqual(health.analyzed_symbols, 1)
        self.assertEqual(health.hard_failures, 1)

    def test_excluded_etf_row(self) -> None:
        self.assertTrue(is_excluded_result_row(excluded_row("HLAL")))
        health = derive_scan_run_health(
            {"total_symbols": 1, "error_count": 0},
            [excluded_row("HLAL")],
        )
        self.assertEqual(health.excluded_symbols, 1)
        self.assertEqual(health.usable_symbols, 0)

    def test_mixed_run(self) -> None:
        run = {"total_symbols": 4, "status": "COMPLETED", "error_count": 2}
        results = [
            equity_row("AAPL"),
            equity_row("MSFT", warnings=["FMP quote: timeout"]),
            excluded_row("HLAL"),
        ]
        health = derive_scan_run_health(run, results)
        self.assertEqual(health.analyzed_symbols, 3)
        self.assertEqual(health.hard_failures, 1)
        self.assertEqual(health.excluded_symbols, 1)
        self.assertEqual(health.usable_symbols, 2)
        self.assertEqual(health.warning_symbols, 1)
        self.assertEqual(health.clean_symbols, 1)

    def test_historical_production_shape_fixture(self) -> None:
        run = {
            "id": "run-prod",
            "total_symbols": 13,
            "scanned_symbols": 13,
            "status": "COMPLETED",
            "error_count": 10,
        }
        health = derive_scan_run_health(run, production_fixture_results())
        self.assertEqual(health.total_symbols, 13)
        self.assertEqual(health.analyzed_symbols, 13)
        self.assertEqual(health.usable_symbols, 10)
        self.assertEqual(health.warning_symbols, 10)
        self.assertEqual(health.hard_failures, 0)
        self.assertEqual(health.excluded_symbols, 3)
        self.assertEqual(health.clean_symbols, 0)
        self.assertTrue(health.fmp_rate_limited)
        self.assertEqual(health.legacy_error_count, 10)
        self.assertEqual(health.scheduled_health, "partial")
        self.assertEqual(resolve_scheduled_health(run, health), "partial")

    def test_all_hard_fail_run(self) -> None:
        run = {"total_symbols": 2, "status": "FAILED", "error_count": 2}
        health = derive_scan_run_health(run, [])
        self.assertEqual(health.hard_failures, 2)
        self.assertEqual(health.usable_symbols, 0)
        self.assertEqual(resolve_scheduled_health(run, health), "failed")

    def test_endpoint_warning_count(self) -> None:
        health = derive_scan_run_health(
            {"total_symbols": 1},
            [equity_row(
                "AAPL",
                endpoint_status={
                    "fmp_profile": "RATE_LIMIT",
                    "fmp_quote": "OK",
                    "fmp_ratios_ttm": "TIMEOUT",
                },
            )],
        )
        self.assertEqual(health.endpoint_warning_count, 2)

    def test_malformed_errors_value(self) -> None:
        row = equity_row("AAPL")
        row["errors"] = "FMP profile: timeout"
        self.assertEqual(classify_result_row(row), "warning")
        health = derive_scan_run_health({"total_symbols": 1}, [row])
        self.assertEqual(health.warning_symbols, 1)

    def test_resolve_without_health_falls_back_to_legacy_error_count(self) -> None:
        run = {"status": "COMPLETED", "error_count": 3}
        self.assertEqual(resolve_scheduled_health(run, None), "partial")
        run_clean = {"status": "COMPLETED", "error_count": 0}
        self.assertEqual(resolve_scheduled_health(run_clean, None), "success")

    def test_daily_brief_clean_success(self) -> None:
        run = {
            "status": "COMPLETED",
            "scanned_symbols": 2,
            "error_count": 0,
        }
        rows = [equity_row(symbol) for symbol in ("AAPL", "MSFT")]
        health = derive_scan_run_health({**run, "total_symbols": 2}, rows)
        status = resolve_scheduled_run_status(run, health=health)
        self.assertEqual(status, "success")
        self.assertIn("2 sembol tarandı", format_scheduled_run_detail(status, run, health=health))

    def test_daily_brief_warning_partial(self) -> None:
        run = {
            "status": "COMPLETED",
            "scanned_symbols": 13,
            "error_count": 10,
        }
        health = derive_scan_run_health(
            {**run, "total_symbols": 13},
            production_fixture_results(),
        )
        status = resolve_scheduled_run_status(run, health=health)
        detail = format_scheduled_run_detail(status, run, health=health)
        self.assertEqual(status, "partial")
        self.assertIn("13 sembol tarandı", detail)
        self.assertIn("10 kullanılabilir sonuç", detail)
        self.assertNotIn("10 hata", detail)

    def test_daily_brief_failed_run(self) -> None:
        run = {"status": "FAILED", "scanned_symbols": 13, "error_count": 13}
        health = derive_scan_run_health({**run, "total_symbols": 13}, [])
        status = resolve_scheduled_run_status(run, health=health)
        self.assertEqual(status, "failed")


class ScanRunnerHealthIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        from tests.test_scan_runner import InMemoryScanStore, ScanRepository

        self.store = InMemoryScanStore()
        self.scan_repo = ScanRepository(self.store)
        self.candidate_repo = MagicMock()
        self.fmp_client = MagicMock()
        self.sec_client = MagicMock()
        self.engine = MagicMock()

    def test_throttle_called_between_symbols_not_after_last(self) -> None:
        self.engine.analyze.side_effect = [
            {
                "symbol": "AAPL",
                "status": "TAM VERİ",
                "excluded": False,
                "candidate": {
                    "symbol": "AAPL",
                    "data_completeness": 80,
                    "conviction_score": 70,
                    "decision_label": "ARAŞTIRMA ADAYI",
                },
                "endpoint_status": {},
                "errors": [],
            },
            {
                "symbol": "MSFT",
                "status": "TAM VERİ",
                "excluded": False,
                "candidate": {
                    "symbol": "MSFT",
                    "data_completeness": 80,
                    "conviction_score": 70,
                    "decision_label": "ARAŞTIRMA ADAYI",
                },
                "endpoint_status": {},
                "errors": [],
            },
        ]
        run_scan(
            symbols=[
                {"symbol": "AAPL", "cik": "1", "company_name": "AAPL", "exchange": "NASDAQ"},
                {"symbol": "MSFT", "cik": "2", "company_name": "MSFT", "exchange": "NASDAQ"},
            ],
            universe_name="test",
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
            inter_symbol_pause_seconds=0.15,
        )
        self.assertEqual(self.fmp_client.pause.call_count, 1)
        self.fmp_client.pause.assert_called_once_with(0.15)

    def test_in_memory_health_counters(self) -> None:
        self.engine.analyze.side_effect = [
            {
                "symbol": "AAPL",
                "status": "TAM VERİ",
                "excluded": False,
                "candidate": {
                    "symbol": "AAPL",
                    "data_completeness": 80,
                    "conviction_score": 70,
                    "decision_label": "ARAŞTIRMA ADAYI",
                },
                "endpoint_status": {"fmp_profile": "RATE_LIMIT"},
                "errors": ["FMP profile: rate limit"],
            },
            RuntimeError("hard fail"),
            {
                "symbol": "HLAL",
                "status": "ELENDİ",
                "excluded": True,
                "candidate": {"symbol": "HLAL", "decision": "ELE"},
                "endpoint_status": {},
                "errors": [],
            },
        ]
        result = run_scan(
            symbols=[
                {"symbol": "AAPL", "cik": "1", "company_name": "AAPL", "exchange": "NASDAQ"},
                {"symbol": "MSFT", "cik": "2", "company_name": "MSFT", "exchange": "NASDAQ"},
                {"symbol": "HLAL", "company_name": "HLAL", "is_etf": True},
            ],
            universe_name="test",
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
            inter_symbol_pause_seconds=0,
        )
        self.assertEqual(result.warning_symbols, 1)
        self.assertEqual(result.hard_failures, 1)
        self.assertEqual(result.excluded, 1)
        self.assertEqual(result.usable_symbols, 1)
        self.assertEqual(result.errors, 2)
        self.assertTrue(result.fmp_rate_limited)


class CliSummaryTests(unittest.TestCase):
    def test_completed_summary_does_not_equate_warnings_with_failures(self) -> None:
        from scripts import run_daily_scan as cli

        result = ScanRunResult(
            run_id="run-1",
            source="scheduled",
            universe_name="SCHEDULED · Daily · 2026-08-11",
            total_symbols=13,
            scanned=13,
            updated=10,
            strong=0,
            errors=10,
            excluded=3,
            warning_symbols=10,
            hard_failures=0,
            usable_symbols=10,
            clean_symbols=0,
            endpoint_warning_count=20,
            fmp_rate_limited=True,
            symbols_without_previous=0,
            status="COMPLETED",
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cli._print_summary(result)
        output = buffer.getvalue()
        self.assertIn("Action: COMPLETED", output)
        self.assertIn("Warnings: 10", output)
        self.assertIn("Hard failures: 0", output)
        self.assertNotIn("Errors:", output)
        self.assertIn("FMP rate limited: yes", output)

    def test_skipped_summary(self) -> None:
        from scripts import run_daily_scan as cli

        result = ScanRunResult(
            run_id="",
            source="scheduled",
            universe_name="SCHEDULED · Daily · 2026-08-11",
            total_symbols=0,
            scanned=0,
            updated=0,
            strong=0,
            errors=0,
            excluded=0,
            symbols_without_previous=0,
            skipped=True,
            skip_reason="Daily scan already completed for 2026-08-11.",
            status="SKIPPED",
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cli._print_summary(result)
        output = buffer.getvalue()
        self.assertIn("Action: SKIPPED", output)
        self.assertIn("already completed", output)
        self.assertNotIn("Warnings:", output)


if __name__ == "__main__":
    unittest.main()
