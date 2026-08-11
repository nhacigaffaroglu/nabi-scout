import copy
import importlib
import py_compile
import unittest
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from repositories.scan_repository import ScanRepository
from services.fmp_client import FMPError
from services.scan_runner_service import ScanRunResult, run_scan
from services.scan_universe_service import (
    build_daily_universe_rows,
    build_fixed_universe_rows,
    scheduled_universe_name,
)
from services.scheduled_scan_service import evaluate_scheduled_run, stale_running_cutoff
from services.supabase_client_factory import SupabaseConfigError, create_supabase_client


def symbol_row(symbol: str, **overrides) -> Dict[str, Any]:
    base = {
        "symbol": symbol,
        "cik": "123",
        "company_name": symbol,
        "exchange": "NASDAQ",
        "is_etf": False,
    }
    base.update(overrides)
    return base


def analyze_result(symbol: str, *, errors=None, excluded=False, **candidate_overrides):
    candidate = {
        "symbol": symbol,
        "company_name": symbol,
        "market": "ABD",
        "data_completeness": 80.0,
        "conviction_score": 70.0,
        "decision_label": "ARAŞTIRMA ADAYI",
        "nabi_score": 75.0,
    }
    candidate.update(candidate_overrides)
    return {
        "symbol": symbol,
        "status": "TAM VERİ",
        "excluded": excluded,
        "candidate": candidate,
        "endpoint_status": {},
        "errors": errors or [],
    }


class InMemoryScanStore:
    def __init__(self) -> None:
        self.runs: Dict[str, Dict[str, Any]] = {}
        self.results: List[Dict[str, Any]] = []
        self._counter = 0

    def table(self, name: str):
        if name == "scan_runs":
            return ScanRunsTable(self)
        if name == "scan_results":
            return ScanResultsTable(self)
        raise KeyError(name)


class ScanRunsTable:
    def __init__(self, store: InMemoryScanStore) -> None:
        self.store = store
        self._filters: List[tuple] = []
        self._operation = "select"
        self._payload: Optional[Dict[str, Any]] = None
        self._limit: Optional[int] = None
        self._order_desc = False

    def insert(self, payload: Dict[str, Any]):
        self._operation = "insert"
        self._payload = payload
        return self

    def update(self, payload: Dict[str, Any]):
        self._operation = "update"
        self._payload = payload
        return self

    def select(self, _columns: str):
        self._operation = "select"
        return self

    def eq(self, key: str, value: Any):
        self._filters.append(("eq", key, value))
        return self

    def lt(self, key: str, value: Any):
        self._filters.append(("lt", key, value))
        return self

    def order(self, _column: str, desc: bool = False):
        self._order_desc = desc
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    def execute(self):
        if self._operation == "insert":
            self.store._counter += 1
            run_id = f"run-{self.store._counter}"
            row = {"id": run_id, **self._payload}
            self.store.runs[run_id] = row
            return MagicMock(data=[row])

        if self._operation == "update":
            for run_id, row in self.store.runs.items():
                if all(row.get(k) == v for op, k, v in self._filters if op == "eq"):
                    row.update(self._payload or {})
                    return MagicMock(data=[row])
            return MagicMock(data=[])

        rows = list(self.store.runs.values())
        for op, key, value in self._filters:
            if op == "eq":
                rows = [row for row in rows if row.get(key) == value]
            elif op == "lt":
                rows = [row for row in rows if (row.get(key) or "") < value]
        if self._order_desc:
            rows = sorted(rows, key=lambda row: row.get("started_at") or "", reverse=True)
        if self._limit is not None:
            rows = rows[: self._limit]
        return MagicMock(data=rows)


class ScanResultsTable:
    def __init__(self, store: InMemoryScanStore) -> None:
        self.store = store
        self._filters: List[tuple] = []
        self._operation = "select"
        self._payload: Optional[Dict[str, Any]] = None
        self._limit: Optional[int] = None
        self._order_desc = False

    def insert(self, payload: Dict[str, Any]):
        self.store.results.append(payload)
        return MagicMock(data=[payload])

    def select(self, _columns: str):
        self._operation = "select"
        return self

    def eq(self, key: str, value: Any):
        self._filters.append(("eq", key, value))
        return self

    def neq(self, key: str, value: Any):
        self._filters.append(("neq", key, value))
        return self

    def order(self, _column: str, desc: bool = False):
        self._order_desc = desc
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    def execute(self):
        rows = list(self.store.results)
        for op, key, value in self._filters:
            if op == "eq":
                rows = [row for row in rows if row.get(key) == value]
            elif op == "neq":
                rows = [row for row in rows if row.get(key) != value]
        if self._order_desc:
            rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
        if self._limit is not None:
            rows = rows[: self._limit]
        return MagicMock(data=rows)


class ScanRunnerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryScanStore()
        self.scan_repo = ScanRepository(self.store)
        self.candidate_repo = MagicMock()
        self.fmp_client = MagicMock()
        self.sec_client = MagicMock()
        self.engine = MagicMock()

    def test_successful_run_completed(self) -> None:
        self.engine.analyze.side_effect = [
            analyze_result("AAPL"),
            analyze_result("MSFT"),
        ]
        result = run_scan(
            symbols=[symbol_row("AAPL"), symbol_row("MSFT")],
            universe_name="Teknoloji 10 [1-2]",
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
        )
        self.assertEqual(result.status, "COMPLETED")
        self.fmp_client.reset_scan_state.assert_called_once()
        self.assertEqual(self.candidate_repo.upsert_by_symbol.call_count, 2)
        run = self.store.runs[result.run_id]
        self.assertEqual(run["status"], "COMPLETED")

    def test_partial_symbol_failure_completed(self) -> None:
        self.engine.analyze.side_effect = [
            analyze_result("AAPL", errors=["FMP timeout"]),
            analyze_result("MSFT"),
        ]
        result = run_scan(
            symbols=[symbol_row("AAPL"), symbol_row("MSFT")],
            universe_name="Teknoloji 10 [1-2]",
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
        )
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.errors, 1)

    def test_all_symbols_fail_failed(self) -> None:
        self.engine.analyze.side_effect = RuntimeError("hard fail")
        result = run_scan(
            symbols=[symbol_row("AAPL"), symbol_row("MSFT")],
            universe_name="Teknoloji 10 [1-2]",
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
        )
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(self.store.runs[result.run_id]["status"], "FAILED")

    def test_fatal_outer_exception_fail_run_and_reraise(self) -> None:
        self.engine.analyze.return_value = analyze_result("AAPL")
        self.scan_repo.complete_run = MagicMock(side_effect=RuntimeError("db down"))
        with self.assertRaises(RuntimeError):
            run_scan(
                symbols=[symbol_row("AAPL")],
                universe_name="Teknoloji 10 [1-1]",
                scan_repo=self.scan_repo,
                candidate_repo=self.candidate_repo,
                fmp_client=self.fmp_client,
                sec_client=self.sec_client,
                engine=self.engine,
            )
        run_id = list(self.store.runs.keys())[0]
        self.assertEqual(self.store.runs[run_id]["status"], "FAILED")

    def test_progress_callback_optional(self) -> None:
        self.engine.analyze.return_value = analyze_result("AAPL")
        callback = MagicMock()
        run_scan(
            symbols=[symbol_row("AAPL")],
            universe_name="Teknoloji 10 [1-1]",
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
            progress_callback=callback,
        )
        callback.assert_called_once_with(1, 1)

    def test_manual_and_scheduled_same_pipeline(self) -> None:
        self.engine.analyze.return_value = analyze_result("NVDA")
        manual = run_scan(
            symbols=[symbol_row("NVDA")],
            universe_name="manual",
            source="manual",
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
        )
        scheduled = run_scan(
            symbols=[symbol_row("NVDA")],
            universe_name=scheduled_universe_name(date(2026, 8, 11)),
            source="scheduled",
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
        )
        self.assertEqual(manual.status, scheduled.status)
        self.assertEqual(manual.source, "manual")
        self.assertEqual(scheduled.source, "scheduled")


class ScheduledScanServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryScanStore()
        self.scan_repo = ScanRepository(self.store)

    def test_completed_same_day_skip(self) -> None:
        universe = scheduled_universe_name(date(2026, 8, 11))
        self.store.runs["run-1"] = {
            "id": "run-1",
            "universe_name": universe,
            "status": "COMPLETED",
            "started_at": "2026-08-11T03:00:00+00:00",
        }
        should_run, reason, _ = evaluate_scheduled_run(
            self.scan_repo,
            run_date=date(2026, 8, 11),
        )
        self.assertFalse(should_run)
        self.assertIn("already completed", reason or "")

    def test_failed_allows_retry(self) -> None:
        universe = scheduled_universe_name(date(2026, 8, 11))
        self.store.runs["run-1"] = {
            "id": "run-1",
            "universe_name": universe,
            "status": "FAILED",
            "started_at": "2026-08-11T03:00:00+00:00",
        }
        should_run, reason, _ = evaluate_scheduled_run(
            self.scan_repo,
            run_date=date(2026, 8, 11),
        )
        self.assertTrue(should_run)
        self.assertIsNone(reason)

    def test_active_running_skip(self) -> None:
        universe = scheduled_universe_name(date(2026, 8, 11))
        now = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)
        self.store.runs["run-1"] = {
            "id": "run-1",
            "universe_name": universe,
            "status": "RUNNING",
            "started_at": "2026-08-11T03:30:00+00:00",
        }
        should_run, reason, _ = evaluate_scheduled_run(
            self.scan_repo,
            run_date=date(2026, 8, 11),
            now=now,
        )
        self.assertFalse(should_run)
        self.assertIn("already running", reason or "")

    def test_stale_running_cleanup(self) -> None:
        cutoff = stale_running_cutoff(datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc))
        self.store.runs["run-1"] = {
            "id": "run-1",
            "universe_name": "Teknoloji 10 [1-3]",
            "status": "RUNNING",
            "started_at": "2026-08-10T20:00:00+00:00",
            "error_count": 0,
        }
        marked = self.scan_repo.mark_stale_running_failed(cutoff)
        self.assertEqual(marked, 1)
        self.assertEqual(self.store.runs["run-1"]["status"], "FAILED")

    def test_stale_running_then_retry_allowed(self) -> None:
        universe = scheduled_universe_name(date(2026, 8, 11))
        self.store.runs["run-1"] = {
            "id": "run-1",
            "universe_name": universe,
            "status": "RUNNING",
            "started_at": "2026-08-10T20:00:00+00:00",
        }
        now = datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc)
        should_run, reason, _ = evaluate_scheduled_run(
            self.scan_repo,
            run_date=date(2026, 8, 11),
            now=now,
        )
        self.assertTrue(should_run)
        self.assertIsNone(reason)

    def test_manual_runs_unaffected(self) -> None:
        self.store.runs["run-1"] = {
            "id": "run-1",
            "universe_name": "Teknoloji 10 [1-3]",
            "status": "COMPLETED",
            "started_at": "2026-08-11T03:00:00+00:00",
        }
        should_run, reason, _ = evaluate_scheduled_run(
            self.scan_repo,
            run_date=date(2026, 8, 11),
        )
        self.assertTrue(should_run)
        self.assertIsNone(reason)

    def test_utc_date_boundary(self) -> None:
        late_utc = datetime(2026, 8, 11, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(
            scheduled_universe_name(late_utc.date()),
            "SCHEDULED · Daily · 2026-08-11",
        )
        early_utc = datetime(2026, 8, 12, 0, 30, tzinfo=timezone.utc)
        self.assertEqual(
            scheduled_universe_name(early_utc.date()),
            "SCHEDULED · Daily · 2026-08-12",
        )


class DailyUniverseTests(unittest.TestCase):
    def test_union_deduplicates_symbols(self) -> None:
        rows = build_daily_universe_rows(
            sec_lookup={},
            watchlist_entries=[{
                "candidate": {"symbol": "AAPL", "company_name": "Apple"},
            }],
        )
        symbols = [row["symbol"] for row in rows]
        self.assertEqual(len(symbols), len(set(symbols)))
        self.assertIn("AAPL", symbols)
        self.assertIn("SPUS", symbols)

    def test_watchlist_empty(self) -> None:
        rows = build_daily_universe_rows(sec_lookup={}, watchlist_entries=[])
        self.assertGreaterEqual(len(rows), 10)

    def test_fixed_universe_rows(self) -> None:
        rows = build_fixed_universe_rows("Teknoloji 10", {})
        self.assertEqual(len(rows), 10)


class HeadlessRunnerTests(unittest.TestCase):
    def test_env_missing_supabase(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SupabaseConfigError):
                create_supabase_client()

    def test_supabase_url_trailing_slash_accepted(self) -> None:
        with patch("services.supabase_client_factory.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            create_supabase_client(
                url="https://example.supabase.co/",
                key="test-key",
            )
            mock_create.assert_called_once_with(
                "https://example.supabase.co",
                "test-key",
            )

    def test_supabase_url_quoted_value_accepted(self) -> None:
        with patch("services.supabase_client_factory.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            create_supabase_client(
                url='"https://example.supabase.co/"',
                key="test-key",
            )
            mock_create.assert_called_once_with(
                "https://example.supabase.co",
                "test-key",
            )

    def test_supabase_url_rest_path_accepted(self) -> None:
        with patch("services.supabase_client_factory.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            create_supabase_client(
                url="https://example.supabase.co/rest/v1",
                key="test-key",
            )
            mock_create.assert_called_once_with(
                "https://example.supabase.co",
                "test-key",
            )

    def test_supabase_url_without_scheme_accepted(self) -> None:
        with patch("services.supabase_client_factory.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            create_supabase_client(
                url="example.supabase.co",
                key="test-key",
            )
            mock_create.assert_called_once_with(
                "https://example.supabase.co",
                "test-key",
            )

    def test_supabase_url_invalid_still_rejected(self) -> None:
        with self.assertRaises(SupabaseConfigError):
            create_supabase_client(
                url="http://not-supabase.example.com",
                key="test-key",
            )

    def test_fmp_env_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(FMPError):
                from services.fmp_client import FMPClient
                FMPClient.from_env()

    def test_cli_import_no_side_effect(self) -> None:
        module = importlib.import_module("scripts.run_daily_scan")
        self.assertTrue(callable(module.main))

    def test_cli_compile(self) -> None:
        py_compile.compile("scripts/run_daily_scan.py", doraise=True)

    def test_scout_page_compile(self) -> None:
        py_compile.compile("pages/2_Scout_Tarama.py", doraise=True)

    def test_scout_page_uses_run_scan(self) -> None:
        with open("pages/2_Scout_Tarama.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("run_scan(", source)
        self.assertNotIn("scan_repo.complete_run(", source)

    def test_cli_exit_skip(self) -> None:
        module = importlib.import_module("scripts.run_daily_scan")
        with patch.object(module, "create_supabase_client") as mock_client:
            mock_client.return_value = MagicMock()
            with patch.object(module, "ScanRepository") as mock_scan_repo_cls:
                mock_scan_repo = mock_scan_repo_cls.return_value
                mock_scan_repo.mark_stale_running_failed.return_value = 0
                with patch.object(module, "evaluate_scheduled_run") as mock_eval:
                    mock_eval.return_value = (False, "Daily scan already completed for 2026-08-11.", {})
                    with patch.dict(
                        "os.environ",
                        {
                            "SEC_CONTACT_EMAIL": "test@example.com",
                            "FMP_API_KEY": "key",
                            "SUPABASE_URL": "https://x.supabase.co",
                            "SUPABASE_KEY": "key",
                        },
                    ):
                        self.assertEqual(module.main(), 0)

    def test_cli_exit_failed(self) -> None:
        module = importlib.import_module("scripts.run_daily_scan")
        failed = ScanRunResult(
            run_id="r1",
            source="scheduled",
            universe_name="SCHEDULED · Daily · 2026-08-11",
            total_symbols=1,
            scanned=1,
            updated=0,
            strong=0,
            errors=1,
            excluded=0,
            symbols_without_previous=0,
            status="FAILED",
        )
        with patch.object(module, "create_supabase_client") as mock_client:
            mock_client.return_value = MagicMock()
            with patch.object(module, "ScanRepository"):
                with patch.object(module, "CandidateRepository"):
                    with patch.object(module, "WatchlistRepository") as mock_wl:
                        mock_wl.return_value.list_active.return_value = []
                        with patch.object(module, "FMPClient") as mock_fmp:
                            mock_fmp.from_env.return_value = MagicMock()
                            with patch.object(module, "_load_sec_lookup", return_value={}):
                                with patch.object(module, "evaluate_scheduled_run") as mock_eval:
                                    mock_eval.return_value = (True, None, None)
                                    with patch.object(module, "run_scan", return_value=failed):
                                        with patch.dict(
                                            "os.environ",
                                            {"SEC_CONTACT_EMAIL": "test@example.com"},
                                        ):
                                            self.assertEqual(module.main(), 1)


if __name__ == "__main__":
    unittest.main()
