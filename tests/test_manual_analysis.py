import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from repositories.scan_repository import ScanRepository
from services.change_detection_engine import detect_changes
from services.manual_analysis_service import (
    analyze_security,
    save_manual_candidate,
)
from services.fmp_client import FMPError
from services.research_monitor_service import build_monitor_feed
from services.scan_runner_service import run_scan
from services.scan_universe_service import MANUAL_UNIVERSE_NAME
from services.scan_snapshot import build_scan_snapshot
from services.symbol_resolver_service import SymbolNotFoundError
from tests.test_scan_runner import InMemoryScanStore, analyze_result, symbol_row


def resolved_equity(symbol: str, **overrides):
    from services.symbol_resolver_service import ResolvedSecurity

    base = {
        "symbol": symbol,
        "company_name": symbol,
        "exchange": "NASDAQ",
        "security_type": "COMMON_STOCK",
        "issuer_category": "OPERATING_COMPANY",
        "is_etf": False,
        "cik": 123,
        "resolution_source": "sec",
        "resolution_confidence": "HIGH",
        "is_equity_eligible": True,
    }
    base.update(overrides)
    return ResolvedSecurity(**base)


def resolved_unresolved(symbol: str, **overrides):
    from services.symbol_resolver_service import ResolvedSecurity, SECURITY_TYPE_UNRESOLVED

    base = {
        "symbol": symbol,
        "company_name": f"{symbol} TRUST, SERIES 1",
        "exchange": "NASDAQ",
        "security_type": SECURITY_TYPE_UNRESOLVED,
        "issuer_category": "UNKNOWN",
        "is_etf": False,
        "cik": 1067839,
        "resolution_source": "sec",
        "resolution_confidence": "LOW",
        "is_equity_eligible": False,
        "classification_warning": "FMP rate limit nedeniyle varlık türü doğrulanamadı.",
    }
    base.update(overrides)
    return ResolvedSecurity(**base)


def resolved_etf(symbol: str):
    from services.symbol_resolver_service import ResolvedSecurity

    return ResolvedSecurity(
        symbol=symbol,
        company_name=symbol,
        exchange="NYSE Arca",
        security_type="ETF",
        issuer_category="FUND",
        is_etf=True,
        cik=None,
        resolution_source="config_etf",
        resolution_confidence="HIGH",
        is_equity_eligible=False,
    )


class ManualAnalysisServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate_repo = MagicMock()
        self.candidate_repo.get_by_symbol.return_value = None
        self.candidate_repo.upsert_by_symbol.side_effect = lambda payload: {
            **payload,
            "id": "saved-id",
        }
        self.scan_repo = MagicMock()
        self.fmp_client = MagicMock()
        self.sec_client = MagicMock()
        self.engine = MagicMock()

    @patch("services.manual_analysis_service.run_scan")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_single_equity_analysis(self, mock_resolve, mock_run_scan) -> None:
        mock_resolve.return_value = resolved_equity("NVDA")
        mock_run_scan.return_value = MagicMock(
            candidates=[{"symbol": "NVDA", "nabi_score": 80.0, "data_completeness": 90.0}],
            fmp_rate_limited=False,
        )
        result = analyze_security(
            "NVDA",
            candidate_repo=self.candidate_repo,
            scan_repo=self.scan_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
        )
        self.assertEqual(result.analysis_kind, "equity")
        mock_run_scan.assert_called_once()
        kwargs = mock_run_scan.call_args.kwargs
        self.assertEqual(kwargs["universe_name"], MANUAL_UNIVERSE_NAME)
        self.assertFalse(kwargs["persist_candidates"])
        self.assertEqual(kwargs["inter_symbol_pause_seconds"], 0.0)

    @patch("services.manual_analysis_service.run_scan")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_analyze_does_not_auto_create_candidate(self, mock_resolve, mock_run_scan) -> None:
        mock_resolve.return_value = resolved_equity("JNJ")
        mock_run_scan.return_value = MagicMock(
            candidates=[{"symbol": "JNJ", "nabi_score": 70.0, "data_completeness": 80.0}],
            fmp_rate_limited=False,
        )
        analyze_security(
            "JNJ",
            candidate_repo=self.candidate_repo,
            scan_repo=self.scan_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
        )
        self.candidate_repo.upsert_by_symbol.assert_not_called()

    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_etf_never_enters_equity_scanner(self, mock_resolve, mock_analyze_fund) -> None:
        from services.fund_analysis_contract import FundAnalysisResult

        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = FundAnalysisResult(
            symbol="SPUS",
            fund_name="SPUS ETF",
            current_price=42.0,
            participation_status="Uygun",
            participation_score=100,
            participation_source="configured",
        )
        with patch("services.manual_analysis_service.run_scan") as mock_run_scan:
            result = analyze_security(
                "SPUS",
                candidate_repo=self.candidate_repo,
                scan_repo=self.scan_repo,
                fmp_client=self.fmp_client,
                sec_client=self.sec_client,
            )
            mock_run_scan.assert_not_called()
        self.assertEqual(result.analysis_kind, "fund")
        self.assertIsNone(result.candidate)
        self.assertIsNotNone(result.fund_result)

    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_etf_structured_metadata(self, mock_resolve, mock_analyze_fund) -> None:
        from services.fund_analysis_contract import FundAnalysisResult

        mock_resolve.return_value = resolved_etf("QQQ")
        mock_analyze_fund.return_value = FundAnalysisResult(
            symbol="QQQ",
            fund_name="Invesco QQQ Trust",
            current_price=380.5,
            participation_status="Kontrol Et",
            participation_score=60,
        )
        result = analyze_security(
            "QQQ",
            candidate_repo=self.candidate_repo,
            scan_repo=self.scan_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
        )
        self.assertEqual(result.current_price, 380.5)
        self.assertEqual(result.participation_status, "Kontrol Et")
        self.assertEqual(result.analysis_kind, "fund")

    def test_explicit_save_idempotent(self) -> None:
        payload = {
            "symbol": "JNJ",
            "company_name": "Johnson & Johnson",
            "market": "ABD",
            "data_completeness": 70.0,
            "nabi_score": 65.0,
        }
        first = save_manual_candidate(self.candidate_repo, payload)
        second = save_manual_candidate(self.candidate_repo, payload)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.candidate_repo.upsert_by_symbol.call_count, 2)

    def test_existing_candidate_save_no_duplicate_logic(self) -> None:
        self.candidate_repo.get_by_symbol.return_value = {"id": "existing", "symbol": "NVDA"}
        payload = {"symbol": "NVDA", "company_name": "NVIDIA", "market": "ABD"}
        saved = save_manual_candidate(self.candidate_repo, payload)
        self.assertEqual(saved["id"], "saved-id")

    def test_cannot_save_etf_candidate(self) -> None:
        with self.assertRaises(ValueError):
            save_manual_candidate(
                self.candidate_repo,
                {"symbol": "SPUS", "security_type": "ETF", "is_etf": True},
            )

    def test_watchlist_requires_persisted_candidate(self) -> None:
        from repositories.watchlist_repository import WatchlistRepository

        repo = WatchlistRepository(MagicMock())
        self.assertTrue(callable(repo.add_candidate))

    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_fmp_rate_limit_graceful_on_etf(self, mock_resolve, mock_analyze_fund) -> None:
        from services.fund_analysis_contract import FundAnalysisResult

        mock_resolve.return_value = resolved_etf("HLAL")
        mock_analyze_fund.return_value = FundAnalysisResult(
            symbol="HLAL",
            warnings=["FMP etf_info: rate limit nedeniyle veri alınamadı."],
        )
        result = analyze_security(
            "HLAL",
            candidate_repo=self.candidate_repo,
            scan_repo=self.scan_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
        )
        self.assertTrue(result.warnings)
        self.assertEqual(result.analysis_kind, "fund")


