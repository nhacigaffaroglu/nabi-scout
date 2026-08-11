import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.page_smoke import load_dashboard_page

from services.daily_action_service import (
    ACTION_TIER_T1,
    ACTION_TIER_T2,
    ACTION_TIER_T3,
    ACTION_TIER_T4,
    ACTION_TIER_T5,
    DATA_QUALITY_ACTIONABLE,
    DATA_QUALITY_WAIT,
    DailyActionItem,
    assign_action_tier,
    build_action_reasons,
    build_today_actions,
    classify_data_quality_band,
    is_availability_only_change,
    open_research_backlog_caveat,
    select_top_actions,
)
from services.signal_classification_service import SignalSummary
from services.daily_brief_service import build_daily_brief
from services.research_history_service import (
    CATEGORY_ATTENTION,
    CATEGORY_NEW,
    CATEGORY_WATCHLIST,
)


def research_change_event():
    return {
        "message": "Karar etiketi değişti",
        "severity": "HIGH",
        "field": "decision_label",
        "category": "DECISION",
        "old": "İZLE",
        "new": "ARAŞTIRMA ADAYI",
    }


def candidate(
    symbol: str,
    *,
    decision_label="ARAŞTIRMA ADAYI",
    completeness=76.0,
    freshness="FRESH",
    workflow="YENI",
    next_action=None,
    last_reviewed_at=None,
    **extra,
):
    base = {
        "id": f"id-{symbol}",
        "symbol": symbol,
        "company_name": symbol,
        "decision_label": decision_label,
        "data_completeness": completeness,
        "freshness_status": freshness,
        "research_status": workflow,
        "research_next_action": next_action,
        "last_reviewed_at": last_reviewed_at,
    }
    base.update(extra)
    return base


def monitor_entry(
    symbol: str,
    *,
    meaningful=1,
    window_score=15,
    first_seen=False,
    watchlist=False,
    events=None,
    decision_label="ARAŞTIRMA ADAYI",
    priority_score=50.0,
    latest_scan_at="2026-08-11T14:47:00+00:00",
    cand=None,
):
    cand = cand or candidate(symbol, decision_label=decision_label)
    return {
        "symbol": symbol,
        "company_name": symbol,
        "candidate": cand,
        "latest_snapshot": {
            "symbol": symbol,
            "decision_label": decision_label,
            "data_completeness": cand.get("data_completeness"),
            "freshness_status": cand.get("freshness_status"),
        },
        "events": events or [{
            "message": "Veri tamlığı %12 → %76",
            "severity": "MEDIUM",
            "field": "data_completeness",
            "category": "COMPLETENESS",
        }],
        "meaningful_change_count": meaningful,
        "window_change_score": window_score,
        "is_first_seen_in_window": first_seen,
        "is_watchlisted": watchlist,
        "latest_scan_at": latest_scan_at,
        "primary_category": CATEGORY_ATTENTION,
        "research_priority": {
            "priority_score": priority_score,
            "priority_label": "ORTA",
            "reasons": ["ARAŞTIRMA ADAYI"],
        },
        "recent_change": {
            "has_meaningful_change": meaningful > 0,
            "change_score": window_score,
            "changes": events or [],
        },
    }


def feed_from_entries(entries):
    return {
        "entries": entries,
        "categories": {
            "ATTENTION": [e for e in entries if e.get("primary_category") == CATEGORY_ATTENTION],
            "WATCHLIST": [e for e in entries if e.get("primary_category") == CATEGORY_WATCHLIST],
            "NEW": [e for e in entries if e.get("primary_category") == CATEGORY_NEW],
            "DATA_ISSUES": [],
        },
    }


