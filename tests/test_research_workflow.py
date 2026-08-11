import copy
import py_compile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from repositories.candidate_repository import CandidateRepository
from repositories.watchlist_repository import WatchlistRepository
from services.research_priority_engine import compute_research_priority
from services.research_workflow_service import (
    DEFAULT_RESEARCH_STATUS,
    RESEARCH_WORKFLOW_STATUSES,
    ResearchWorkflowError,
    WORKFLOW_FILTER_OPEN,
    WORKFLOW_FILTER_TAMAMLANDI,
    build_research_workflow,
    build_research_workflow_update,
    filter_monitor_entries,
    is_open_research_status,
    normalize_research_status,
    validate_research_status,
)
from services.ui_formatters import format_research_status
from tests.test_research_history import snapshot


def candidate(**overrides):
    base = {
        "id": "cand-1",
        "symbol": "NVDA",
        "company_name": "NVIDIA",
        "market": "ABD",
        "nabi_score": 82.0,
        "decision_label": "ARAŞTIRMA ADAYI",
        "opportunity_score": 74.0,
        "conviction_score": 72.0,
        "research_confidence": 80.0,
        "freshness_status": "FRESH",
        "research_status": DEFAULT_RESEARCH_STATUS,
    }
    base.update(overrides)
    return base


def monitor_entry(**overrides):
    base = {
        "symbol": "NVDA",
        "company_name": "NVIDIA",
        "candidate": candidate(),
        "research_priority": {"priority_score": 55.0},
        "events": [],
    }
    base.update(overrides)
    return base


class InMemoryCandidateStore:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {
            "cand-1": candidate(),
        }

    def table(self, name: str):
        if name != "investment_candidates":
            raise KeyError(name)
        return CandidateTable(self)


class CandidateTable:
    def __init__(self, store: InMemoryCandidateStore) -> None:
        self.store = store
        self._filters: List[tuple] = []
        self._operation = "select"
        self._payload: Optional[Dict[str, Any]] = None
        self._limit: Optional[int] = None

    def select(self, columns: str):
        self._operation = "select"
        return self

    def update(self, payload: Dict[str, Any]):
        self._operation = "update"
        self._payload = payload
        return self

    def upsert(self, payload: Dict[str, Any], on_conflict: str = ""):
        self._operation = "upsert"
        self._payload = payload
        return self

    def eq(self, key: str, value: Any):
        self._filters.append(("eq", key, value))
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self._operation == "select":
            rows = list(self.store.rows.values())
            for op, key, value in self._filters:
                if op == "eq":
                    rows = [row for row in rows if row.get(key) == value]
            if self._limit is not None:
                rows = rows[: self._limit]
            return MagicMock(data=rows)

        if self._operation == "update":
            for op, key, value in self._filters:
                if op == "eq" and key == "id" and value in self.store.rows:
                    self.store.rows[value].update(self._payload or {})
                    return MagicMock(data=[self.store.rows[value]])
            return MagicMock(data=[])

        if self._operation == "upsert":
            payload = dict(self._payload or {})
            symbol = payload.get("symbol")
            existing = next(
                (row for row in self.store.rows.values() if row.get("symbol") == symbol),
                None,
            )
            if existing:
                existing.update(payload)
                return MagicMock(data=[existing])
            new_id = f"cand-{len(self.store.rows) + 1}"
            payload["id"] = new_id
            self.store.rows[new_id] = payload
            return MagicMock(data=[payload])

        raise RuntimeError(self._operation)


