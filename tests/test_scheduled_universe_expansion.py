from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from repositories.universe_expansion_run_repository import (
    RUN_STATUS_COMPLETED,
    TRIGGER_SCHEDULED,
    UniverseExpansionRunRepository,
)
from services.scheduled_universe_expansion_service import (
    evaluate_scheduled_expansion_run,
    expansion_run_date,
)
from services.universe_expansion_contract import STOP_REASON_ALREADY_RAN_TODAY
from services.universe_expansion_run_report import format_expansion_run_summary


class ScheduledExpansionGuardTests(unittest.TestCase):
    def test_blocks_second_scheduled_run_same_day(self) -> None:
        repo = UniverseExpansionRunRepository()
        run_date = date(2026, 8, 16)
        repo.start_run(
            run_id="run-1",
            run_date=run_date,
            trigger_type=TRIGGER_SCHEDULED,
            dry_run=False,
            allow_second_run_today=False,
            started_at=datetime(2026, 8, 16, 5, 0, tzinfo=timezone.utc),
        )
        repo.finalize_run(
            "run-1",
            status=RUN_STATUS_COMPLETED,
            stop_reason="BUDGET_EXHAUSTED",
            report={"symbols_started": 3, "symbols_completed": 3},
            finished_at=datetime(2026, 8, 16, 5, 10, tzinfo=timezone.utc),
        )
        should_run, reason, _ = evaluate_scheduled_expansion_run(
            repo,
            run_date=run_date,
            trigger_type=TRIGGER_SCHEDULED,
        )
        self.assertFalse(should_run)
        self.assertIn("already completed", reason or "")

    def test_manual_override_permits_second_run(self) -> None:
        repo = UniverseExpansionRunRepository()
        run_date = date(2026, 8, 16)
        repo.start_run(
            run_id="run-1",
            run_date=run_date,
            trigger_type=TRIGGER_SCHEDULED,
            dry_run=False,
            allow_second_run_today=False,
            started_at=datetime(2026, 8, 16, 5, 0, tzinfo=timezone.utc),
        )
        repo.finalize_run(
            "run-1",
            status=RUN_STATUS_COMPLETED,
            stop_reason="SAFETY_CAP",
            report={"symbols_started": 2, "symbols_completed": 2},
            finished_at=datetime(2026, 8, 16, 5, 5, tzinfo=timezone.utc),
        )
        should_run, reason, _ = evaluate_scheduled_expansion_run(
            repo,
            run_date=run_date,
            trigger_type=TRIGGER_SCHEDULED,
            allow_second_run_today=True,
        )
        self.assertTrue(should_run)
        self.assertIsNone(reason)

    def test_dry_run_bypasses_duplicate_guard(self) -> None:
        repo = UniverseExpansionRunRepository()
        run_date = date(2026, 8, 16)
        repo.start_run(
            run_id="run-1",
            run_date=run_date,
            trigger_type=TRIGGER_SCHEDULED,
            dry_run=False,
            allow_second_run_today=False,
            started_at=datetime(2026, 8, 16, 5, 0, tzinfo=timezone.utc),
        )
        repo.finalize_run(
            "run-1",
            status=RUN_STATUS_COMPLETED,
            stop_reason="SAFETY_CAP",
            report={"symbols_started": 3, "symbols_completed": 3},
            finished_at=datetime(2026, 8, 16, 5, 5, tzinfo=timezone.utc),
        )
        should_run, _, _ = evaluate_scheduled_expansion_run(
            repo,
            run_date=run_date,
            dry_run=True,
        )
        self.assertTrue(should_run)

    def test_istanbul_run_date(self) -> None:
        # 2026-08-16 04:30 UTC -> still previous Istanbul day
        early = datetime(2026, 8, 16, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(expansion_run_date(early), date(2026, 8, 16))
        late = datetime(2026, 8, 16, 5, 30, tzinfo=timezone.utc)
        self.assertEqual(expansion_run_date(late), date(2026, 8, 16))


class SchedulerCliTests(unittest.TestCase):
    def test_headless_secret_validation_blocks_publishable_only(self) -> None:
        from scripts import run_daily_universe_expansion as module

        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "sb_publishable_test",
                "FMP_API_KEY": "fmp",
                "SEC_CONTACT_EMAIL": "sec@example.com",
            },
            clear=True,
        ):
            with self.assertRaises(Exception):
                module._validate_headless_secrets()

    def test_resolve_max_symbols_from_config(self) -> None:
        from scripts import run_daily_universe_expansion as module

        config = UniverseExpansionBudgetConfig(max_symbols_per_run=25)
        self.assertEqual(module._resolve_max_symbols(None, config), 25)
        self.assertEqual(module._resolve_max_symbols(5, config), 5)

    def test_secret_free_report(self) -> None:
        summary = format_expansion_run_summary(
            {
                "run_id": "abc",
                "dry_run": False,
                "stop_reason": "BUDGET_EXHAUSTED",
                "symbols_started": 2,
                "symbols_completed": 2,
                "fmp_calls_used": 4,
                "sec_calls_used": 3,
                "cache_hits": {"sec:company_submissions": 1},
                "budget_remaining": {"fmp": 240, "sec": 490},
                "queue_counts": {"PENDING": 110, "COMPLETED": 6},
            },
            trigger="scheduled",
        )
        lowered = summary.lower()
        for token in ("api_key", "authorization", "bearer", "password", "service_role"):
            self.assertNotIn(token, lowered)


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_has_concurrency_and_service_role(self) -> None:
        path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily_universe_expansion.yml"
        content = path.read_text(encoding="utf-8")
        self.assertIn("concurrency:", content)
        self.assertIn("cancel-in-progress: false", content)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", content)
        self.assertIn("workflow_dispatch", content)
        self.assertIn('cron: "0 5 * * *"', content)
        self.assertNotIn("sb_secret_", content)
        self.assertNotIn("sb_publishable_", content)

    def test_runs_migration_contract(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "database"
            / "migration_universe_expansion_runs.sql"
        )
        sql = path.read_text(encoding="utf-8")
        self.assertIn("universe_expansion_runs", sql)
        self.assertIn("run_date", sql)
        self.assertIn("trigger_type", sql)
        self.assertIn("PRE-DEPLOY MIGRATION REQUIRED", sql)


if __name__ == "__main__":
    unittest.main()