def production_shaped_feed():
    entries = [
        monitor_entry(
            "NVDA",
            meaningful=2,
            priority_score=64.1,
            first_seen=True,
            watchlist=True,
            cand=candidate(
                "NVDA",
                workflow="INCELEMEDE",
                next_action="Q3 earnings sonrası tekrar bak",
                last_reviewed_at="2026-08-10T21:19:11+00:00",
            ),
        ),
        monitor_entry("GOOGL", meaningful=1, priority_score=52.8, first_seen=True),
        monitor_entry(
            "AVGO",
            meaningful=1,
            priority_score=38.6,
            first_seen=True,
            decision_label="İZLE",
            cand=candidate("AVGO", decision_label="İZLE"),
        ),
        monitor_entry(
            "MSFT",
            meaningful=2,
            priority_score=38.0,
            first_seen=True,
            decision_label="İZLE",
            cand=candidate("MSFT", decision_label="İZLE", workflow="TAMAMLANDI"),
        ),
        monitor_entry(
            "AAPL",
            meaningful=2,
            priority_score=25.8,
            first_seen=True,
            decision_label="İKİNCİL İNCELEME",
            cand=candidate("AAPL", decision_label="İKİNCİL İNCELEME"),
        ),
        {
            **monitor_entry(
                "TSM",
                meaningful=0,
                window_score=0,
                first_seen=True,
                priority_score=46.8,
                events=[],
                cand=candidate("TSM", freshness="AGING"),
            ),
            "primary_category": CATEGORY_NEW,
        },
    ]
    return feed_from_entries(entries)


class DataQualityTests(unittest.TestCase):
    def test_actionable_at_65(self) -> None:
        band, caveat = classify_data_quality_band(
            candidate("AAPL", completeness=76.0),
            meaningful_change_count=1,
            availability_only=False,
        )
        self.assertEqual(band, DATA_QUALITY_ACTIONABLE)
        self.assertIsNone(caveat)

    def test_wait_below_40(self) -> None:
        band, _ = classify_data_quality_band(candidate("AACB", completeness=16.7))
        self.assertEqual(band, DATA_QUALITY_WAIT)

    def test_fmp_warning_with_sec_backed_data_stays_actionable(self) -> None:
        entry = monitor_entry("NVDA")
        entry["events"] = [{
            "message": "FMP profile: rate limit",
            "severity": "MEDIUM",
            "category": "AVAILABILITY",
        }]
        band, _ = classify_data_quality_band(
            candidate("NVDA", completeness=76.0),
            monitor_entry=entry,
            meaningful_change_count=1,
            availability_only=True,
        )
        self.assertEqual(band, DATA_QUALITY_ACTIONABLE)

    def test_backlog_caveat_for_low_data(self) -> None:
        self.assertIn(
            "Veri bekle",
            open_research_backlog_caveat(candidate("AACB", completeness=16.7)) or "",
        )


class AvailabilityOnlyTests(unittest.TestCase):
    def test_completeness_only_event(self) -> None:
        entry = monitor_entry("NVDA")
        self.assertTrue(is_availability_only_change(entry))

    def test_decision_change_not_availability_only(self) -> None:
        entry = monitor_entry(
            "NVDA",
            events=[{
                "message": "Karar etiketi değişti",
                "severity": "HIGH",
                "field": "decision_label",
                "category": "DECISION",
            }],
        )
        self.assertFalse(is_availability_only_change(entry))

    def test_availability_reason_wording(self) -> None:
        reasons = build_action_reasons(
            action_tier=ACTION_TIER_T3,
            monitor_entry=monitor_entry("NVDA"),
            candidate=candidate("NVDA"),
            workflow_status="YENI",
            is_watchlisted=False,
            next_action=None,
            availability_only=True,
            data_quality_caveat=None,
        )
        self.assertTrue(any("Veri tamlığı değişti" in reason for reason in reasons))
        self.assertFalse(any("finansalları güçlendi" in reason for reason in reasons))