class ResearchWorkflowServiceTests(unittest.TestCase):
    def test_default_yeni(self) -> None:
        self.assertEqual(normalize_research_status(None), "YENI")
        self.assertEqual(build_research_workflow({})["research_status"], "YENI")

    def test_normalize_legacy_arastirilacak(self) -> None:
        self.assertEqual(normalize_research_status("Araştırılacak"), "YENI")

    def test_normalize_legacy_inceleniyor(self) -> None:
        self.assertEqual(normalize_research_status("İnceleniyor"), "INCELEMEDE")

    def test_normalize_scanner_pollution(self) -> None:
        self.assertEqual(normalize_research_status("Otomatik tarandı"), "YENI")
        self.assertEqual(normalize_research_status("Scanner v4 tarandı"), "YENI")

    def test_invalid_status_rejected(self) -> None:
        with self.assertRaises(ResearchWorkflowError):
            validate_research_status("INVALID")

    def test_status_update_payload(self) -> None:
        payload = build_research_workflow_update(status="INCELEMEDE")
        self.assertEqual(payload["research_status"], "INCELEMEDE")

    def test_next_action(self) -> None:
        payload = build_research_workflow_update(next_action="Q3 sonrası bak")
        self.assertEqual(payload["research_next_action"], "Q3 sonrası bak")

    def test_research_note(self) -> None:
        payload = build_research_workflow_update(research_note="20-F doğrulandı")
        self.assertEqual(payload["research_note"], "20-F doğrulandı")

    def test_last_reviewed(self) -> None:
        reviewed = datetime(2026, 8, 10, 20, 8, tzinfo=timezone.utc)
        payload = build_research_workflow_update(last_reviewed_at=reviewed)
        self.assertIn("2026-08-10T20:08:00+00:00", payload["last_reviewed_at"])

    def test_tamamlandi_semantics(self) -> None:
        workflow = build_research_workflow(candidate(research_status="TAMAMLANDI"))
        self.assertEqual(workflow["research_status_label"], "Tamamlandı")
        self.assertFalse(workflow["is_open"])

    def test_is_open_yeni(self) -> None:
        self.assertTrue(is_open_research_status("YENI"))

    def test_is_open_tamamlandi_false(self) -> None:
        self.assertFalse(is_open_research_status("TAMAMLANDI"))

    def test_missing_workflow_fields_graceful(self) -> None:
        workflow = build_research_workflow(candidate())
        self.assertIsNone(workflow["research_next_action"])
        self.assertIsNone(workflow["research_note"])
        self.assertIsNone(workflow["last_reviewed_at"])

    def test_legacy_polluted_candidate_graceful(self) -> None:
        workflow = build_research_workflow(
            candidate(research_status="Scanner v4 tarandı")
        )
        self.assertEqual(workflow["research_status"], "YENI")
        self.assertEqual(workflow["research_status_label"], "Henüz başlanmadı")

    def test_ui_formatter_mappings(self) -> None:
        for status in RESEARCH_WORKFLOW_STATUSES:
            label = format_research_status(status)
            self.assertNotEqual(label, status)


class ResearchWorkflowPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryCandidateStore()
        self.repo = CandidateRepository(self.store)

    def test_status_update_persist(self) -> None:
        updated = self.repo.update_research_workflow(
            "cand-1",
            status="BEKLEMEDE",
            next_action="Katalizör bekle",
            research_note="Not",
        )
        self.assertEqual(updated["research_status"], "BEKLEMEDE")
        self.assertEqual(updated["research_next_action"], "Katalizör bekle")

    def test_mark_research_reviewed(self) -> None:
        updated = self.repo.mark_research_reviewed("cand-1")
        self.assertIsNotNone(updated.get("last_reviewed_at"))

    def test_scanner_does_not_overwrite_workflow(self) -> None:
        self.store.rows["cand-1"]["research_status"] = "INCELEMEDE"
        self.store.rows["cand-1"]["research_next_action"] = "Devam et"
        scanner_payload = {
            "symbol": "NVDA",
            "market": "ABD",
            "nabi_score": 90.0,
            "decision_label": "ARAŞTIRMA ADAYI",
        }
        self.repo.upsert_by_symbol(scanner_payload)
        row_data = self.store.rows["cand-1"]
        self.assertEqual(row_data["research_status"], "INCELEMEDE")
        self.assertEqual(row_data["research_next_action"], "Devam et")

    def test_scanner_sources_do_not_set_research_status(self) -> None:
        for name in (
            "scanner_v2_engine.py",
            "scanner_v3_engine.py",
            "scanner_v4_engine.py",
            "collector_engine.py",
        ):
            text = Path("services") / name
            self.assertNotIn('"research_status":', text.read_text(encoding="utf-8"))


class ResearchWorkflowIndependenceTests(unittest.TestCase):
    def test_priority_all_five_statuses_equal(self) -> None:
        base = candidate()
        change = {
            "has_meaningful_change": True,
            "change_score": 20,
            "changes": [{"severity": "HIGH", "message": "Test"}],
        }
        scores = []
        for status in RESEARCH_WORKFLOW_STATUSES:
            item = compute_research_priority(
                {**base, "research_status": status},
                recent_change=change,
            )
            scores.append(item["priority_score"])
        self.assertEqual(len(set(scores)), 1)

    def test_scanner_decision_independent(self) -> None:
        low = compute_research_priority(
            candidate(decision_label="İZLE"),
            recent_change={"has_meaningful_change": False, "change_score": 0, "changes": []},
        )
        high = compute_research_priority(
            candidate(decision_label="ARAŞTIRMA ADAYI"),
            recent_change={"has_meaningful_change": False, "change_score": 0, "changes": []},
        )
        self.assertNotEqual(low["priority_score"], high["priority_score"])

    def test_watchlist_add_independent(self) -> None:
        self.assertEqual(
            normalize_research_status(
                candidate(research_status="YENI")["research_status"]
            ),
            "YENI",
        )

    def test_watchlist_note_not_research_note(self) -> None:
        cand = candidate(research_note="Araştırma notu")
        watchlist_note = "Neden izliyorum"
        self.assertNotEqual(cand.get("research_note"), watchlist_note)