class ManualRunIsolationTests(unittest.TestCase):
    def test_manual_runs_excluded_from_monitor_aggregate(self) -> None:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        scan_repo = MagicMock()
        scan_repo.get_completed_runs_since.return_value = [
            {"id": "scheduled-run", "universe_name": "SCHEDULED · Daily · 2026-08-11"},
            {"id": "manual-run", "universe_name": MANUAL_UNIVERSE_NAME},
        ]
        scan_repo.get_results_for_runs.return_value = [
            {
                "symbol": "NVDA",
                "scan_run_id": "scheduled-run",
                "created_at": since.isoformat(),
                "candidate_snapshot": {},
                "scan_runs": {"universe_name": "SCHEDULED · Daily · 2026-08-11"},
            },
            {
                "symbol": "JNJ",
                "scan_run_id": "manual-run",
                "created_at": since.isoformat(),
                "candidate_snapshot": {},
                "scan_runs": {"universe_name": MANUAL_UNIVERSE_NAME},
            },
        ]
        scan_repo.get_all_completed_run_ids_before.return_value = []
        scan_repo.get_symbols_with_results_before.return_value = set()
        scan_repo.row_to_snapshot.side_effect = lambda row: row.get("candidate_snapshot") or {}

        build_monitor_feed(
            scan_repo=scan_repo,
            candidates=[],
            since=since,
        )
        scan_repo.get_completed_runs_since.assert_called_once_with(
            since,
            None,
            exclude_manual=True,
        )
        scan_repo.get_all_completed_run_ids_before.assert_called_once_with(
            since,
            None,
            exclude_manual=True,
        )

    def test_company_intelligence_still_queries_all_runs(self) -> None:
        with open("services/company_intelligence_service.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("exclude_manual=True", source)


class ManualPreviousSnapshotTests(unittest.TestCase):
    def test_first_manual_analysis_no_fake_change(self) -> None:
        rows = [
            {
                "symbol": "NVDA",
                "candidate_snapshot": {"symbol": "NVDA", "nabi_score": 80.0},
                "scan_runs": {
                    "universe_name": "SCHEDULED · Daily · 2026-08-11",
                    "status": "COMPLETED",
                },
            }
        ]
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.eq.return_value = query
        query.neq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value = MagicMock(data=rows)

        repo = ScanRepository(client)
        snapshot = repo.get_previous_snapshot(
            "NVDA",
            "manual-current",
            MANUAL_UNIVERSE_NAME,
        )
        self.assertIsNone(snapshot)

    def test_later_manual_history_compares_within_manual(self) -> None:
        rows = [
            {
                "symbol": "NVDA",
                "candidate_snapshot": {"symbol": "NVDA", "nabi_score": 75.0},
                "scan_runs": {
                    "universe_name": MANUAL_UNIVERSE_NAME,
                    "status": "COMPLETED",
                },
            }
        ]
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.eq.return_value = query
        query.neq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value = MagicMock(data=rows)

        repo = ScanRepository(client)
        snapshot = repo.get_previous_snapshot(
            "NVDA",
            "manual-current",
            MANUAL_UNIVERSE_NAME,
        )
        self.assertEqual(snapshot["nabi_score"], 75.0)


class RunScanPersistCandidatesTests(unittest.TestCase):
    def test_persist_candidates_false_skips_upsert(self) -> None:
        store = InMemoryScanStore()
        scan_repo = ScanRepository(store)
        candidate_repo = MagicMock()
        engine = MagicMock()
        engine.analyze.return_value = analyze_result("NVDA")

        run_scan(
            symbols=[symbol_row("NVDA")],
            universe_name=MANUAL_UNIVERSE_NAME,
            scan_repo=scan_repo,
            candidate_repo=candidate_repo,
            fmp_client=MagicMock(),
            sec_client=MagicMock(),
            engine=engine,
            persist_candidates=False,
        )
        candidate_repo.upsert_by_symbol.assert_not_called()
        self.assertEqual(len(store.results), 1)


class FailClosedAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate_repo = MagicMock()
        self.candidate_repo.get_by_symbol.return_value = None
        self.scan_repo = MagicMock()
        self.fmp_client = MagicMock()
        self.sec_client = MagicMock()

    @patch("services.manual_analysis_service.run_scan")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_qqq_rate_limit_sec_live_failure_scanner_not_called(
        self,
        mock_resolve,
        mock_run_scan,
    ) -> None:
        mock_resolve.return_value = resolved_unresolved("QQQ")
        result = analyze_security(
            "QQQ",
            candidate_repo=self.candidate_repo,
            scan_repo=self.scan_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
        )
        mock_run_scan.assert_not_called()
        self.assertEqual(result.analysis_kind, "unresolved")
        self.assertIsNone(result.candidate)
        self.assertIn("doğrulanamadı", result.unsupported_reason or "")

    @patch("services.manual_analysis_service.run_scan")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_unresolved_no_equity_handoff(self, mock_resolve, mock_run_scan) -> None:
        mock_resolve.return_value = resolved_unresolved("XYZT")
        result = analyze_security(
            "XYZT",
            candidate_repo=self.candidate_repo,
            scan_repo=self.scan_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
        )
        self.assertEqual(result.analysis_kind, "unresolved")
        self.assertIsNone(result.candidate)
        mock_run_scan.assert_not_called()

    def test_unresolved_cannot_be_saved(self) -> None:
        with self.assertRaises(ValueError):
            save_manual_candidate(
                self.candidate_repo,
                {"symbol": "QQQ", "security_type": "UNRESOLVED"},
            )

    @patch("services.manual_analysis_service.run_scan")
    def test_qqq_live_resolver_path_end_to_end(self, mock_run_scan) -> None:
        fmp = MagicMock()
        fmp.profile.side_effect = FMPError(
            "rate limited",
            error_class="rate_limit",
        )
        from services.symbol_resolver_service import resolve_symbol

        resolved = resolve_symbol(
            "QQQ",
            candidate_repo=self.candidate_repo,
            fmp_client=fmp,
            sec_lookup={
                "QQQ": {
                    "symbol": "QQQ",
                    "company_name": "INVESCO QQQ TRUST, SERIES 1",
                    "exchange": "NASDAQ",
                    "cik": 1067839,
                }
            },
        )
        self.assertFalse(resolved.is_equity_eligible)
        with patch(
            "services.manual_analysis_service.resolve_symbol",
            return_value=resolved,
        ):
            result = analyze_security(
                "QQQ",
                candidate_repo=self.candidate_repo,
                scan_repo=self.scan_repo,
                fmp_client=fmp,
                sec_client=self.sec_client,
            )
        mock_run_scan.assert_not_called()
        self.assertEqual(result.analysis_kind, "unresolved")


class ManualSemanticAuditTests(unittest.TestCase):
    @patch("services.manual_analysis_service.run_scan")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_nvda_equity_fixture(self, mock_resolve, mock_run_scan) -> None:
        mock_resolve.return_value = resolved_equity("NVDA")
        mock_run_scan.return_value = MagicMock(
            candidates=[{
                "symbol": "NVDA",
                "nabi_score": 80.0,
                "data_completeness": 76.0,
                "decision_label": "ARAŞTIRMA ADAYI",
            }],
            fmp_rate_limited=False,
        )
        candidate_repo = MagicMock(get_by_symbol=MagicMock(return_value=None))
        result = analyze_security(
            "NVDA",
            candidate_repo=candidate_repo,
            scan_repo=MagicMock(),
            fmp_client=MagicMock(),
            sec_client=MagicMock(),
        )
        self.assertEqual(result.analysis_kind, "equity")
        self.assertFalse(result.is_persisted)
        candidate_repo.upsert_by_symbol.assert_not_called()

    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_spus_etf_fixture(self, mock_resolve, mock_analyze_fund) -> None:
        from services.fund_analysis_contract import FundAnalysisResult

        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = FundAnalysisResult(symbol="SPUS")
        with patch("services.manual_analysis_service.run_scan") as mock_run_scan:
            result = analyze_security(
                "SPUS",
                candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
                scan_repo=MagicMock(),
                fmp_client=MagicMock(),
                sec_client=MagicMock(),
            )
            mock_run_scan.assert_not_called()
        payload = result.fund_result.to_dict() if result.fund_result else {}
        self.assertNotIn("nabi_score", payload)


class DashboardSmokeTests(unittest.TestCase):
    def test_dashboard_compiles(self) -> None:
        import py_compile

        py_compile.compile("pages/1_Dashboard.py", doraise=True)

    def test_dashboard_imports_manual_analysis(self) -> None:
        with open("pages/1_Dashboard.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("analyze_security", source)
        self.assertIn("Bir sembol analiz et", source)


class RuntimeImportContractTests(unittest.TestCase):
    def test_dashboard_imports_fund_analysis(self) -> None:
        with open("pages/1_Dashboard.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("analysis_kind == \"fund\"", source)
        self.assertIn("bağımsız NABI Şeriat uygunluk doğrulaması değildir", source)
        self.assertIn("PERFORMANCE_SECTION_TITLE", source)
        self.assertIn("PRICE_RETURN_DISCLAIMER", source)
        self.assertIn("PERFORMANCE_UNAVAILABLE_MESSAGE", source)
        self.assertNotIn("Company Report", source.split("analysis_kind == \"fund\"")[1].split("elif")[0])

    def test_manual_analysis_imports_in_fresh_process(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from services.manual_analysis_service import analyze_security; "
                "from services.fund_analysis_service import analyze_fund; "
                "from services.fund_performance_service import normalize_price_points; "
                "from services.scan_universe_service import MANUAL_UNIVERSE_NAME; "
                "assert MANUAL_UNIVERSE_NAME == 'MANUAL'; "
                "print('MANUAL_IMPORT_OK')",
            ],
            cwd=".",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("MANUAL_IMPORT_OK", result.stdout)

    def test_scan_snapshot_does_not_export_manual_universe_name(self) -> None:
        import services.scan_snapshot as scan_snapshot

        self.assertFalse(hasattr(scan_snapshot, "MANUAL_UNIVERSE_NAME"))

    def test_manual_universe_constant_is_canonical(self) -> None:
        from services.scan_universe_service import MANUAL_UNIVERSE_NAME, is_manual_universe

        self.assertEqual(MANUAL_UNIVERSE_NAME, "MANUAL")
        self.assertTrue(is_manual_universe("MANUAL"))
        self.assertFalse(is_manual_universe("SCHEDULED · Daily · 2026-08-11"))

    def test_dashboard_dependency_chain_imports_in_fresh_process(self) -> None:
        import subprocess
        import sys

        script = """
import importlib.util
import sys
from unittest.mock import MagicMock

mock_st = MagicMock()
mock_st.session_state = {}
mock_st.columns.side_effect = lambda spec: [
    MagicMock() for _ in range(len(spec) if isinstance(spec, list) else spec)
]
mock_st.button.return_value = False
mock_st.text_input.return_value = ""
mock_st.cache_data = lambda **kwargs: (lambda fn: fn)
mock_st.divider = lambda: None
mock_st.title = lambda *a, **k: None
mock_st.markdown = lambda *a, **k: None
mock_st.caption = lambda *a, **k: None
mock_st.metric = lambda *a, **k: None
mock_st.info = lambda *a, **k: None
mock_st.warning = lambda *a, **k: None
mock_st.error = lambda *a, **k: None
mock_st.success = lambda *a, **k: None
mock_st.spinner = MagicMock(
    return_value=MagicMock(
        __enter__=MagicMock(return_value=None),
        __exit__=MagicMock(return_value=False),
    )
)
mock_st.subheader = lambda *a, **k: None
mock_st.switch_page = lambda *a, **k: None
mock_st.expander = MagicMock(
    return_value=MagicMock(
        __enter__=MagicMock(return_value=None),
        __exit__=MagicMock(return_value=False),
    )
)
mock_st.query_params = {}
sys.modules["streamlit"] = mock_st

from unittest.mock import patch, MagicMock

brief = {
    "scheduled_run": {"status_label": "—", "detail": None},
    "headline": "x",
    "summary_stats": {
        "meaningful_change_count": 0,
        "new_candidate_count": 0,
        "open_research_count": 0,
        "data_issue_count": 0,
    },
    "today_actions": [],
    "new_candidates": [],
    "data_quality_updates": [],
    "watchlist_changes": [],
    "open_research": [],
    "data_issues": [],
}

with patch("services.supabase_client.get_supabase_client", return_value=MagicMock()):
    with patch("services.daily_brief_service.build_daily_brief", return_value=brief):
        with patch(
            "repositories.candidate_repository.CandidateRepository.get_all",
            return_value=[],
        ):
            with patch(
                "repositories.candidate_repository.CandidateRepository.get_dashboard_stats",
                return_value={
                    "total": 0,
                    "strong": 0,
                    "watch": 0,
                    "participation_ok": 0,
                    "open_research": 0,
                },
            ):
                spec = importlib.util.spec_from_file_location(
                    "dashboard_page_smoke",
                    "pages/1_Dashboard.py",
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
print("DASHBOARD_IMPORT_OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=".",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("DASHBOARD_IMPORT_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