class ActionTierTests(unittest.TestCase):
    def test_availability_only_incelemde_watchlist_not_t1(self) -> None:
        tier = assign_action_tier(
            meaningful_change_count=1,
            workflow_status="INCELEMEDE",
            is_watchlisted=True,
            next_action="Q3 sonrası bak",
            data_quality_band=DATA_QUALITY_ACTIONABLE,
            availability_only=True,
            decision_label="ARAŞTIRMA ADAYI",
            is_first_seen=True,
            is_open_workflow=True,
        )
        self.assertEqual(tier, ACTION_TIER_T3)

    def test_availability_only_tekrar_bak_next_action_not_t1(self) -> None:
        tier = assign_action_tier(
            meaningful_change_count=1,
            workflow_status="TEKRAR_BAK",
            is_watchlisted=False,
            next_action="Q3 sonrası bak",
            data_quality_band=DATA_QUALITY_ACTIONABLE,
            availability_only=True,
            decision_label="ARAŞTIRMA ADAYI",
            is_first_seen=False,
            is_open_workflow=True,
        )
        self.assertEqual(tier, ACTION_TIER_T3)

    def test_genuine_change_incelemde_watchlist_is_t1(self) -> None:
        tier = assign_action_tier(
            meaningful_change_count=1,
            workflow_status="INCELEMEDE",
            is_watchlisted=True,
            next_action="Q3 sonrası bak",
            data_quality_band=DATA_QUALITY_ACTIONABLE,
            availability_only=False,
            decision_label="ARAŞTIRMA ADAYI",
            is_first_seen=True,
            is_open_workflow=True,
        )
        self.assertEqual(tier, ACTION_TIER_T1)

    def test_research_relevant_meaningful_is_t2_when_not_availability_only(self) -> None:
        tier = assign_action_tier(
            meaningful_change_count=1,
            workflow_status="YENI",
            is_watchlisted=False,
            next_action=None,
            data_quality_band=DATA_QUALITY_ACTIONABLE,
            availability_only=False,
            decision_label="ARAŞTIRMA ADAYI",
            is_first_seen=True,
            is_open_workflow=True,
        )
        self.assertEqual(tier, ACTION_TIER_T2)

    def test_availability_only_blocks_t2(self) -> None:
        tier = assign_action_tier(
            meaningful_change_count=1,
            workflow_status="YENI",
            is_watchlisted=False,
            next_action=None,
            data_quality_band=DATA_QUALITY_ACTIONABLE,
            availability_only=True,
            decision_label="ARAŞTIRMA ADAYI",
            is_first_seen=True,
            is_open_workflow=True,
        )
        self.assertEqual(tier, ACTION_TIER_T3)

    def test_tamamlandi_with_change_is_t3(self) -> None:
        tier = assign_action_tier(
            meaningful_change_count=1,
            workflow_status="TAMAMLANDI",
            is_watchlisted=False,
            next_action=None,
            data_quality_band=DATA_QUALITY_ACTIONABLE,
            availability_only=True,
            decision_label="İZLE",
            is_first_seen=True,
            is_open_workflow=False,
        )
        self.assertEqual(tier, ACTION_TIER_T3)

    def test_first_seen_without_change_is_t4(self) -> None:
        tier = assign_action_tier(
            meaningful_change_count=0,
            workflow_status="YENI",
            is_watchlisted=False,
            next_action=None,
            data_quality_band=DATA_QUALITY_ACTIONABLE,
            availability_only=False,
            decision_label="ARAŞTIRMA ADAYI",
            is_first_seen=True,
            is_open_workflow=True,
        )
        self.assertEqual(tier, ACTION_TIER_T4)

    def test_open_workflow_without_catalyst_is_t5(self) -> None:
        tier = assign_action_tier(
            meaningful_change_count=0,
            workflow_status="YENI",
            is_watchlisted=False,
            next_action=None,
            data_quality_band=DATA_QUALITY_WAIT,
            availability_only=False,
            decision_label=None,
            is_first_seen=False,
            is_open_workflow=True,
        )
        self.assertEqual(tier, ACTION_TIER_T5)


