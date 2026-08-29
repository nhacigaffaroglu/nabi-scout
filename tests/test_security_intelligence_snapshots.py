from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
)
from services.security_intelligence_contract import (
    ENGINE_VERSION,
    FACTS_VERSION,
    SecurityFacts,
    SecurityParticipationContext,
    snapshot_from_view,
)
from services.security_intelligence_engine import (
    compare_snapshots,
    evaluate_security_intelligence,
)
from services.security_intelligence_snapshot_service import (
    as_of_key,
    canonicalize_as_of,
    load_previous_for_evaluation,
    may_persist_view,
    payloads_semantically_equal,
    save_security_intelligence_snapshot,
    snapshot_from_row,
    snapshot_row_from_view,
)


MIGRATION = Path("database/migration_security_intelligence_snapshots.sql")
PAGE = Path("pages/4_Company_Report.py")
FACADE = Path("services/nabi_intelligence_facade.py")


class _FakeRepo:
    def __init__(self) -> None:
        self.rows: Dict[tuple, Dict[str, Any]] = {}
        self.upserts = 0

    def _key(self, payload: Dict[str, Any]) -> tuple:
        return (
            payload["symbol"],
            payload["as_of_key"],
            payload["facts_version"],
            payload["engine_version"],
        )

    def upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.upserts += 1
        stored = dict(payload)
        stored.setdefault("id", f"id-{len(self.rows)+1}")
        self.rows[self._key(payload)] = stored
        return stored

    def get_by_identity(
        self,
        symbol: str,
        *,
        as_of_key: str,
        facts_version: str,
        engine_version: str,
    ) -> Optional[Dict[str, Any]]:
        return self.rows.get((symbol, as_of_key, facts_version, engine_version))

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        matches = [
            row
            for row in self.rows.values()
            if row.get("symbol") == symbol
        ]
        matches.sort(key=lambda row: str(row.get("as_of") or ""), reverse=True)
        return matches[0] if matches else None

    def get_recent_history(self, symbol: str, *, limit: int = 10):
        matches = [row for row in self.rows.values() if row.get("symbol") == symbol]
        matches.sort(key=lambda row: str(row.get("as_of") or ""), reverse=True)
        return matches[:limit]

    def get_previous(
        self,
        symbol: str,
        *,
        before_as_of: Optional[str] = None,
        exclude_id: Optional[str] = None,
        facts_version: Optional[str] = None,
        engine_version: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        before = str(before_as_of or "")
        for row in self.get_recent_history(symbol, limit=25):
            if exclude_id and row.get("id") == exclude_id:
                continue
            if facts_version and row.get("facts_version") != facts_version:
                continue
            if engine_version and row.get("engine_version") != engine_version:
                continue
            as_of = str(row.get("as_of") or "")
            if before and as_of >= before:
                continue
            return row
        return None


def _view(**overrides):
    payload = dict(
        symbol="CRM",
        roic=18,
        roe=20,
        roa=9,
        revenue_cagr_3y=12,
        eps_cagr_3y=14,
        fcf_cagr_3y=10,
        operating_margin=18,
        fcf_margin=14,
        net_margin=12,
        gross_margin=75,
        pe=30,
        price_to_sales=6,
        price_to_book=5,
        debt_to_equity=0.3,
        net_debt_to_fcf=0.4,
        current_ratio=1.2,
        interest_coverage=20,
        price=250,
        market_cap=200_000_000_000,
        revenue=30_000_000_000,
        free_cash_flow=8_000_000_000,
        as_of="2026-01-31",
    )
    payload.update(overrides)
    return evaluate_security_intelligence(
        SecurityFacts(**payload),
        SecurityParticipationContext(
            status=PARTICIPATION_STATUS_UYGUN,
            research_allowed=True,
        ),
    )


class MigrationContractTests(unittest.TestCase):
    def test_migration_is_additive(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("create table if not exists", sql)
        self.assertIn("unique (symbol, as_of_key, facts_version, engine_version)", sql)
        self.assertIn("security_intelligence_snapshots_symbol_as_of_idx", sql)
        self.assertNotIn("drop table", sql.lower())
        self.assertNotIn("truncate", sql.lower())
        self.assertIn("facts_version", sql)
        self.assertIn("engine_version", sql)
        self.assertIn("as_of_key", sql)


class SnapshotIdempotencyTests(unittest.TestCase):
    def test_identical_replay_skips_write(self) -> None:
        repo = _FakeRepo()
        view = _view()
        first = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        second = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        self.assertTrue(first.saved)
        self.assertTrue(second.skipped_duplicate)
        self.assertFalse(second.saved)
        self.assertEqual(len(repo.rows), 1)
        self.assertEqual(repo.upserts, 1)
        self.assertEqual(as_of_key("2026-01-31"), "2026-01-31")

    def test_runtime_timestamp_difference_skips_write(self) -> None:
        repo = _FakeRepo()
        view = _view()
        first = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        stored = repo.get_latest("CRM")
        assert stored is not None
        stored["created_at"] = "2026-08-01T00:00:00+00:00"
        stored["updated_at"] = "2026-08-29T12:34:56+00:00"
        stored["id"] = "208751a8-c403-44a1-b8a0-7e8b61ac6d4a"
        second = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        self.assertTrue(first.saved)
        self.assertTrue(second.skipped_duplicate)
        self.assertFalse(second.saved)
        self.assertEqual(repo.upserts, 1)
        self.assertEqual(second.row["id"], "208751a8-c403-44a1-b8a0-7e8b61ac6d4a")

    def test_midnight_timestamptz_as_of_skips_write(self) -> None:
        repo = _FakeRepo()
        view = _view()
        first = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        stored = repo.get_latest("CRM")
        assert stored is not None
        stored["as_of"] = "2026-01-31T00:00:00+00:00"
        stored["overall_score"] = Decimal(str(stored["overall_score"]))
        second = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        self.assertTrue(first.saved)
        self.assertTrue(second.skipped_duplicate)
        self.assertEqual(repo.upserts, 1)
        self.assertEqual(canonicalize_as_of("2026-01-31T00:00:00+00:00"), "2026-01-31")
        self.assertTrue(
            payloads_semantically_equal(
                stored,
                snapshot_row_from_view(view, as_of="2026-01-31"),
            )
        )

    def test_stable_json_ordering_skips_write(self) -> None:
        repo = _FakeRepo()
        view = _view()
        first = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        stored = repo.get_latest("CRM")
        assert stored is not None
        stored["dimension_scores"] = {
            key: stored["dimension_scores"][key]
            for key in reversed(list(stored["dimension_scores"]))
        }
        stored["data_quality"] = {
            key: stored["data_quality"][key]
            for key in reversed(list(stored["data_quality"]))
        }
        second = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        self.assertTrue(first.saved)
        self.assertTrue(second.skipped_duplicate)
        self.assertEqual(repo.upserts, 1)

    def test_genuine_score_change_upserts_then_replay_skips(self) -> None:
        repo = _FakeRepo()
        view = _view()
        first = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        changed = replace(view, overall_score=round((view.overall_score or 50.0) + 1.0, 1))
        updated = save_security_intelligence_snapshot(repo, changed, as_of="2026-01-31")
        replay = save_security_intelligence_snapshot(repo, changed, as_of="2026-01-31")
        self.assertTrue(first.saved)
        self.assertTrue(updated.saved)
        self.assertFalse(updated.skipped_duplicate)
        self.assertTrue(replay.skipped_duplicate)
        self.assertFalse(replay.saved)
        self.assertEqual(len(repo.rows), 1)
        self.assertEqual(repo.upserts, 2)

    def test_participation_change_upserts(self) -> None:
        repo = _FakeRepo()
        view = _view()
        save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        changed = replace(
            view,
            participation_status=PARTICIPATION_STATUS_KONTROL_ET,
            research_allowed=False,
        )
        updated = save_security_intelligence_snapshot(repo, changed, as_of="2026-01-31")
        replay = save_security_intelligence_snapshot(repo, changed, as_of="2026-01-31")
        self.assertTrue(updated.saved)
        self.assertTrue(replay.skipped_duplicate)
        self.assertEqual(len(repo.rows), 1)
        self.assertEqual(repo.upserts, 2)

    def test_data_quality_semantic_change_upserts(self) -> None:
        repo = _FakeRepo()
        view = _view()
        save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        changed = replace(
            view,
            data_quality=replace(
                view.data_quality,
                score=0.0 if (view.data_quality.score or 0) > 0 else 12.0,
                status="INSUFFICIENT_DATA",
            ),
        )
        updated = save_security_intelligence_snapshot(repo, changed, as_of="2026-01-31")
        replay = save_security_intelligence_snapshot(repo, changed, as_of="2026-01-31")
        self.assertTrue(updated.saved)
        self.assertTrue(replay.skipped_duplicate)
        self.assertEqual(repo.upserts, 2)

    def test_engine_version_creates_separate_row(self) -> None:
        repo = _FakeRepo()
        view = _view()
        first = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        other = replace(view, engine_version="security_intelligence_8c.1-test")
        second = save_security_intelligence_snapshot(repo, other, as_of="2026-01-31")
        replay = save_security_intelligence_snapshot(repo, other, as_of="2026-01-31")
        self.assertTrue(first.saved)
        self.assertTrue(second.saved)
        self.assertTrue(replay.skipped_duplicate)
        self.assertEqual(len(repo.rows), 2)
        self.assertEqual(repo.upserts, 2)
        self.assertNotEqual(first.row["engine_version"], second.row["engine_version"])

    def test_facts_version_creates_separate_row(self) -> None:
        repo = _FakeRepo()
        view = _view()
        first = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        other = replace(view, facts_version="security_facts_8c.1-test")
        second = save_security_intelligence_snapshot(repo, other, as_of="2026-01-31")
        replay = save_security_intelligence_snapshot(repo, other, as_of="2026-01-31")
        self.assertTrue(first.saved)
        self.assertTrue(second.saved)
        self.assertTrue(replay.skipped_duplicate)
        self.assertEqual(len(repo.rows), 2)
        self.assertEqual(repo.upserts, 2)
        self.assertNotEqual(first.row["facts_version"], second.row["facts_version"])

    def test_engine_and_facts_versions_do_not_overwrite(self) -> None:
        repo = _FakeRepo()
        view = _view()
        save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        other = snapshot_row_from_view(view, as_of="2026-01-31")
        other["engine_version"] = "security_intelligence_8a.1"
        repo.upsert(other)
        self.assertEqual(len(repo.rows), 2)
        latest = repo.get_latest("CRM")
        self.assertIsNotNone(latest)

    def test_latest_and_previous_retrieval(self) -> None:
        repo = _FakeRepo()
        first = _view()
        second = evaluate_security_intelligence(
            SecurityFacts(
                symbol="CRM",
                roic=10,
                roe=12,
                roa=5,
                revenue_cagr_3y=4,
                eps_cagr_3y=4,
                fcf_cagr_3y=4,
                operating_margin=10,
                fcf_margin=8,
                net_margin=6,
                gross_margin=60,
                pe=40,
                price_to_sales=8,
                price_to_book=7,
                debt_to_equity=0.6,
                net_debt_to_fcf=1.2,
                current_ratio=1.1,
                interest_coverage=8,
                as_of="2026-06-30",
            ),
            SecurityParticipationContext(
                status=PARTICIPATION_STATUS_UYGUN,
                research_allowed=True,
            ),
        )
        save_security_intelligence_snapshot(repo, first, as_of="2026-01-31")
        save_security_intelligence_snapshot(repo, second, as_of="2026-06-30")
        prev = load_previous_for_evaluation(
            repo,
            "CRM",
            as_of="2026-06-30",
            facts_version=FACTS_VERSION,
            engine_version=ENGINE_VERSION,
        )
        self.assertIsNotNone(prev)
        self.assertEqual(prev.as_of, "2026-01-31")

    def test_sparse_view_is_not_persistable(self) -> None:
        view = evaluate_security_intelligence(SecurityFacts(symbol="TSLA", price=340))
        self.assertFalse(may_persist_view(view, completeness_pct=9.5))
        result = save_security_intelligence_snapshot(
            _FakeRepo(), view, require_sufficient=True, completeness_pct=9.5
        )
        self.assertTrue(result.insufficient)
        self.assertFalse(result.saved)

    def test_same_data_replay_has_no_change_flags(self) -> None:
        first = _view()
        snap = snapshot_from_view(first, as_of="2026-01-31")
        again = evaluate_security_intelligence(
            SecurityFacts(
                symbol="CRM",
                roic=18,
                roe=20,
                roa=9,
                revenue_cagr_3y=12,
                eps_cagr_3y=14,
                fcf_cagr_3y=10,
                operating_margin=18,
                fcf_margin=14,
                net_margin=12,
                gross_margin=75,
                pe=30,
                price_to_sales=6,
                price_to_book=5,
                debt_to_equity=0.3,
                net_debt_to_fcf=0.4,
                current_ratio=1.2,
                interest_coverage=20,
                price=250,
                market_cap=200_000_000_000,
                revenue=30_000_000_000,
                free_cash_flow=8_000_000_000,
                as_of="2026-01-31",
            ),
            SecurityParticipationContext(
                status=PARTICIPATION_STATUS_UYGUN,
                research_allowed=True,
            ),
            previous=snap,
        )
        self.assertEqual(again.change_flags, ())

    def test_missing_to_populated_is_data_quality_only(self) -> None:
        sparse = evaluate_security_intelligence(SecurityFacts(symbol="CRM", price=250))
        filled = evaluate_security_intelligence(
            SecurityFacts(
                symbol="CRM",
                roic=18,
                roe=20,
                roa=9,
                revenue_cagr_3y=12,
                operating_margin=18,
                pe=20,
                debt_to_equity=0.3,
                current_ratio=1.2,
                price=250,
                market_cap=1,
                revenue=1,
                free_cash_flow=1,
            ),
            SecurityParticipationContext(
                status=PARTICIPATION_STATUS_KONTROL_ET, research_allowed=False
            ),
            previous=snapshot_from_view(sparse, as_of="2025-01-01"),
        )
        self.assertIn("DATA_QUALITY_CHANGED", filled.change_flags)
        self.assertNotIn("QUALITY_IMPROVING", filled.change_flags)

    def test_change_detection_from_persisted_history(self) -> None:
        repo = _FakeRepo()
        earlier = _view()
        save_security_intelligence_snapshot(repo, earlier, as_of="2026-01-31")
        previous = snapshot_from_row(repo.get_latest("CRM"))
        later = evaluate_security_intelligence(
            SecurityFacts(
                symbol="CRM",
                roic=8,
                roe=9,
                roa=3,
                revenue_cagr_3y=-4,
                eps_cagr_3y=-2,
                fcf_cagr_3y=-1,
                operating_margin=8,
                fcf_margin=6,
                net_margin=4,
                gross_margin=50,
                pe=45,
                price_to_sales=9,
                price_to_book=8,
                debt_to_equity=1.4,
                net_debt_to_fcf=3,
                current_ratio=0.9,
                interest_coverage=3,
                as_of="2026-06-30",
            ),
            SecurityParticipationContext(
                status=PARTICIPATION_STATUS_KONTROL_ET,
                research_allowed=False,
            ),
            previous=previous,
        )
        self.assertTrue(later.change_flags)
        self.assertTrue(
            any(
                flag in later.change_flags
                for flag in ("GROWTH_SLOWING", "PARTICIPATION_CHANGED", "QUALITY_DETERIORATING")
            )
        )
        self.assertEqual(compare_snapshots(None, snapshot_from_view(later)), ())

    def test_consumers_read_snapshot_and_keep_live_evaluate(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        facade = FACADE.read_text(encoding="utf-8")
        self.assertIn("load_previous_for_evaluation", page)
        self.assertIn("SecurityIntelligenceService", page)
        self.assertIn("get_latest", facade)
        self.assertIn("SecurityIntelligenceService", facade)
        self.assertIn("SignalIntelligenceService", page)
        self.assertIn("signal_context", facade)
        self.assertNotIn(".insert(", facade)
        self.assertNotIn("nabi_score_v4", facade)
        ui = Path("components/security_intelligence_ui.py").read_text(encoding="utf-8")
        self.assertIn("Canlı evaluate()", ui)


if __name__ == "__main__":
    unittest.main()
