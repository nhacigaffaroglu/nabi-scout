import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from repositories.scan_repository import ScanRepository
from services.change_detection_engine import detect_changes
from services.research_history_service import (
    CATEGORY_ATTENTION,
    CATEGORY_DATA_ISSUES,
    CATEGORY_NEW,
    CATEGORY_NONE,
    CATEGORY_WATCHLIST,
    aggregate_monitor_events,
    assign_category_and_badges,
    build_monitor_entries,
    build_symbol_monitor_entry,
    compute_consecutive_pair_changes,
    group_entries_by_category,
    sort_monitor_entries,
    top_priority_entries,
)
from services.research_monitor_service import build_monitor_feed
from services.scan_snapshot import sparse_snapshot_from_row


def snapshot(**overrides):
    base = {
        "symbol": "TEST",
        "status": "TAM VERİ",
        "excluded": False,
        "nabi_score": 70.0,
        "decision_label": "İZLE",
        "opportunity_score": 55.0,
        "conviction_score": 62.0,
        "research_confidence": 80.0,
        "freshness_status": "FRESH",
        "data_completeness": 90.0,
        "_comparison_source": "snapshot",
    }
    base.update(overrides)
    return base


def row(symbol, created_at, snap, row_id="1"):
    return {
        "id": row_id,
        "symbol": symbol,
        "scan_run_id": f"run-{row_id}",
        "created_at": created_at,
        "candidate_snapshot": snap,
        "status": snap.get("status"),
        "nabi_score": snap.get("nabi_score"),
        "data_completeness": snap.get("data_completeness"),
        "endpoint_status": {},
    }


def snapshot_fn(scan_row):
    snap = scan_row.get("candidate_snapshot")
    if isinstance(snap, dict) and snap:
        return dict(snap)
    return sparse_snapshot_from_row(scan_row)


