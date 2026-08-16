from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from repositories.wealth_portfolio_snapshot_repository import WealthPortfolioSnapshotRepository
from services.wealth_snapshot_canonical import (
    group_duplicate_snapshot_rows,
    merge_nullable_fields_into_canonical,
    nullable_field_diffs,
    select_canonical_snapshot_row,
)


def _row(
    *,
    row_id: str,
    portfolio_id: str = "pf-1",
    captured_at: str,
    created_at: str | None = None,
    snapshot_date: str | None = None,
    liabilities_total: float | None = None,
    priced_market_value: float = 1000.0,
) -> dict:
    return {
        "id": row_id,
        "portfolio_id": portfolio_id,
        "captured_at": captured_at,
        "created_at": created_at or captured_at,
        "snapshot_date": snapshot_date,
        "liabilities_total": liabilities_total,
        "priced_market_value": priced_market_value,
    }


class SnapshotCanonicalSelectionTests(unittest.TestCase):
    def test_latest_captured_at_wins(self) -> None:
        rows = [
            _row(row_id="old", captured_at="2026-08-13T10:00:00+00:00"),
            _row(row_id="new", captured_at="2026-08-13T18:00:00+00:00"),
        ]
        canonical = select_canonical_snapshot_row(rows)
        self.assertEqual(canonical["id"], "new")

    def test_same_captured_at_tie_breaks_on_created_at(self) -> None:
        rows = [
            _row(
                row_id="a",
                captured_at="2026-08-13T12:00:00+00:00",
                created_at="2026-08-13T12:00:01+00:00",
            ),
            _row(
                row_id="b",
                captured_at="2026-08-13T12:00:00+00:00",
                created_at="2026-08-13T12:00:05+00:00",
            ),
        ]
        canonical = select_canonical_snapshot_row(rows)
        self.assertEqual(canonical["id"], "b")

    def test_same_timestamp_tie_breaks_on_id(self) -> None:
        rows = [
            _row(
                row_id="aaa",
                captured_at="2026-08-13T12:00:00+00:00",
                created_at="2026-08-13T12:00:00+00:00",
            ),
            _row(
                row_id="bbb",
                captured_at="2026-08-13T12:00:00+00:00",
                created_at="2026-08-13T12:00:00+00:00",
            ),
        ]
        canonical = select_canonical_snapshot_row(rows)
        self.assertEqual(canonical["id"], "bbb")

    def test_multiple_duplicate_groups(self) -> None:
        rows = [
            _row(row_id="d1a", portfolio_id="pf-1", captured_at="2026-08-13T09:00:00+00:00", snapshot_date="2026-08-13"),
            _row(row_id="d1b", portfolio_id="pf-1", captured_at="2026-08-13T15:00:00+00:00", snapshot_date="2026-08-13"),
            _row(row_id="d2a", portfolio_id="pf-2", captured_at="2026-08-14T09:00:00+00:00", snapshot_date="2026-08-14"),
            _row(row_id="d2b", portfolio_id="pf-2", captured_at="2026-08-14T11:00:00+00:00", snapshot_date="2026-08-14"),
            _row(row_id="solo", portfolio_id="pf-3", captured_at="2026-08-15T09:00:00+00:00", snapshot_date="2026-08-15"),
        ]
        groups = group_duplicate_snapshot_rows(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(select_canonical_snapshot_row(groups[("pf-1", date(2026, 8, 13))])["id"], "d1b")
        self.assertEqual(select_canonical_snapshot_row(groups[("pf-2", date(2026, 8, 14))])["id"], "d2b")

    def test_nullable_merge_only_fills_missing_canonical_fields(self) -> None:
        canonical = _row(row_id="keep", captured_at="2026-08-13T18:00:00+00:00", liabilities_total=None)
        dupe = _row(row_id="drop", captured_at="2026-08-13T10:00:00+00:00", liabilities_total=500.0)
        merged = merge_nullable_fields_into_canonical(canonical, [dupe])
        self.assertEqual(merged["liabilities_total"], 500.0)

    def test_material_diff_reported_without_merge(self) -> None:
        canonical = _row(row_id="keep", captured_at="2026-08-13T18:00:00+00:00", priced_market_value=1100.0)
        dupe = _row(row_id="drop", captured_at="2026-08-13T10:00:00+00:00", priced_market_value=1000.0)
        diffs = nullable_field_diffs(canonical, dupe)
        self.assertIn("priced_market_value", diffs)


class SnapshotRepositoryUpsertTests(unittest.TestCase):
    def test_upsert_uses_portfolio_date_conflict(self) -> None:
        client = MagicMock()
        repo = WealthPortfolioSnapshotRepository(client)
        table = client.table.return_value
        upsert = table.upsert.return_value
        upsert.execute.return_value.data = [{"id": "snap-1"}]
        payload = {
            "portfolio_id": "pf-1",
            "snapshot_date": "2026-08-13",
            "user_id": "user-a",
        }
        row = repo.upsert_for_portfolio_date(payload)
        self.assertEqual(row["id"], "snap-1")
        table.upsert.assert_called_once_with(payload, on_conflict="portfolio_id,snapshot_date")

    def test_find_for_portfolio_on_date_queries_snapshot_date(self) -> None:
        client = MagicMock()
        repo = WealthPortfolioSnapshotRepository(client)
        chain = client.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value.execute.return_value.data = [{"id": "snap-1"}]
        found = repo.find_for_portfolio_on_date("user-a", "pf-1", date(2026, 8, 13))
        self.assertEqual(found["id"], "snap-1")
        chain.eq.assert_any_call("snapshot_date", "2026-08-13")


class Wave4SnapshotMigrationSqlTests(unittest.TestCase):
    MIGRATION_PATH = Path("database/migration_wave4_wealth_os.sql")

    def test_migration_contains_dedupe_before_unique_index(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        dedupe_pos = sql.index("delete from public.wealth_portfolio_snapshots")
        unique_pos = sql.index("create unique index if not exists wealth_portfolio_snapshots_portfolio_date_uidx")
        self.assertLess(dedupe_pos, unique_pos)

    def test_migration_is_idempotent_friendly(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        self.assertIn("create table if not exists public.fx_rates", sql)
        self.assertIn("add column if not exists snapshot_date", sql)
        self.assertIn("create unique index if not exists wealth_portfolio_snapshots_portfolio_date_uidx", sql)
        self.assertIn("drop policy if exists", sql)

    def test_migration_documents_duplicate_detection_query(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        self.assertIn("group by portfolio_id, snapshot_date", sql)
        self.assertIn("having count(*) > 1", sql)

    def test_migration_adds_snapshot_update_policy(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn('"wealth portfolio snapshots update own"', sql)
        self.assertIn("for update to authenticated", sql.lower())

    def test_no_fk_references_to_portfolio_snapshots_in_migrations(self) -> None:
        database = Path("database")
        for path in database.glob("migration*.sql"):
            text = path.read_text(encoding="utf-8").lower()
            if path.name == "migration_wave4_wealth_os.sql":
                continue
            self.assertNotIn(
                "references public.wealth_portfolio_snapshots",
                text,
                msg=f"unexpected FK to wealth_portfolio_snapshots in {path.name}",
            )


if __name__ == "__main__":
    unittest.main()
