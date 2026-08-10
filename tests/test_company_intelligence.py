import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import py_compile
from pathlib import Path

from services.company_intelligence_service import (
    build_company_intelligence,
    build_data_quality_context,
    build_timeline_items,
)
from services.research_monitor_service import build_monitor_feed
from tests.test_research_history import row, snapshot, snapshot_fn


def candidate(**overrides):
    base = {
        "id": "cand-1",
        "symbol": "NVDA",
        "company_name": "NVIDIA",
        "nabi_score": 82.0,
        "decision_label": "ARAŞTIRMA ADAYI",
        "opportunity_score": 74.0,
        "conviction_score": 72.0,
        "research_confidence": 80.0,
        "freshness_status": "FRESH",
        "data_completeness": 90.0,
    }
    base.update(overrides)
    return base


class CompanyIntelligenceServiceTests(unittest.TestCase):
    def _scan_repo(self, rows, pre_window=None):
        scan_repo = MagicMock()
        since = datetime.now(timezone.utc) - timedelta(days=7)
        scan_repo.get_completed_runs_since.return_value = [{"id": "run-1"}]
        scan_repo.get_results_for_runs.return_value = rows
        scan_repo.get_all_completed_run_ids_before.return_value = ["old-run"]
        scan_repo.get_symbols_with_results_before.return_value = pre_window or set()
        scan_repo.row_to_snapshot.side_effect = snapshot_fn
        return scan_repo

    def test_no_history(self) -> None:
        result = build_company_intelligence(
            candidate(),
            scan_repo=self._scan_repo([]),
        )
        self.assertEqual(result["history_summary"]["history_count"], 0)
        self.assertEqual(result["history_summary"]["events"], [])
        self.assertIn("priority", result)

    def test_single_previous_snapshot(self) -> None:
        rows = [row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(), "1")]
        result = build_company_intelligence(
            candidate(),
            scan_repo=self._scan_repo(rows),
        )
        self.assertEqual(result["history_summary"]["history_count"], 1)
        self.assertEqual(result["history_summary"]["pair_count"], 0)

    def test_multi_scan_consecutive_history(self) -> None:
        rows = [
            row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(data_completeness=12.0), "1"),
            row("NVDA", "2026-08-10T11:00:00+00:00", snapshot(data_completeness=96.0), "2"),
            row("NVDA", "2026-08-10T12:00:00+00:00", snapshot(data_completeness=76.0), "3"),
        ]
        result = build_company_intelligence(
            candidate(),
            scan_repo=self._scan_repo(rows),
        )
        self.assertEqual(result["history_summary"]["pair_count"], 2)
        self.assertGreater(result["history_summary"]["window_change_score"], 0)

    def test_meaningful_change_shown(self) -> None:
        rows = [
            row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(decision_label="İZLE"), "1"),
            row("NVDA", "2026-08-10T11:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "2"),
        ]
        result = build_company_intelligence(
            candidate(decision_label="ARAŞTIRMA ADAYI"),
            scan_repo=self._scan_repo(rows),
        )
        self.assertTrue(result["history_summary"]["events"])

    def test_score_zero_noise_not_shown(self) -> None:
        rows = [
            row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(nabi_score=70.0), "1"),
            row("NVDA", "2026-08-10T11:00:00+00:00", snapshot(nabi_score=71.0), "2"),
        ]
        result = build_company_intelligence(
            candidate(),
            scan_repo=self._scan_repo(rows),
        )
        self.assertEqual(result["history_summary"]["events"], [])

    def test_legacy_sparse_badge(self) -> None:
        from services.scan_snapshot import sparse_snapshot_from_row

        rows = [
            row("NVDA", "2026-08-10T10:00:00+00:00", sparse_snapshot_from_row({
                "symbol": "NVDA",
                "status": "KISMİ VERİ",
                "data_completeness": 12.0,
                "endpoint_status": {},
            }), "1"),
            row("NVDA", "2026-08-10T11:00:00+00:00", snapshot(data_completeness=96.0), "2"),
        ]
        result = build_company_intelligence(
            candidate(),
            scan_repo=self._scan_repo(rows),
        )
        self.assertTrue(result["has_legacy_history"])
        self.assertIn("LEGACY_HISTORY", result["badges"])

    def test_first_seen_new_badge(self) -> None:
        rows = [row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(), "1")]
        result = build_company_intelligence(
            candidate(),
            scan_repo=self._scan_repo(rows, pre_window=set()),
        )
        self.assertTrue(result["is_first_seen_in_window"])
        self.assertIn("NEW", result["badges"])

    def test_stale_issuer(self) -> None:
        rows = [row("SONY", "2026-08-10T10:00:00+00:00", snapshot(freshness_status="STALE"), "1")]
        result = build_company_intelligence(
            candidate(symbol="SONY", freshness_status="STALE"),
            scan_repo=self._scan_repo(rows),
        )
        self.assertIn("STALE", result["badges"])

    def test_aging_issuer(self) -> None:
        rows = [row("TM", "2026-08-10T10:00:00+00:00", snapshot(freshness_status="AGING"), "1")]
        result = build_company_intelligence(
            candidate(symbol="TM", freshness_status="AGING"),
            scan_repo=self._scan_repo(rows),
        )
        self.assertIn("AGING", result["badges"])

    def test_fmp_unavailable_not_fundamental(self) -> None:
        rows = [
            row("API", "2026-08-10T10:00:00+00:00", snapshot(pe_ratio=20.0, pe_source="quote"), "1"),
            row("API", "2026-08-10T11:00:00+00:00", snapshot(pe_ratio=None, pe_source="unavailable"), "2"),
        ]
        result = build_company_intelligence(
            candidate(symbol="API"),
            scan_repo=self._scan_repo(rows),
        )
        reasons = " ".join(result["priority"]["reasons"])
        self.assertNotIn("değerleme", reasons.lower())
        availability = [
            event for event in result["history_summary"]["events"]
            if event.get("category") == "AVAILABILITY"
        ]
        self.assertTrue(availability)

    def test_watchlist_membership_priority_reason(self) -> None:
        rows = [
            row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(decision_label="İZLE"), "1"),
            row("NVDA", "2026-08-10T11:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "2"),
        ]
        result = build_company_intelligence(
            candidate(),
            scan_repo=self._scan_repo(rows),
            is_watchlisted=True,
        )
        self.assertIn(
            "Kullanıcı izleme listesinde",
            result["priority"]["reasons"],
        )

    def test_watchlist_note_preserved(self) -> None:
        result = build_company_intelligence(
            candidate(),
            scan_repo=self._scan_repo([]),
            is_watchlisted=True,
            watchlist_note="Takip notu",
        )
        self.assertEqual(result["watchlist_note"], "Takip notu")

    def test_stable_high_nabi_not_auto_high_priority(self) -> None:
        rows = [row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(decision_label="İZLE"), "1")]
        result = build_company_intelligence(
            candidate(
                nabi_score=92.0,
                decision_label="İZLE",
                opportunity_score=50.0,
                conviction_score=55.0,
            ),
            scan_repo=self._scan_repo(rows),
        )
        self.assertLess(result["priority"]["priority_score"], 70)

    def test_priority_deterministic(self) -> None:
        rows = [
            row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(decision_label="İZLE"), "1"),
            row("NVDA", "2026-08-10T11:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "2"),
        ]
        scan_repo = self._scan_repo(rows)
        first = build_company_intelligence(candidate(), scan_repo=scan_repo)
        second = build_company_intelligence(candidate(), scan_repo=scan_repo)
        self.assertEqual(first["priority"], second["priority"])

    def test_monitor_semantics_alignment(self) -> None:
        rows = [
            row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(data_completeness=12.0), "1"),
            row("NVDA", "2026-08-10T11:00:00+00:00", snapshot(data_completeness=96.0), "2"),
            row("NVDA", "2026-08-10T12:00:00+00:00", snapshot(data_completeness=76.0), "3"),
        ]
        scan_repo = self._scan_repo(rows, pre_window=set())
        since = datetime.now(timezone.utc) - timedelta(days=7)
        company = build_company_intelligence(
            candidate(),
            scan_repo=scan_repo,
            since=since,
        )
        feed = build_monitor_feed(
            scan_repo=scan_repo,
            candidates=[candidate()],
            watched_candidate_ids=set(),
            since=since,
        )
        monitor_entry = next(item for item in feed["entries"] if item["symbol"] == "NVDA")
        self.assertEqual(
            company["priority"]["priority_score"],
            monitor_entry["research_priority"]["priority_score"],
        )
        self.assertEqual(
            company["history_summary"]["window_change_score"],
            monitor_entry["window_change_score"],
        )

    def test_timeline_deduplicates_messages(self) -> None:
        events = [
            {"occurred_at": "2026-08-10T11:00:00+00:00", "message": "Aynı mesaj", "severity": "MEDIUM", "pair_index": 1},
            {"occurred_at": "2026-08-10T12:00:00+00:00", "message": "Aynı mesaj", "severity": "MEDIUM", "pair_index": 2},
            {"occurred_at": "2026-08-10T13:00:00+00:00", "message": "Başka mesaj", "severity": "HIGH", "pair_index": 3},
        ]
        timeline = build_timeline_items(events)
        messages = [item["message"] for item in timeline]
        self.assertEqual(len(messages), len(set(messages)))

    def test_data_quality_legacy_note(self) -> None:
        context = build_data_quality_context(
            candidate(),
            {
                "has_legacy_history": True,
                "is_first_seen_in_window": False,
                "events": [],
            },
        )
        self.assertTrue(
            any("daha az alan kaydedildiği" in note for note in context["notes"])
        )