class Top3SelectionTests(unittest.TestCase):
    def _item(
        self,
        symbol,
        tier,
        score=10,
        meaningful=1,
        *,
        research_actionable=True,
    ):
        summary = SignalSummary(
            is_research_actionable=research_actionable,
            is_data_quality_only=not research_actionable,
            families=frozenset({"RESEARCH"} if research_actionable else {"DATA_QUALITY"}),
        )
        return DailyActionItem(
            symbol=symbol,
            company_name=symbol,
            action_tier=tier,
            action_label=tier,
            reasons=[symbol],
            workflow_status="YENI",
            workflow_status_label="Henüz başlanmadı",
            next_action=None,
            last_reviewed_at=None,
            is_watchlisted=False,
            meaningful_change_count=meaningful,
            window_change_score=15,
            research_priority_score=score,
            research_priority_label="ORTA",
            is_first_seen=False,
            data_quality_band=DATA_QUALITY_ACTIONABLE,
            data_quality_caveat=None,
            latest_scan_at="2026-08-11T14:47:00+00:00",
            company_report_target={"symbol": symbol},
            candidate={"symbol": symbol},
            is_research_actionable=research_actionable,
            signal_summary=summary,
        )

    def test_t4_does_not_displace_t123(self) -> None:
        items = [
            self._item("NVDA", ACTION_TIER_T1, score=60),
            self._item("GOOGL", ACTION_TIER_T3, score=50),
            self._item("AVGO", ACTION_TIER_T3, score=40),
            self._item("TSM", ACTION_TIER_T4, score=99),
        ]
        top = select_top_actions(items, max_actions=3)
        self.assertEqual([i.symbol for i in top], ["NVDA", "GOOGL", "AVGO"])
        self.assertNotIn("TSM", [i.symbol for i in top])

    def test_t4_no_longer_fills_top3(self) -> None:
        items = [
            self._item("NVDA", ACTION_TIER_T1, score=60),
            self._item("TSM", ACTION_TIER_T4, score=99, research_actionable=False),
        ]
        top = select_top_actions(items, max_actions=3)
        self.assertEqual([i.symbol for i in top], ["NVDA"])

    def test_data_quality_only_not_top3(self) -> None:
        items = [
            self._item("NVDA", ACTION_TIER_T3, score=60, research_actionable=False),
        ]
        self.assertEqual(select_top_actions(items, max_actions=3), [])

    def test_wait_never_top3(self) -> None:
        wait_item = self._item("AACB", ACTION_TIER_T5, score=0, meaningful=0)
        wait_item = DailyActionItem(
            **{
                **wait_item.__dict__,
                "data_quality_band": DATA_QUALITY_WAIT,
            }
        )
        top = select_top_actions([wait_item], max_actions=3)
        self.assertEqual(top, [])

    def test_max_three(self) -> None:
        items = [
            self._item(f"S{i}", ACTION_TIER_T3, score=50 - i)
            for i in range(6)
        ]
        self.assertEqual(len(select_top_actions(items, max_actions=3)), 3)