class ResearchHistoryServiceTests(unittest.TestCase):
    def test_no_history(self) -> None:
        entries = build_monitor_entries([], snapshot_fn=snapshot_fn)
        self.assertEqual(entries, [])

    def test_two_snapshots_one_pair(self) -> None:
        timeline = [
            row("AAPL", "2026-08-10T10:00:00+00:00", snapshot(decision_label="İZLE"), "1"),
            row("AAPL", "2026-08-10T11:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "2"),
        ]
        entry = build_symbol_monitor_entry(
            "AAPL",
            timeline,
            snapshot_fn=snapshot_fn,
            candidate={"symbol": "AAPL", "decision_label": "ARAŞTIRMA ADAYI"},
        )
        self.assertEqual(entry["pair_count"], 1)
        self.assertEqual(entry["history_count"], 2)

    def test_three_plus_consecutive_pairs(self) -> None:
        timeline = [
            row("MSFT", "2026-08-10T10:00:00+00:00", snapshot(data_completeness=12.0), "1"),
            row("MSFT", "2026-08-10T11:00:00+00:00", snapshot(data_completeness=96.0), "2"),
            row("MSFT", "2026-08-10T12:00:00+00:00", snapshot(data_completeness=76.0), "3"),
            row("MSFT", "2026-08-10T13:00:00+00:00", snapshot(data_completeness=76.0), "4"),
        ]
        pairs = compute_consecutive_pair_changes(timeline, snapshot_fn)
        self.assertEqual(len(pairs), 3)

    def test_direct_first_last_not_used(self) -> None:
        timeline = [
            row("AAPL", "2026-08-10T10:00:00+00:00", snapshot(decision_label="İZLE"), "1"),
            row("AAPL", "2026-08-10T11:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "2"),
            row("AAPL", "2026-08-10T12:00:00+00:00", snapshot(decision_label="YÜKSEK ÖNCELİKLİ ARAŞTIRMA ADAYI"), "3"),
        ]
        pairs = compute_consecutive_pair_changes(timeline, snapshot_fn)
        direct = detect_changes(
            snapshot_fn(timeline[0]),
            snapshot_fn(timeline[-1]),
        )
        pair_scores = [int(pair["change"]["change_score"]) for pair in pairs]
        _, window_score, _, _ = aggregate_monitor_events(pairs)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(window_score, max(pair_scores))
        self.assertNotEqual(sum(pair_scores), direct.get("change_score"))

    def test_high_decision_preserved(self) -> None:
        timeline = [
            row("NVDA", "2026-08-10T10:00:00+00:00", snapshot(decision_label="İZLE"), "1"),
            row("NVDA", "2026-08-10T11:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "2"),
        ]
        entry = build_symbol_monitor_entry("NVDA", timeline, snapshot_fn=snapshot_fn)
        self.assertTrue(any(event.get("severity") == "HIGH" for event in entry["events"]))

    def test_multiple_low_handling(self) -> None:
        timeline = [
            row("AAA", "2026-08-10T10:00:00+00:00", snapshot(nabi_score=70.0), "1"),
            row("AAA", "2026-08-10T11:00:00+00:00", snapshot(nabi_score=75.0), "2"),
            row("AAA", "2026-08-10T12:00:00+00:00", snapshot(nabi_score=80.0), "3"),
        ]
        pairs = compute_consecutive_pair_changes(timeline, snapshot_fn)
        events, _, _, _ = aggregate_monitor_events(pairs)
        self.assertGreaterEqual(len(events), 1)

    def test_duplicate_semantic_dedupe(self) -> None:
        events = [
            {
                "field": "nabi_score",
                "category": "SCORE",
                "severity": "MEDIUM",
                "message": "NABI 70 → 75",
                "occurred_at": "2026-08-10T11:00:00+00:00",
                "pair_index": 1,
            },
            {
                "field": "nabi_score",
                "category": "SCORE",
                "severity": "MEDIUM",
                "message": "NABI 75 → 80",
                "occurred_at": "2026-08-10T12:00:00+00:00",
                "pair_index": 2,
            },
        ]
        deduped, _, _, _ = aggregate_monitor_events([
            {"pair_index": 1, "occurred_at": "t1", "change": {"change_score": 15, "changes": [events[0]]}, "previous_snapshot": {}, "current_snapshot": {}},
            {"pair_index": 2, "occurred_at": "t2", "change": {"change_score": 15, "changes": [events[1]]}, "previous_snapshot": {}, "current_snapshot": {}},
        ])
        score_keys = [_semantic(event) for event in deduped]
        self.assertEqual(len(score_keys), len(set(score_keys)))

    def test_pe_flapping_collapse(self) -> None:
        timeline = [
            row("PE1", "2026-08-10T10:00:00+00:00", snapshot(pe_ratio=20.0, pe_source="quote"), "1"),
            row("PE1", "2026-08-10T11:00:00+00:00", snapshot(pe_ratio=None, pe_source="unavailable"), "2"),
            row("PE1", "2026-08-10T12:00:00+00:00", snapshot(pe_ratio=21.0, pe_source="quote"), "3"),
        ]
        pairs = compute_consecutive_pair_changes(timeline, snapshot_fn)
        events, _, _, _ = aggregate_monitor_events(pairs)
        availability = [event for event in events if event.get("category") == "AVAILABILITY"]
        valuation = [event for event in events if event.get("category") == "VALUATION"]
        self.assertLessEqual(len(availability), 1)
        self.assertEqual(valuation, [])

    def test_pe_unavailable_not_fundamental(self) -> None:
        timeline = [
            row("PE2", "2026-08-10T10:00:00+00:00", snapshot(pe_ratio=20.0, pe_source="quote"), "1"),
            row("PE2", "2026-08-10T11:00:00+00:00", snapshot(pe_ratio=None, pe_source="unavailable"), "2"),
        ]
        entry = build_symbol_monitor_entry("PE2", timeline, snapshot_fn=snapshot_fn)
        reasons = " ".join(entry["research_priority"]["reasons"])
        self.assertNotIn("değerleme", reasons.lower())

    def test_freshness_flapping_suppressed(self) -> None:
        timeline = [
            row("FR1", "2026-08-10T10:00:00+00:00", snapshot(freshness_status="FRESH"), "1"),
            row("FR1", "2026-08-10T11:00:00+00:00", snapshot(freshness_status="AGING"), "2"),
            row("FR1", "2026-08-10T12:00:00+00:00", snapshot(freshness_status="FRESH"), "3"),
        ]
        pairs = compute_consecutive_pair_changes(timeline, snapshot_fn)
        events, _, _, _ = aggregate_monitor_events(pairs)
        freshness = [event for event in events if event.get("field") == "freshness_status"]
        self.assertEqual(freshness, [])

    def test_net_stale_retained(self) -> None:
        timeline = [
            row("FR2", "2026-08-10T10:00:00+00:00", snapshot(freshness_status="FRESH"), "1"),
            row("FR2", "2026-08-10T11:00:00+00:00", snapshot(freshness_status="AGING"), "2"),
            row("FR2", "2026-08-10T12:00:00+00:00", snapshot(freshness_status="STALE"), "3"),
        ]
        entry = build_symbol_monitor_entry(
            "FR2",
            timeline,
            snapshot_fn=snapshot_fn,
            candidate={"symbol": "FR2", "freshness_status": "STALE"},
        )
        self.assertTrue(
            any(event.get("field") == "freshness_status" for event in entry["events"])
        )

    def test_completeness_flapping_suppress(self) -> None:
        timeline = [
            row("CP1", "2026-08-10T10:00:00+00:00", snapshot(data_completeness=75.0), "1"),
            row("CP1", "2026-08-10T11:00:00+00:00", snapshot(data_completeness=84.0), "2"),
            row("CP1", "2026-08-10T12:00:00+00:00", snapshot(data_completeness=76.0), "3"),
        ]
        pairs = compute_consecutive_pair_changes(timeline, snapshot_fn)
        events, _, _, _ = aggregate_monitor_events(pairs)
        completeness = [event for event in events if event.get("field") == "data_completeness"]
        self.assertEqual(completeness, [])

    def test_completeness_net_threshold_retained(self) -> None:
        timeline = [
            row("CP2", "2026-08-10T10:00:00+00:00", snapshot(data_completeness=12.0), "1"),
            row("CP2", "2026-08-10T11:00:00+00:00", snapshot(data_completeness=96.0), "2"),
        ]
        entry = build_symbol_monitor_entry("CP2", timeline, snapshot_fn=snapshot_fn)
        self.assertTrue(
            any("Veri tamlığı" in event.get("message", "") for event in entry["events"])
        )

    def test_first_seen_without_pre_window_history(self) -> None:
        timeline = [row("NEW1", "2026-08-10T10:00:00+00:00", snapshot(), "1")]
        entries = build_monitor_entries(
            timeline,
            snapshot_fn=snapshot_fn,
            pre_window_symbols=set(),
        )
        self.assertTrue(entries[0]["is_first_seen_in_window"])

    def test_pre_window_history_not_first_seen(self) -> None:
        timeline = [row("OLD1", "2026-08-10T10:00:00+00:00", snapshot(), "1")]
        entries = build_monitor_entries(
            timeline,
            snapshot_fn=snapshot_fn,
            pre_window_symbols={"OLD1"},
        )
        self.assertFalse(entries[0]["is_first_seen_in_window"])

    def test_legacy_sparse_to_snapshot(self) -> None:
        legacy = sparse_snapshot_from_row({
            "symbol": "AAPL",
            "status": "KISMİ VERİ",
            "data_completeness": 12.0,
            "endpoint_status": {},
        })
        timeline = [
            row("AAPL", "2026-08-10T10:00:00+00:00", legacy, "1"),
            row("AAPL", "2026-08-10T11:00:00+00:00", snapshot(data_completeness=96.0), "2"),
        ]
        entry = build_symbol_monitor_entry("AAPL", timeline, snapshot_fn=snapshot_fn)
        self.assertTrue(entry["has_legacy_history"])
        self.assertFalse(
            any("decision_label" == event.get("field") for event in entry["events"])
        )

    def test_legacy_badge(self) -> None:
        timeline = [
            row("LEG", "2026-08-10T10:00:00+00:00", sparse_snapshot_from_row({
                "symbol": "LEG",
                "status": "KISMİ VERİ",
                "data_completeness": 12.0,
                "endpoint_status": {},
            }), "1"),
            row("LEG", "2026-08-10T11:00:00+00:00", snapshot(data_completeness=96.0), "2"),
        ]
        entry = build_symbol_monitor_entry("LEG", timeline, snapshot_fn=snapshot_fn)
        _, badges = assign_category_and_badges(entry)
        self.assertIn("LEGACY_HISTORY", badges)

    def test_watchlist_boost(self) -> None:
        timeline = [
            row("WL", "2026-08-10T10:00:00+00:00", snapshot(decision_label="İZLE"), "1"),
            row("WL", "2026-08-10T11:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "2"),
        ]
        entry = build_symbol_monitor_entry(
            "WL",
            timeline,
            snapshot_fn=snapshot_fn,
            is_watchlisted=True,
        )
        self.assertEqual(
            entry["research_priority"]["components"].get("user_watchlist"),
            10.0,
        )

    def test_stale_issuer_category(self) -> None:
        timeline = [row("ST", "2026-08-10T10:00:00+00:00", snapshot(freshness_status="STALE"), "1")]
        entry = build_symbol_monitor_entry(
            "ST",
            timeline,
            snapshot_fn=snapshot_fn,
            candidate={"symbol": "ST", "freshness_status": "STALE"},
        )
        category, badges = assign_category_and_badges(entry)
        self.assertIn(category, {CATEGORY_DATA_ISSUES, CATEGORY_NONE})
        self.assertIn("DATA_ISSUE", badges)

    def test_foreign_issuer_graceful(self) -> None:
        timeline = [
            row("TSM", "2026-08-10T10:00:00+00:00", snapshot(
                financial_taxonomy="ifrs-full",
                financial_currency="TWD",
            ), "1"),
        ]
        entry = build_symbol_monitor_entry("TSM", timeline, snapshot_fn=snapshot_fn)
        self.assertIn("research_priority", entry)

    def test_same_symbol_multiple_universe_merge(self) -> None:
        rows = [
            row("AAPL", "2026-08-10T10:00:00+00:00", snapshot(nabi_score=70.0), "1"),
            row("AAPL", "2026-08-10T11:00:00+00:00", snapshot(nabi_score=75.0), "2"),
            row("AAPL", "2026-08-10T12:00:00+00:00", snapshot(nabi_score=80.0), "3"),
        ]
        entries = build_monitor_entries(rows, snapshot_fn=snapshot_fn)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["history_count"], 3)

    def test_window_change_score_max_not_sum(self) -> None:
        timeline = [
            row("SC", "2026-08-10T10:00:00+00:00", snapshot(data_completeness=12.0), "1"),
            row("SC", "2026-08-10T11:00:00+00:00", snapshot(data_completeness=96.0), "2"),
            row("SC", "2026-08-10T12:00:00+00:00", snapshot(data_completeness=76.0), "3"),
        ]
        entry = build_symbol_monitor_entry("SC", timeline, snapshot_fn=snapshot_fn)
        self.assertLessEqual(entry["window_change_score"], 30)

    def test_deterministic_ordering(self) -> None:
        entries = [
            {
                "symbol": "BBB",
                "primary_category": CATEGORY_ATTENTION,
                "research_priority": {"priority_score": 50.0},
                "events": [],
                "window_change_score": 10,
                "latest_scan_at": "2026-08-10T12:00:00+00:00",
            },
            {
                "symbol": "AAA",
                "primary_category": CATEGORY_ATTENTION,
                "research_priority": {"priority_score": 50.0},
                "events": [{"severity": "HIGH"}],
                "window_change_score": 10,
                "latest_scan_at": "2026-08-10T12:00:00+00:00",
            },
        ]
        ordered = sort_monitor_entries(entries)
        self.assertEqual(ordered[0]["symbol"], "AAA")

    def test_primary_category_no_duplicate(self) -> None:
        entries = [
            {
                "symbol": "DUP",
                "primary_category": CATEGORY_ATTENTION,
                "research_priority": {"priority_score": 60.0},
                "events": [{"severity": "HIGH", "field": "decision_label"}],
                "window_change_score": 30,
                "meaningful_change_count": 1,
                "is_watchlisted": True,
                "is_first_seen_in_window": True,
                "candidate": {"freshness_status": "STALE"},
                "latest_snapshot": {"freshness_status": "STALE"},
                "has_legacy_history": True,
            }
        ]
        grouped = group_entries_by_category(entries)
        appearances = sum(
            1
            for category_entries in grouped.values()
            for entry in category_entries
            if entry["symbol"] == "DUP"
        )
        self.assertEqual(appearances, 1)

    def test_badges(self) -> None:
        entry = {
            "events": [],
            "window_change_score": 0,
            "meaningful_change_count": 0,
            "is_watchlisted": True,
            "is_first_seen_in_window": True,
            "has_legacy_history": True,
            "candidate": {"freshness_status": "STALE"},
            "latest_snapshot": {"freshness_status": "STALE"},
        }
        _, badges = assign_category_and_badges(entry)
        self.assertIn("WATCHLIST", badges)
        self.assertIn("NEW", badges)
        self.assertIn("LEGACY_HISTORY", badges)

    def test_api_outage_reason_classification(self) -> None:
        timeline = [
            row("API", "2026-08-10T10:00:00+00:00", snapshot(pe_ratio=20.0, pe_source="quote"), "1"),
            row("API", "2026-08-10T11:00:00+00:00", snapshot(pe_ratio=None, pe_source="unavailable"), "2"),
        ]
        entry = build_symbol_monitor_entry("API", timeline, snapshot_fn=snapshot_fn)
        category, _ = assign_category_and_badges(entry)
        self.assertIn(category, {CATEGORY_DATA_ISSUES, CATEGORY_ATTENTION, CATEGORY_NONE})

    def test_current_candidate_missing_graceful(self) -> None:
        timeline = [row("MISS", "2026-08-10T10:00:00+00:00", snapshot(decision_label="İZLE"), "1")]
        entry = build_symbol_monitor_entry("MISS", timeline, snapshot_fn=snapshot_fn, candidate=None)
        self.assertIsNotNone(entry["research_priority"])


def _semantic(event):
    return f"{event.get('category')}:{event.get('field')}"


class ScanRepositoryBatchTests(unittest.TestCase):
    def test_get_completed_runs_since_universe_filter(self) -> None:
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.eq.return_value = query
        query.gte.return_value = query
        query.order.return_value = query
        query.execute.return_value = MagicMock(data=[
            {"id": "1", "universe_name": "Teknoloji 10 [1-3]", "status": "COMPLETED", "completed_at": "2026-08-10T10:00:00+00:00"},
            {"id": "2", "universe_name": "Katılım ETF 3 [1-3]", "status": "COMPLETED", "completed_at": "2026-08-10T11:00:00+00:00"},
        ])
        repo = ScanRepository(client)
        runs = repo.get_completed_runs_since(
            datetime(2026, 8, 9, tzinfo=timezone.utc),
            "Teknoloji 10",
        )
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["id"], "1")

    def test_get_completed_runs_since_exclude_manual(self) -> None:
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.eq.return_value = query
        query.gte.return_value = query
        query.order.return_value = query
        query.execute.return_value = MagicMock(data=[
            {"id": "1", "universe_name": "SCHEDULED · Daily · 2026-08-11", "status": "COMPLETED", "completed_at": "2026-08-10T10:00:00+00:00"},
            {"id": "2", "universe_name": "MANUAL", "status": "COMPLETED", "completed_at": "2026-08-10T11:00:00+00:00"},
        ])
        repo = ScanRepository(client)
        runs = repo.get_completed_runs_since(
            datetime(2026, 8, 9, tzinfo=timezone.utc),
            exclude_manual=True,
        )
        self.assertEqual([run["id"] for run in runs], ["1"])

    def test_get_results_for_runs_batch(self) -> None:
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.in_.return_value = query
        query.order.return_value = query
        query.execute.return_value = MagicMock(data=[
            {"id": "a", "symbol": "AAPL", "scan_run_id": "1", "created_at": "2026-08-10T10:00:00+00:00", "candidate_snapshot": snapshot()},
            {"id": "b", "symbol": "AAPL", "scan_run_id": "2", "created_at": "2026-08-10T11:00:00+00:00", "candidate_snapshot": snapshot()},
        ])
        repo = ScanRepository(client)
        rows = repo.get_results_for_runs(["1", "2"])
        self.assertEqual(len(rows), 2)
        table.select.assert_called_once()

    def test_build_monitor_feed_no_n_plus_one(self) -> None:
        scan_repo = MagicMock()
        since = datetime.now(timezone.utc) - timedelta(days=7)
        scan_repo.get_completed_runs_since.return_value = [{"id": "run-1"}]
        scan_repo.get_results_for_runs.return_value = [
            row("AAPL", "2026-08-10T10:00:00+00:00", snapshot(), "1"),
            row("AAPL", "2026-08-10T11:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "2"),
        ]
        scan_repo.get_all_completed_run_ids_before.return_value = []
        scan_repo.get_symbols_with_results_before.return_value = set()
        scan_repo.row_to_snapshot.side_effect = snapshot_fn

        feed = build_monitor_feed(
            scan_repo=scan_repo,
            candidates=[{"symbol": "AAPL", "decision_label": "ARAŞTIRMA ADAYI"}],
            since=since,
        )
        scan_repo.get_completed_runs_since.assert_called_once()
        scan_repo.get_results_for_runs.assert_called_once()
        scan_repo.get_symbols_with_results_before.assert_called_once()
        call_kwargs = scan_repo.get_symbols_with_results_before.call_args.kwargs
        self.assertEqual(call_kwargs.get("run_ids"), [])
        self.assertGreaterEqual(len(feed["entries"]), 1)

    def test_get_symbols_with_results_before_empty_run_ids(self) -> None:
        repo = ScanRepository(MagicMock())
        result = repo.get_symbols_with_results_before(
            ["AAPL"],
            datetime(2026, 8, 10, tzinfo=timezone.utc),
            run_ids=[],
        )
        self.assertEqual(result, set())


class FirstSeenSemanticsTests(unittest.TestCase):
    def test_pre_window_completed_history_not_first_seen(self) -> None:
        since = datetime(2026, 8, 10, 10, 0, 0, tzinfo=timezone.utc)
        timeline = [
            row("AAPL", "2026-08-10T11:00:00+00:00", snapshot(), "1"),
        ]
        entries = build_monitor_entries(
            timeline,
            snapshot_fn=snapshot_fn,
            pre_window_symbols={"AAPL"},
        )
        self.assertFalse(entries[0]["is_first_seen_in_window"])

    def test_truly_first_ever_scan_inside_window(self) -> None:
        timeline = [
            row("NEWCO", "2026-08-10T11:00:00+00:00", snapshot(), "1"),
        ]
        entries = build_monitor_entries(
            timeline,
            snapshot_fn=snapshot_fn,
            pre_window_symbols=set(),
        )
        self.assertTrue(entries[0]["is_first_seen_in_window"])

    def test_pre_window_non_completed_run_ignored_via_run_ids(self) -> None:
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.in_.return_value = query
        query.lt.return_value = query
        query.execute.return_value = MagicMock(data=[])

        repo = ScanRepository(client)
        completed_run_ids = ["completed-run-1"]
        found = repo.get_symbols_with_results_before(
            ["AAPL"],
            datetime(2026, 8, 10, tzinfo=timezone.utc),
            run_ids=completed_run_ids,
        )
        self.assertEqual(found, set())
        query.in_.assert_any_call("scan_run_id", completed_run_ids)

    def test_all_universe_pre_window_other_universe_false(self) -> None:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        scan_repo = MagicMock()
        scan_repo.get_completed_runs_since.return_value = [{"id": "run-window"}]
        scan_repo.get_results_for_runs.return_value = [
            row("AAPL", "2026-08-10T11:00:00+00:00", snapshot(decision_label="İZLE"), "w1"),
            row("AAPL", "2026-08-10T12:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "w2"),
        ]
        scan_repo.get_all_completed_run_ids_before.return_value = ["run-old-other"]
        scan_repo.get_symbols_with_results_before.return_value = {"AAPL"}
        scan_repo.row_to_snapshot.side_effect = snapshot_fn

        feed = build_monitor_feed(
            scan_repo=scan_repo,
            candidates=[{"symbol": "AAPL", "decision_label": "ARAŞTIRMA ADAYI"}],
            since=since,
            universe_name=None,
        )
        aapl = next(entry for entry in feed["entries"] if entry["symbol"] == "AAPL")
        self.assertFalse(aapl["is_first_seen_in_window"])

    def test_universe_filter_empty_pre_window_run_ids(self) -> None:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        scan_repo = MagicMock()
        scan_repo.get_completed_runs_since.return_value = [{"id": "run-window"}]
        scan_repo.get_results_for_runs.return_value = [
            row("AAPL", "2026-08-10T12:00:00+00:00", snapshot(), "w1"),
        ]
        scan_repo.get_all_completed_run_ids_before.return_value = []
        scan_repo.get_symbols_with_results_before.return_value = set()
        scan_repo.row_to_snapshot.side_effect = snapshot_fn

        feed = build_monitor_feed(
            scan_repo=scan_repo,
            candidates=[{"symbol": "AAPL"}],
            since=since,
            universe_name="Teknoloji 10",
        )
        scan_repo.get_symbols_with_results_before.assert_called_once()
        self.assertEqual(
            scan_repo.get_symbols_with_results_before.call_args.kwargs["run_ids"],
            [],
        )
        self.assertTrue(feed["entries"][0]["is_first_seen_in_window"])

    def test_universe_filter_pre_window_same_universe_false(self) -> None:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        scan_repo = MagicMock()
        scan_repo.get_completed_runs_since.return_value = [{"id": "run-window"}]
        scan_repo.get_results_for_runs.return_value = [
            row("AAPL", "2026-08-10T11:00:00+00:00", snapshot(decision_label="İZLE"), "w1"),
            row("AAPL", "2026-08-10T12:00:00+00:00", snapshot(decision_label="ARAŞTIRMA ADAYI"), "w2"),
        ]
        scan_repo.get_all_completed_run_ids_before.return_value = ["run-old-tech"]
        scan_repo.get_symbols_with_results_before.return_value = {"AAPL"}
        scan_repo.row_to_snapshot.side_effect = snapshot_fn

        feed = build_monitor_feed(
            scan_repo=scan_repo,
            candidates=[{"symbol": "AAPL", "decision_label": "ARAŞTIRMA ADAYI"}],
            since=since,
            universe_name="Teknoloji 10",
        )
        aapl = next(entry for entry in feed["entries"] if entry["symbol"] == "AAPL")
        self.assertFalse(aapl["is_first_seen_in_window"])


class MonitorCategoryTests(unittest.TestCase):
    def test_watchlist_category(self) -> None:
        entry = {
            "events": [{"severity": "MEDIUM", "field": "nabi_score", "category": "SCORE", "message": "x"}],
            "window_change_score": 10,
            "meaningful_change_count": 1,
            "is_watchlisted": True,
            "is_first_seen_in_window": False,
            "candidate": {},
            "latest_snapshot": {},
            "has_legacy_history": False,
        }
        category, _ = assign_category_and_badges(entry)
        self.assertEqual(category, CATEGORY_WATCHLIST)

    def test_new_category(self) -> None:
        entry = {
            "events": [],
            "window_change_score": 0,
            "meaningful_change_count": 0,
            "is_watchlisted": False,
            "is_first_seen_in_window": True,
            "candidate": {},
            "latest_snapshot": {},
            "has_legacy_history": False,
        }
        category, badges = assign_category_and_badges(entry)
        self.assertEqual(category, CATEGORY_NEW)
        self.assertIn("NEW", badges)

    def test_top_priority_entries(self) -> None:
        entries = [
            {"primary_category": CATEGORY_NONE, "research_priority": {"priority_score": 99}},
            {"primary_category": CATEGORY_ATTENTION, "research_priority": {"priority_score": 40}, "events": [], "window_change_score": 20, "latest_scan_at": "t", "symbol": "A"},
        ]
        top = top_priority_entries(entries, limit=1)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["primary_category"], CATEGORY_ATTENTION)


if __name__ == "__main__":
    unittest.main()


class MonitorImportSmokeTests(unittest.TestCase):
    def test_build_monitor_feed_import(self) -> None:
        from services.research_monitor_service import build_monitor_feed

        self.assertTrue(callable(build_monitor_feed))

    def test_build_priority_teaser_import(self) -> None:
        from services.research_monitor_service import build_priority_teaser_from_monitor

        self.assertTrue(callable(build_priority_teaser_from_monitor))

    def test_research_monitor_page_import_smoke(self) -> None:
        import py_compile
        from pathlib import Path

        page_path = Path("pages/3_Research_Monitor.py")
        source = page_path.read_text(encoding="utf-8")
        self.assertIn(
            "from services.research_monitor_service import build_monitor_feed",
            source,
        )
        py_compile.compile(page_path, doraise=True)

    def test_dashboard_teaser_import_smoke(self) -> None:
        import py_compile
        from pathlib import Path

        page_path = Path("pages/5_Firsatlar.py")
        source = page_path.read_text(encoding="utf-8")
        self.assertIn(
            "from services.daily_brief_service import build_daily_brief",
            source,
        )
        py_compile.compile(page_path, doraise=True)

    def test_dashboard_teaser_import(self) -> None:
        from services.research_monitor_service import build_priority_teaser_from_monitor

        scan_repo = MagicMock()
        scan_repo.get_completed_runs_since.return_value = []
        scan_repo.get_results_for_runs.return_value = []
        scan_repo.get_all_completed_run_ids_before.return_value = []
        scan_repo.get_symbols_with_results_before.return_value = set()
        scan_repo.row_to_snapshot.side_effect = snapshot_fn

        entries = build_priority_teaser_from_monitor(
            scan_repo=scan_repo,
            candidates=[],
            watched_candidate_ids=set(),
            limit=5,
        )
        self.assertIsInstance(entries, list)