class CompanyReportImportSmokeTests(unittest.TestCase):
    def test_company_report_compile(self) -> None:
        py_compile.compile("pages/4_Company_Report.py", doraise=True)

    def test_company_intelligence_import(self) -> None:
        from services.company_intelligence_service import build_company_intelligence

        self.assertTrue(callable(build_company_intelligence))

    def test_dashboard_regression_import(self) -> None:
        from services.research_monitor_service import build_priority_teaser_from_monitor

        self.assertTrue(callable(build_priority_teaser_from_monitor))

    def test_company_report_imports_intelligence(self) -> None:
        source = Path("pages/4_Company_Report.py").read_text(encoding="utf-8")
        self.assertIn("build_company_intelligence", source)
        self.assertIn("Araştırma Önceliği", source)
        self.assertIn("Scanner Kararı", source)


class WatchlistActiveEntryTests(unittest.TestCase):
    def test_get_active_entry(self) -> None:
        from repositories.watchlist_repository import WatchlistRepository

        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.eq.return_value = query
        query.in_.return_value = query
        query.limit.return_value = query
        query.execute.return_value = MagicMock(data=[{"notes": "Takip", "status": "AKTİF"}])

        repo = WatchlistRepository(client)
        entry = repo.get_active_entry("cand-1")
        self.assertEqual(entry["notes"], "Takip")


if __name__ == "__main__":
    unittest.main()