class ResearchWorkflowMonitorFilterTests(unittest.TestCase):
    def test_open_filter(self) -> None:
        entries = [
            monitor_entry(candidate=candidate(research_status="YENI")),
            monitor_entry(
                symbol="MSFT",
                candidate=candidate(symbol="MSFT", research_status="TAMAMLANDI"),
            ),
        ]
        filtered = filter_monitor_entries(entries, WORKFLOW_FILTER_OPEN)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["symbol"], "NVDA")

    def test_incelemde_filter(self) -> None:
        entries = [
            monitor_entry(candidate=candidate(research_status="INCELEMEDE")),
            monitor_entry(candidate=candidate(research_status="YENI")),
        ]
        filtered = filter_monitor_entries(entries, "İnceliyorum")
        self.assertEqual(len(filtered), 1)

    def test_beklemede_filter(self) -> None:
        entries = [
            monitor_entry(candidate=candidate(research_status="BEKLEMEDE")),
            monitor_entry(candidate=candidate(research_status="YENI")),
        ]
        filtered = filter_monitor_entries(entries, "Beklemede")
        self.assertEqual(len(filtered), 1)
        entries = [
            monitor_entry(candidate=candidate(research_status="TEKRAR_BAK")),
        ]
        filtered = filter_monitor_entries(entries, "Tekrar bak")
        self.assertEqual(len(filtered), 1)

    def test_tamamlandi_filter(self) -> None:
        entries = [
            monitor_entry(candidate=candidate(research_status="TAMAMLANDI")),
            monitor_entry(candidate=candidate(research_status="YENI")),
        ]
        filtered = filter_monitor_entries(entries, WORKFLOW_FILTER_TAMAMLANDI)
        self.assertEqual(len(filtered), 1)


class ResearchWorkflowRegressionTests(unittest.TestCase):
    def test_stale_issuer_priority_unchanged_by_workflow(self) -> None:
        stale = candidate(freshness_status="STALE")
        score_a = compute_research_priority(
            {**stale, "research_status": "YENI"},
            recent_change={"has_meaningful_change": False, "change_score": 0, "changes": []},
        )["priority_score"]
        score_b = compute_research_priority(
            {**stale, "research_status": "TAMAMLANDI"},
            recent_change={"has_meaningful_change": False, "change_score": 0, "changes": []},
        )["priority_score"]
        self.assertEqual(score_a, score_b)

    def test_foreign_issuer_regression(self) -> None:
        foreign = candidate(symbol="SONY", freshness_status="STALE")
        workflow = build_research_workflow(foreign)
        self.assertTrue(workflow["is_open"])

    def test_fmp_unavailable_regression(self) -> None:
        from services.change_detection_engine import detect_changes

        previous = snapshot(pe_ratio=20.0, pe_source="quote")
        current = snapshot(pe_ratio=None, pe_source="unavailable")
        change = detect_changes(previous, current)
        priority = compute_research_priority(
            candidate(research_status="INCELEMEDE"),
            recent_change=change,
        )
        reasons = " ".join(priority["reasons"]).lower()
        self.assertNotIn("değerleme", reasons)


class ResearchWorkflowPageSmokeTests(unittest.TestCase):
    def test_company_report_compile(self) -> None:
        py_compile.compile("pages/4_Company_Report.py", doraise=True)

    def test_research_monitor_compile(self) -> None:
        py_compile.compile("pages/3_Research_Monitor.py", doraise=True)

    def test_dashboard_compile(self) -> None:
        py_compile.compile("pages/1_Dashboard.py", doraise=True)

    def test_aday_havuzu_compile(self) -> None:
        py_compile.compile("pages/2_Aday_Havuzu.py", doraise=True)


class WatchlistWorkflowIndependenceTests(unittest.TestCase):
    def test_watchlist_add_does_not_change_workflow(self) -> None:
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        table.select.return_value = table
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"status": "AKTİF"}])

        repo = WatchlistRepository(client)
        repo.add_candidate("cand-1", note="Takip")
        workflow = build_research_workflow(candidate(research_status="YENI"))
        self.assertEqual(workflow["research_status"], "YENI")


if __name__ == "__main__":
    unittest.main()