class BuildTodayActionsTests(unittest.TestCase):
    def test_production_shaped_fixture(self) -> None:
        feed = production_shaped_feed()
        candidates = [
            candidate("NVDA", workflow="INCELEMEDE", next_action="Q3 earnings sonrası tekrar bak"),
            candidate("GOOGL"),
            candidate("AVGO", decision_label="İZLE"),
            candidate("MSFT", decision_label="İZLE", workflow="TAMAMLANDI"),
            candidate("AAPL", decision_label="İKİNCİL İNCELEME"),
            candidate("TSM", freshness="AGING"),
            candidate("AACB", completeness=16.7),
        ]
        top = build_today_actions(
            feed=feed,
            candidates=candidates,
            watched_candidate_ids={"id-NVDA"},
            max_actions=3,
        )
        self.assertEqual(top, [])

    def test_quiet_day_data_quality_only_returns_empty_top3(self) -> None:
        feed = production_shaped_feed()
        top = build_today_actions(
            feed=feed,
            candidates=[candidate("NVDA", workflow="INCELEMEDE")],
            watched_candidate_ids={"id-NVDA"},
        )
        self.assertEqual(top, [])

    def test_genuine_non_availability_change_qualifies_t1(self) -> None:
        feed = feed_from_entries([
            monitor_entry(
                "NVDA",
                meaningful=1,
                watchlist=True,
                cand=candidate(
                    "NVDA",
                    workflow="INCELEMEDE",
                    next_action="Q3 earnings sonrası tekrar bak",
                ),
                events=[{
                    "message": "Karar etiketi değişti",
                    "severity": "HIGH",
                    "field": "decision_label",
                    "category": "DECISION",
                }],
            ),
        ])
        top = build_today_actions(
            feed=feed,
            candidates=[candidate("NVDA", workflow="INCELEMEDE", next_action="Q3 earnings sonrası tekrar bak")],
            watched_candidate_ids={"id-NVDA"},
            max_actions=3,
        )
        self.assertEqual(top[0].symbol, "NVDA")
        self.assertEqual(top[0].action_tier, ACTION_TIER_T1)

    def test_t4_does_not_fill_remaining_slot(self) -> None:
        feed = feed_from_entries([
            monitor_entry(
                "NVDA",
                meaningful=1,
                priority_score=60,
                events=[research_change_event()],
            ),
            {
                **monitor_entry("TSM", meaningful=0, window_score=0, first_seen=True, priority_score=99, events=[]),
                "primary_category": CATEGORY_NEW,
            },
        ])
        top = build_today_actions(
            feed=feed,
            candidates=[candidate("NVDA"), candidate("TSM", freshness="AGING")],
            max_actions=3,
        )
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].symbol, "NVDA")

    def test_candidate_only_backlog(self) -> None:
        feed = feed_from_entries([])
        top = build_today_actions(
            feed=feed,
            candidates=[candidate("AACB", completeness=16.7)],
            max_actions=3,
        )
        self.assertEqual(top, [])

    def test_reviewed_without_new_change_demoted(self) -> None:
        feed = feed_from_entries([
            monitor_entry(
                "NVDA",
                meaningful=1,
                cand=candidate(
                    "NVDA",
                    workflow="INCELEMEDE",
                    last_reviewed_at="2026-08-11T15:00:00+00:00",
                ),
                latest_scan_at="2026-08-11T14:47:00+00:00",
            )
        ])
        top = build_today_actions(
            feed=feed,
            candidates=[candidate("NVDA", workflow="INCELEMEDE")],
            watched_candidate_ids={"id-NVDA"},
            max_actions=3,
        )
        self.assertEqual(top, [])

    def test_reviewed_before_change_resurfaces(self) -> None:
        feed = feed_from_entries([
            monitor_entry(
                "NVDA",
                meaningful=1,
                events=[research_change_event()],
                cand=candidate(
                    "NVDA",
                    workflow="INCELEMEDE",
                    last_reviewed_at="2026-08-10T21:00:00+00:00",
                ),
                latest_scan_at="2026-08-11T14:47:00+00:00",
            )
        ])
        top = build_today_actions(
            feed=feed,
            candidates=[candidate("NVDA", workflow="INCELEMEDE")],
            watched_candidate_ids={"id-NVDA"},
            max_actions=3,
        )
        self.assertEqual(top[0].symbol, "NVDA")

    def test_no_buy_sell_wording(self) -> None:
        top = build_today_actions(
            feed=production_shaped_feed(),
            candidates=[candidate("NVDA", workflow="INCELEMEDE")],
            watched_candidate_ids={"id-NVDA"},
        )
        forbidden = ("al", "sat", "tut", "buy", "sell", "hold")
        for item in top:
            blob = " ".join([item.action_label, *item.reasons]).casefold()
            for word in forbidden:
                self.assertNotIn(f" {word} ", f" {blob} ")


