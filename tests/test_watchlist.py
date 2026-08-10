import copy
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from repositories.watchlist_repository import (
    LEGACY_ACTIVE_STATUS,
    STATUS_ACTIVE,
    STATUS_INACTIVE,
    WatchlistRepository,
)


class InMemorySupabase:
    def __init__(self) -> None:
        self.watchlist: List[Dict[str, Any]] = []
        self.candidates: Dict[str, Dict[str, Any]] = {}

    def table(self, name: str):
        if name == "watchlist":
            return WatchlistTable(self)
        if name == "investment_candidates":
            return CandidateTable(self)
        raise KeyError(name)


class WatchlistTable:
    def __init__(self, store: InMemorySupabase) -> None:
        self.store = store
        self._filters: List[tuple] = []
        self._operation = "select"
        self._payload: Optional[Dict[str, Any]] = None
        self._limit: Optional[int] = None
        self._order: Optional[tuple] = None
        self._join_select = False

    def select(self, columns: str):
        self._operation = "select"
        self._join_select = "investment_candidates" in columns
        return self

    def insert(self, payload: Dict[str, Any]):
        self._operation = "insert"
        self._payload = payload
        return self

    def update(self, payload: Dict[str, Any]):
        self._operation = "update"
        self._payload = payload
        return self

    def eq(self, field: str, value: Any):
        self._filters.append(("eq", field, value))
        return self

    def in_(self, field: str, values: List[Any]):
        self._filters.append(("in", field, values))
        return self

    def order(self, field: str, desc: bool = False):
        self._order = (field, desc)
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    def execute(self):
        rows = list(self.store.watchlist)

        for op, field, value in self._filters:
            if op == "eq":
                rows = [row for row in rows if row.get(field) == value]
            elif op == "in":
                rows = [row for row in rows if row.get(field) in value]

        if self._operation == "select":
            if self._join_select:
                joined = []
                for row in rows:
                    candidate = self.store.candidates.get(row["candidate_id"])
                    joined.append({
                        **row,
                        "investment_candidates": candidate,
                    })
                rows = joined

            if self._order:
                field, desc = self._order
                rows.sort(
                    key=lambda item: item.get(field) or "",
                    reverse=desc,
                )

            if self._limit is not None:
                rows = rows[: self._limit]

            return MagicMock(data=rows)

        if self._operation == "insert":
            row = {
                "id": f"wl-{len(self.store.watchlist) + 1}",
                "created_at": datetime.now(timezone.utc).isoformat(),
                **self._payload,
            }
            self.store.watchlist.append(row)
            return MagicMock(data=[row])

        if self._operation == "update":
            updated_rows = []
            for row in self.store.watchlist:
                if all(row.get(field) == value for op, field, value in self._filters if op == "eq"):
                    row.update(self._payload or {})
                    updated_rows.append(dict(row))
            return MagicMock(data=updated_rows)

        raise RuntimeError(f"Unsupported operation: {self._operation}")


class CandidateTable:
    def __init__(self, store: InMemorySupabase) -> None:
        self.store = store

    def select(self, columns: str):
        return self

    def eq(self, field: str, value: Any):
        return self

    def limit(self, count: int):
        return self

    def execute(self):
        return MagicMock(data=[])


class WatchlistRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemorySupabase()
        self.repo = WatchlistRepository(self.store)
        self.store.candidates["cand-1"] = {
            "id": "cand-1",
            "symbol": "AAPL",
            "company_name": "Apple",
            "decision_label": "İZLE",
            "nabi_score": 72.0,
        }
        self.store.candidates["cand-2"] = {
            "id": "cand-2",
            "symbol": "MSFT",
            "company_name": "Microsoft",
            "decision_label": "ARAŞTIRMA ADAYI",
            "nabi_score": 80.0,
        }

    def test_add_candidate(self) -> None:
        row = self.repo.add_candidate("cand-1", note="Takip")
        self.assertEqual(row["status"], STATUS_ACTIVE)
        self.assertEqual(row["notes"], "Takip")
        self.assertTrue(self.repo.is_watched("cand-1"))

    def test_duplicate_add_idempotent(self) -> None:
        self.repo.add_candidate("cand-1", note="İlk")
        second = self.repo.add_candidate("cand-1", note="İkinci")
        self.assertEqual(len(self.store.watchlist), 1)
        self.assertEqual(second["status"], STATUS_ACTIVE)
        self.assertEqual(second["notes"], "İkinci")
        self.assertEqual(self.store.watchlist[0]["notes"], "İkinci")

    def test_passive_to_active_reactivation(self) -> None:
        self.repo.add_candidate("cand-1")
        self.repo.deactivate("cand-1")
        self.assertFalse(self.repo.is_watched("cand-1"))
        row = self.repo.add_candidate("cand-1", note="Tekrar")
        self.assertEqual(row["status"], STATUS_ACTIVE)
        self.assertTrue(self.repo.is_watched("cand-1"))

    def test_remove_deactivate(self) -> None:
        self.repo.add_candidate("cand-1")
        row = self.repo.deactivate("cand-1")
        self.assertEqual(row["status"], STATUS_INACTIVE)
        self.assertFalse(self.repo.is_watched("cand-1"))
        self.assertEqual(len(self.store.watchlist), 1)

    def test_list_active(self) -> None:
        self.repo.add_candidate("cand-1")
        self.repo.add_candidate("cand-2")
        self.repo.deactivate("cand-2")
        active = self.repo.list_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["candidate"]["symbol"], "AAPL")

    def test_legacy_izle_active_compatibility(self) -> None:
        self.store.watchlist.append({
            "id": "legacy-1",
            "candidate_id": "cand-1",
            "status": LEGACY_ACTIVE_STATUS,
            "notes": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        self.assertTrue(self.repo.is_watched("cand-1"))
        active = self.repo.list_active()
        self.assertEqual(len(active), 1)
        new_row = self.repo.add_candidate("cand-1")
        self.assertEqual(new_row["status"], STATUS_ACTIVE)

    def test_scanner_decision_izle_not_watchlist(self) -> None:
        candidate = self.store.candidates["cand-1"]
        self.assertEqual(candidate["decision_label"], "İZLE")
        self.assertFalse(self.repo.is_watched("cand-1"))
        self.repo.add_candidate("cand-1")
        self.assertTrue(self.repo.is_watched("cand-1"))
        candidate["decision_label"] = "ŞİMDİLİK UZAK DUR"
        self.assertTrue(self.repo.is_watched("cand-1"))

    def test_note_update(self) -> None:
        self.repo.add_candidate("cand-1", note="Eski")
        updated = self.repo.update_note("cand-1", "Yeni not")
        self.assertEqual(updated["notes"], "Yeni not")


if __name__ == "__main__":
    unittest.main()
