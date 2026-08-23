import importlib
import importlib.util
import py_compile
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.daily_brief_service import build_daily_brief
from services.research_history_service import (
    CATEGORY_ATTENTION,
    CATEGORY_DATA_ISSUES,
    CATEGORY_NEW,
    CATEGORY_NONE,
    CATEGORY_WATCHLIST,
    build_monitor_entries,
)
from services.ui_formatters import (
    format_data_issue_summary,
    format_scheduled_run_detail,
    format_scheduled_run_status,
    resolve_scheduled_run_status,
)


def snapshot(**overrides):
    base = {
        "symbol": "NVDA",
        "company_name": "NVIDIA",
        "decision_label": "ARAŞTIRMA ADAYI",
        "data_completeness": 76.0,
        "freshness_status": "FRESH",
        "_comparison_source": "snapshot",
    }
    base.update(overrides)
    return base


def row(symbol, created_at, snap, run_id="run-1"):
    return {
        "id": f"{symbol}-{run_id}",
        "symbol": symbol,
        "scan_run_id": run_id,
        "created_at": created_at,
        "candidate_snapshot": snap,
    }


def snapshot_fn(row_obj):
    return row_obj.get("candidate_snapshot") or {}


def research_change_event():
    return {
        "message": "İZLE → ARAŞTIRMA ADAYI",
        "severity": "HIGH",
        "field": "decision_label",
        "category": "DECISION",
        "old": "İZLE",
        "new": "ARAŞTIRMA ADAYI",
    }


def monitor_entry(
    symbol,
    *,
    category=CATEGORY_ATTENTION,
    meaningful=1,
    first_seen=False,
    events=None,
    reasons=None,
):
    return {
        "symbol": symbol,
        "company_name": symbol,
        "candidate": {"symbol": symbol, "decision_label": "ARAŞTIRMA ADAYI"},
        "latest_snapshot": snapshot(symbol=symbol),
        "events": events or [{
            "message": "Veri tamlığı %12 → %76",
            "severity": "MEDIUM",
            "field": "data_completeness",
            "category": "COMPLETENESS",
            "old": 12.0,
            "new": 76.0,
            "delta": 64.0,
        }],
        "meaningful_change_count": meaningful,
        "window_change_score": 15 if meaningful else 0,
        "latest_scan_at": "2026-08-11T14:47:00+00:00",
        "is_first_seen_in_window": first_seen,
        "primary_category": category,
        "recent_change": {
            "has_meaningful_change": meaningful > 0,
            "change_score": 15 if meaningful else 0,
            "changes": events or [{
                "message": "Veri tamlığı %12 → %76",
                "severity": "MEDIUM",
                "field": "data_completeness",
                "category": "COMPLETENESS",
                "old": 12.0,
                "new": 76.0,
                "delta": 64.0,
            }],
        },
        "research_priority": {
            "priority_score": 54.0,
            "priority_label": "ORTA",
            "reasons": reasons or [],
        },
    }


def scheduled_run(**overrides):
    base = {
        "id": "run-scheduled-1",
        "universe_name": "SCHEDULED · Daily · 2026-08-11",
        "status": "COMPLETED",
        "scanned_symbols": 13,
        "total_symbols": 13,
        "error_count": 0,
        "started_at": "2026-08-11T14:46:52+00:00",
        "completed_at": "2026-08-11T14:47:07+00:00",
    }
    base.update(overrides)
    return base


def excluded_monitor_entry(symbol: str = "HLAL"):
    return monitor_entry(
        symbol,
        events=[{
            "message": "Menkul kıymet elendi",
            "severity": "HIGH",
            "field": "data_completeness",
        }],
        reasons=["Menkul kıymet elendi"],
    )


class DailyBriefImportTests(unittest.TestCase):
    def test_ui_formatters_exports_for_daily_brief(self) -> None:
        from services.ui_formatters import (
            format_data_issue_summary,
            format_priority_reasons,
            format_scheduled_run_detail,
            format_scheduled_run_status,
            resolve_scheduled_run_status,
        )

        self.assertTrue(callable(format_data_issue_summary))
        self.assertTrue(callable(format_priority_reasons))
        self.assertTrue(callable(format_scheduled_run_detail))
        self.assertTrue(callable(format_scheduled_run_status))
        self.assertTrue(callable(resolve_scheduled_run_status))

    def test_daily_brief_service_import_chain(self) -> None:
        importlib.invalidate_caches()
        module = importlib.import_module("services.daily_brief_service")
        module = importlib.reload(module)
        self.assertTrue(callable(module.build_daily_brief))


class DailyBriefServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scan_repo = MagicMock()
        self.candidate_repo = MagicMock()
        self.watchlist_repo = MagicMock()
        self.candidate_repo.get_all.return_value = []
        self.watchlist_repo.watched_candidate_ids.return_value = set()
        self.scan_repo.get_latest_scheduled_run.return_value = None
        self.scan_repo.get_completed_runs_since.return_value = []
        self.scan_repo.get_results_for_runs.return_value = []
        self.scan_repo.get_results_for_run.return_value = []
        self.scan_repo.get_all_completed_run_ids_before.return_value = []
        self.scan_repo.get_symbols_with_results_before.return_value = set()
        self.scan_repo.row_to_snapshot.side_effect = snapshot_fn

    def _feed(self, **categories):
        return {
            "since": datetime.now(timezone.utc) - timedelta(hours=24),
            "entries": [],
            "categories": {
                "ATTENTION": categories.get("ATTENTION", []),
                "WATCHLIST": categories.get("WATCHLIST", []),
                "NEW": categories.get("NEW", []),
                "DATA_ISSUES": categories.get("DATA_ISSUES", []),
            },
        }

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_deterministic_headline_with_changes(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            ATTENTION=[
                monitor_entry("NVDA", events=[research_change_event()]),
                monitor_entry("MSFT", events=[research_change_event()]),
            ],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertIn(
            "2 şirkette araştırma açısından anlamlı değişiklik bulundu",
            brief["headline"],
        )
        self.assertEqual(brief["summary_stats"]["meaningful_change_count"], 2)
        self.assertEqual(brief["summary_stats"]["research_change_count"], 2)

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_zero_change_headline(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertIn(
            "Bugün araştırma önceliğini değiştiren yeni bir gelişme yok.",
            brief["headline"],
        )

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_latest_scheduled_success(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        self.scan_repo.get_latest_scheduled_run.return_value = scheduled_run()
        self.scan_repo.get_results_for_run.return_value = [
            {
                "symbol": f"S{i}",
                "status": "TAM VERİ",
                "decision": "ARAŞTIRMA ADAYI",
                "errors": [],
                "endpoint_status": {"fmp_profile": "OK"},
            }
            for i in range(13)
        ]
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["scheduled_run"]["status"], "success")
        self.assertEqual(brief["scheduled_run"]["status_label"], "Başarılı")

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_latest_scheduled_partial(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        self.scan_repo.get_latest_scheduled_run.return_value = scheduled_run(
            error_count=10,
        )
        from tests.test_scan_run_health import production_fixture_results

        self.scan_repo.get_results_for_run.return_value = production_fixture_results()
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["scheduled_run"]["status"], "partial")
        detail = brief["scheduled_run"]["detail"]
        self.assertIn("13 sembol tarandı", detail)
        self.assertIn("10 kullanılabilir sonuç", detail)
        self.assertNotIn("başarısız", detail.casefold())

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_scheduled_failed(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        self.scan_repo.get_latest_scheduled_run.return_value = scheduled_run(
            status="FAILED",
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["scheduled_run"]["status"], "failed")
        self.assertEqual(
            brief["scheduled_run"]["detail"],
            "Otomatik tarama tamamlanamadı.",
        )

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_scheduled_missing(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["scheduled_run"]["status"], "missing")
        self.assertEqual(
            brief["scheduled_run"]["detail"],
            "Bugün henüz otomatik tarama yok.",
        )

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_error_count_not_labeled_failed(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        self.scan_repo.get_latest_scheduled_run.return_value = scheduled_run(
            error_count=10,
        )
        from tests.test_scan_run_health import production_fixture_results

        self.scan_repo.get_results_for_run.return_value = production_fixture_results()
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        detail = brief["scheduled_run"]["detail"]
        self.assertNotIn("10 hata", detail)
        self.assertNotIn("başarısız", detail.casefold())

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_attention_items_from_monitor(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            ATTENTION=[monitor_entry("NVDA")],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["today_actions"], [])
        self.assertEqual(len(brief["attention_items"]), 1)
        self.assertEqual(brief["attention_items"][0]["symbol"], "NVDA")
        self.assertEqual(len(brief["data_quality_updates"]), 1)

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_new_candidates(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            NEW=[monitor_entry("PLTR", category=CATEGORY_NEW, first_seen=True, meaningful=0)],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["today_actions"], [])
        self.assertEqual(brief["new_candidates"][0]["symbol"], "PLTR")

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_watchlist_changes(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            WATCHLIST=[
                monitor_entry("AAPL", category=CATEGORY_WATCHLIST, events=[research_change_event()]),
            ],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["today_actions"][0]["symbol"], "AAPL")
        self.assertEqual(brief["watchlist_changes"], [])

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_open_research_excludes_tamamlandi(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        self.candidate_repo.get_all.return_value = [
            {
                "symbol": "NVDA",
                "research_status": "INCELEMEDE",
                "research_next_action": "Q3 sonrası tekrar bak",
                "last_reviewed_at": "2026-08-10T21:19:00+00:00",
            },
            {"symbol": "MSFT", "research_status": "TAMAMLANDI"},
        ]
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        symbols = [item["symbol"] for item in brief["open_research"]]
        self.assertEqual(symbols, ["NVDA"])

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_incelemde_open_research(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        self.candidate_repo.get_all.return_value = [
            {"symbol": "NVDA", "research_status": "INCELEMEDE"},
            {"symbol": "MSFT", "research_status": "YENI"},
        ]
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["open_research"][0]["workflow_status"], "INCELEMEDE")

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_next_action_and_last_reviewed_included(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        self.candidate_repo.get_all.return_value = [{
            "symbol": "NVDA",
            "research_status": "INCELEMEDE",
            "research_next_action": "Q3 earnings sonrası tekrar bak",
            "last_reviewed_at": "2026-08-10T21:19:00+00:00",
        }]
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        item = brief["open_research"][0]
        self.assertEqual(item["research_next_action"], "Q3 earnings sonrası tekrar bak")
        self.assertEqual(item["last_reviewed_at"], "2026-08-10T21:19:00+00:00")

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_data_issues(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            DATA_ISSUES=[monitor_entry("TSM", category=CATEGORY_DATA_ISSUES)],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(len(brief["data_issues"]), 1)

    def test_fmp_unavailable_not_fundamental_deterioration(self) -> None:
        summary = format_data_issue_summary({
            "symbol": "ASML",
            "events": [{
                "category": "AVAILABILITY",
                "message": "FMP quote: FMP çağrı limiti aktif",
            }],
            "candidate": {},
            "latest_snapshot": {},
        })
        self.assertIn("FMP verisi geçici", summary)
        self.assertNotIn("kötüleş", summary.casefold())

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_excluded_etf_not_in_attention(self, mock_feed) -> None:
        entry = excluded_monitor_entry("HLAL")
        entry["latest_snapshot"] = {
            "symbol": "HLAL",
            "status": "ELENDİ",
            "excluded": True,
            "issuer_category": "FUND",
        }
        mock_feed.return_value = self._feed(
            ATTENTION=[entry, monitor_entry("NVDA", events=[research_change_event()])],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        symbols = [item["symbol"] for item in brief["today_actions"]]
        self.assertEqual(symbols, ["NVDA"])
        self.assertEqual(brief["attention_items"], [])

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_excluded_etf_not_in_new_candidates(self, mock_feed) -> None:
        entry = excluded_monitor_entry("SPUS")
        entry["primary_category"] = CATEGORY_NEW
        entry["latest_snapshot"] = {
            "symbol": "SPUS",
            "status": "ELENDİ",
            "excluded": True,
            "issuer_category": "FUND",
        }
        mock_feed.return_value = self._feed(
            NEW=[entry, monitor_entry("TSM", category=CATEGORY_NEW, first_seen=True)],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["today_actions"], [])
        self.assertEqual([item["symbol"] for item in brief["new_candidates"]], ["TSM"])

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_equity_first_seen_still_appears(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            NEW=[
                monitor_entry("TSM", category=CATEGORY_NEW, first_seen=True, meaningful=0),
                monitor_entry("META", category=CATEGORY_NEW, first_seen=True, meaningful=0),
                monitor_entry("ASML", category=CATEGORY_NEW, first_seen=True, meaningful=0),
                monitor_entry("PLTR", category=CATEGORY_NEW, first_seen=True, meaningful=0),
            ],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
            max_new=4,
        )
        self.assertEqual(brief["today_actions"], [])
        self.assertEqual(
            {item["symbol"] for item in brief["new_candidates"]},
            {"TSM", "META", "ASML", "PLTR"},
        )

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_watchlist_workflow_independence(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            WATCHLIST=[
                monitor_entry("AAPL", category=CATEGORY_WATCHLIST, events=[research_change_event()]),
            ],
        )
        self.candidate_repo.get_all.return_value = [{
            "symbol": "AAPL",
            "research_status": "INCELEMEDE",
            "research_next_action": "Keep reviewing",
        }]
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["today_actions"][0]["symbol"], "AAPL")
        self.assertEqual(brief["watchlist_changes"], [])
        self.assertEqual(brief["open_research"][0]["symbol"], "AAPL")

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_stable_no_change_omitted_from_attention(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(ATTENTION=[])
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["attention_items"], [])

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_item_caps(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            ATTENTION=[monitor_entry(f"S{i}") for i in range(8)],
            NEW=[monitor_entry(f"N{i}", category=CATEGORY_NEW) for i in range(5)],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
            max_attention=5,
            max_new=3,
        )
        self.assertEqual(brief["today_actions"], [])
        self.assertLessEqual(len(brief["data_quality_updates"]), 3)
        self.assertLessEqual(len(brief["attention_items"]), 5)
        self.assertLessEqual(len(brief["new_candidates"]), 3)

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_attention_dedupes_new_and_watchlist(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            ATTENTION=[monitor_entry("NVDA", events=[research_change_event()])],
            NEW=[monitor_entry("NVDA", category=CATEGORY_NEW)],
            WATCHLIST=[monitor_entry("NVDA", category=CATEGORY_WATCHLIST)],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["today_actions"][0]["symbol"], "NVDA")
        self.assertEqual(brief["attention_items"], [])
        self.assertEqual(brief["new_candidates"], [])
        self.assertEqual(brief["watchlist_changes"], [])

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_mixed_research_action_shows_in_top3_not_data_quality_section(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            ATTENTION=[monitor_entry(
                "NVDA",
                events=[
                    research_change_event(),
                    {
                        "message": "Veri tamlığı %12 → %76",
                        "severity": "MEDIUM",
                        "field": "data_completeness",
                        "category": "COMPLETENESS",
                        "old": 12.0,
                        "new": 76.0,
                    },
                ],
            )],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["today_actions"][0]["symbol"], "NVDA")
        self.assertEqual(
            [item["symbol"] for item in brief["data_quality_updates"]],
            [],
        )

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_read_only_no_scanner_calls(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        with patch("services.scanner_v8_engine.ScannerV8Engine") as mock_engine:
            build_daily_brief(
                scan_repo=self.scan_repo,
                candidate_repo=self.candidate_repo,
                watchlist_repo=self.watchlist_repo,
            )
            mock_engine.assert_not_called()

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_batch_no_n_plus_one(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            ATTENTION=[monitor_entry("NVDA")],
        )
        build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.scan_repo.get_latest_scheduled_run.assert_called_once()
        mock_feed.assert_called_once()

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_window_boundary_uses_as_of(self, mock_feed) -> None:
        as_of = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
        mock_feed.return_value = self._feed()
        build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
            as_of=as_of,
            window_hours=24,
        )
        _, kwargs = mock_feed.call_args
        self.assertEqual(kwargs["since"], as_of - timedelta(hours=24))

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_latest_scheduled_older_than_24h_still_visible(self, mock_feed) -> None:
        mock_feed.return_value = self._feed()
        self.scan_repo.get_latest_scheduled_run.return_value = scheduled_run(
            universe_name="SCHEDULED · Daily · 2026-08-10",
            started_at="2026-08-10T03:00:00+00:00",
            completed_at="2026-08-10T03:05:00+00:00",
        )
        self.scan_repo.get_results_for_run.return_value = [
            {
                "symbol": f"S{i}",
                "status": "TAM VERİ",
                "decision": "ARAŞTIRMA ADAYI",
                "errors": [],
                "endpoint_status": {"fmp_profile": "OK"},
            }
            for i in range(13)
        ]
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
            as_of=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(brief["scheduled_run"]["status"], "success")

    def test_first_seen_semantics_via_monitor(self) -> None:
        timeline = [row("NEWCO", "2026-08-11T10:00:00+00:00", snapshot(symbol="NEWCO"))]
        entries = build_monitor_entries(
            timeline,
            snapshot_fn=snapshot_fn,
            pre_window_symbols=set(),
        )
        self.assertTrue(entries[0]["is_first_seen_in_window"])

    def test_legacy_history_preserved_in_monitor(self) -> None:
        timeline = [
            row("AAPL", "2026-08-10T10:00:00+00:00", {"symbol": "AAPL"}, "1"),
            row(
                "AAPL",
                "2026-08-11T10:00:00+00:00",
                snapshot(decision_label="ARAŞTIRMA ADAYI"),
                "2",
            ),
        ]
        entries = build_monitor_entries(
            timeline,
            snapshot_fn=lambda r: r.get("candidate_snapshot") or {},
            pre_window_symbols={"AAPL"},
        )
        self.assertFalse(entries[0]["is_first_seen_in_window"])

    def test_scheduled_status_helpers(self) -> None:
        self.assertEqual(resolve_scheduled_run_status(None), "missing")
        self.assertEqual(
            resolve_scheduled_run_status({"status": "COMPLETED", "error_count": 3}),
            "partial",
        )
        self.assertEqual(format_scheduled_run_status("partial"), "Kısmi")
        self.assertIn(
            "bazı veri kaynakları sınırlıydı",
            format_scheduled_run_detail("partial", {"scanned_symbols": 13}),
        )

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_data_quality_updates_on_completeness_only(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            ATTENTION=[monitor_entry("NVDA"), monitor_entry("AAPL")],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertEqual(brief["today_actions"], [])
        self.assertEqual(brief["summary_stats"]["research_change_count"], 0)
        self.assertEqual(brief["summary_stats"]["data_quality_change_count"], 2)
        self.assertEqual(len(brief["data_quality_updates"]), 2)
        self.assertIn("Veri tamlığı yeniden yükseldi", brief["data_quality_updates"][0]["summary"])

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_quiet_research_headline_with_data_quality_context(self, mock_feed) -> None:
        mock_feed.return_value = self._feed(
            ATTENTION=[monitor_entry("NVDA"), monitor_entry("AAPL"), monitor_entry("MSFT")],
        )
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        self.assertIn(
            "Bugün araştırma önceliğini değiştiren yeni bir gelişme yok.",
            brief["headline"],
        )
        self.assertIn("3 şirkette veri kalitesi güncellemesi var.", brief["headline"])

    def test_monitor_category_unchanged_for_completeness(self) -> None:
        from services.research_history_service import assign_category_and_badges

        category, _ = assign_category_and_badges(monitor_entry("NVDA"))
        self.assertEqual(category, CATEGORY_ATTENTION)

    def test_dashboard_compile(self) -> None:
        py_compile.compile("pages/1_Dashboard.py", doraise=True)

    def test_research_monitor_compile(self) -> None:
        py_compile.compile("pages/3_Research_Monitor.py", doraise=True)

    def test_company_report_compile(self) -> None:
        py_compile.compile("pages/4_Company_Report.py", doraise=True)

    def test_dashboard_uses_daily_brief(self) -> None:
        with open("pages/5_Firsatlar.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("build_daily_brief(", source)
        self.assertNotIn("build_priority_teaser_from_monitor", source)
        ui = Path("services/opportunity_center_presentation.py").read_text(encoding="utf-8")
        self.assertIn("data_quality_updates", ui)


if __name__ == "__main__":
    unittest.main()