class DailyBriefIntegrationTests(unittest.TestCase):
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
        self.scan_repo.get_all_completed_run_ids_before.return_value = set()
        self.scan_repo.get_symbols_with_results_before.return_value = set()

    @patch("services.daily_brief_service.build_monitor_feed")
    def test_today_actions_dedup_new_candidates(self, mock_feed) -> None:
        mock_feed.return_value = production_shaped_feed()
        self.candidate_repo.get_all.return_value = [
            candidate("NVDA", workflow="INCELEMEDE", next_action="Q3"),
            candidate("GOOGL"),
            candidate("AVGO", decision_label="İZLE"),
            candidate("MSFT", decision_label="İZLE", workflow="TAMAMLANDI"),
            candidate("AAPL", decision_label="İKİNCİL İNCELEME"),
            candidate("TSM", freshness="AGING"),
        ]
        self.watchlist_repo.watched_candidate_ids.return_value = {"id-NVDA"}
        brief = build_daily_brief(
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            watchlist_repo=self.watchlist_repo,
        )
        today_symbols = {item["symbol"] for item in brief["today_actions"]}
        for item in brief["new_candidates"]:
            self.assertNotIn(item["symbol"], today_symbols)
        self.assertEqual(brief["today_actions"], [])
        self.assertIn("NVDA", [item["symbol"] for item in brief.get("attention_items", [])])


class DashboardSmokeTests(unittest.TestCase):
    def test_dashboard_import_with_today_actions(self) -> None:
        mock_st = MagicMock()
        mock_st.session_state = {}
        mock_st.columns.side_effect = lambda spec: [
            MagicMock() for _ in range(len(spec) if isinstance(spec, list) else spec)
        ]
        mock_st.button.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.cache_data = lambda **kwargs: (lambda fn: fn)
        mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
        mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
        mock_st.query_params = {}

        brief = {
            "scheduled_run": {
                "status": "partial",
                "status_label": "Kısmi",
                "detail": "ok",
                "started_at": None,
                "completed_at": "2026-08-11T14:47:07+00:00",
            },
            "headline": "test",
            "summary_stats": {
                "meaningful_change_count": 5,
                "research_change_count": 1,
                "data_quality_change_count": 4,
                "discovery_count": 1,
                "attention_count": 0,
                "new_candidate_count": 1,
                "watchlist_change_count": 0,
                "open_research_count": 1,
                "data_issue_count": 0,
                "today_action_count": 1,
                "data_quality_update_count": 2,
            },
            "today_actions": [{
                "symbol": "NVDA",
                "company_name": "NVIDIA",
                "action_label": "Bugün devam et",
                "reasons": ["Veri tamlığı değişti; şirket yeniden gözden geçirilmeli."],
                "workflow_status_label": "İnceliyorum",
                "next_action": "Q3 earnings sonrası tekrar bak",
                "data_quality_caveat": None,
                "company_report_target": {"symbol": "NVDA"},
                "candidate": {"symbol": "NVDA"},
            }],
            "attention_items": [],
            "new_candidates": [{"symbol": "TSM", "company_name": "TSM", "reasons": []}],
            "watchlist_changes": [],
            "open_research": [{
                "symbol": "AACB",
                "workflow_status_label": "Henüz başlanmadı",
                "data_quality_caveat": "Veri bekle — değerlendirme için yeterli veri yok.",
            }],
            "data_issues": [],
            "data_quality_updates": [{
                "symbol": "GOOGL",
                "company_name": "GOOGL",
                "summary": "Veri tamlığı yeniden yükseldi.",
                "direction": "RECOVERY",
                "company_report_target": {"symbol": "GOOGL"},
                "candidate": {"symbol": "GOOGL"},
            }],
            "has_anything_to_report": True,
        }

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            with patch("services.supabase_client.get_supabase_client") as mock_client:
                mock_client.return_value = MagicMock()
                with patch("services.daily_brief_service.build_daily_brief", return_value=brief):
                    load_dashboard_page()

        mock_st.title.assert_called()


if __name__ == "__main__":
    unittest.main()
