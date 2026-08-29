from __future__ import annotations

import unittest
from typing import Any, Dict, Optional

from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.security_intelligence_contract import (
    ENGINE_VERSION,
    FACTS_VERSION,
    SecurityFacts,
    SecurityParticipationContext,
    snapshot_from_view,
)
from services.security_intelligence_engine import evaluate_security_intelligence
from services.security_intelligence_snapshot_service import (
    as_of_key,
    save_security_intelligence_snapshot,
    snapshot_from_row,
    snapshot_row_from_view,
)


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
        matches = [row for key, row in self.rows.items() if key[0] == symbol]
        return matches[-1] if matches else None


def _view():
    return evaluate_security_intelligence(
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
    )


class SnapshotIdempotencyTests(unittest.TestCase):
    def test_upsert_replay_does_not_duplicate(self) -> None:
        repo = _FakeRepo()
        view = _view()
        first = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        second = save_security_intelligence_snapshot(repo, view, as_of="2026-01-31")
        self.assertTrue(first.saved)
        self.assertTrue(second.skipped_duplicate)
        self.assertEqual(len(repo.rows), 1)
        self.assertEqual(repo.upserts, 2)
        row = next(iter(repo.rows.values()))
        self.assertEqual(row["facts_version"], FACTS_VERSION)
        self.assertEqual(row["engine_version"], ENGINE_VERSION)
        self.assertEqual(as_of_key(row["as_of"]), "2026-01-31")
        restored = snapshot_from_row(row)
        self.assertEqual(restored.symbol, "CRM")
        self.assertEqual(restored.overall_score, view.overall_score)

    def test_dry_run_does_not_write(self) -> None:
        repo = _FakeRepo()
        result = save_security_intelligence_snapshot(
            repo, _view(), as_of="2026-01-31", dry_run=True
        )
        self.assertTrue(result.dry_run)
        self.assertFalse(result.saved)
        self.assertEqual(repo.upserts, 0)
        payload = snapshot_row_from_view(_view(), as_of="2026-01-31")
        self.assertNotIn("sec_financials", payload)
        self.assertNotIn("raw_payload", payload)

    def test_snapshot_from_view_carries_change_contract(self) -> None:
        view = _view()
        snap = snapshot_from_view(view, as_of="2026-01-31")
        self.assertIn("QUALITY", snap.dimension_scores)
        self.assertIn("QUALITY", snap.dimension_statuses)
        self.assertEqual(snap.participation_status, PARTICIPATION_STATUS_UYGUN)


if __name__ == "__main__":
    unittest.main()
