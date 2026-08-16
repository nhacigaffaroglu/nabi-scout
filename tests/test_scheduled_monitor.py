from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from repositories.monitor_run_repository import MonitorRunRepository
from services.monitor_refresh_service import evaluate_scheduled_monitor_run


class MonitorSchedulerTests(unittest.TestCase):
    def test_blocks_second_scheduled_run_same_day(self) -> None:
        store: dict[str, dict] = {}
        repo = MonitorRunRepository(MagicMock())
        repo.get_by_run_id = lambda run_id: store.get(run_id)
        repo.create_running = lambda **kwargs: store.setdefault(
            kwargs["run_id"],
            {"run_id": kwargs["run_id"], "status": "RUNNING"},
        )
        first = evaluate_scheduled_monitor_run(repo, run_date="2026-08-16", trigger_type="scheduled")
        store[first["run_id"]]["status"] = "COMPLETED"
        second = evaluate_scheduled_monitor_run(repo, run_date="2026-08-16", trigger_type="scheduled")
        self.assertFalse(first["skipped"])
        self.assertTrue(second["skipped"])

    def test_allow_second_run_override(self) -> None:
        repo = MonitorRunRepository(MagicMock())
        repo.get_by_run_id = MagicMock(
            return_value={"run_id": "monitor-2026-08-16-scheduled", "status": "COMPLETED"}
        )
        repo.create_running = MagicMock(return_value={"run_id": "monitor-2026-08-16-scheduled-override"})
        result = evaluate_scheduled_monitor_run(
            repo,
            run_date="2026-08-16",
            trigger_type="scheduled",
            allow_second_run_today=True,
        )
        self.assertFalse(result["skipped"])
        self.assertIn("override", result["run_id"])


class MonitorWorkflowContractTests(unittest.TestCase):
    def test_daily_monitor_workflow(self) -> None:
        path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily_monitor.yml"
        content = path.read_text(encoding="utf-8")
        self.assertIn("concurrency:", content)
        self.assertIn("cancel-in-progress: false", content)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", content)
        self.assertIn("workflow_dispatch", content)
        self.assertIn('cron: "30 7 * * *"', content)
        self.assertIn("run_daily_monitor_refresh.py", content)
        self.assertNotIn("OPENAI", content)
        self.assertNotIn("sb_publishable_", content)

    def test_monitor_script_has_no_llm(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts" / "run_daily_monitor_refresh.py"
        content = path.read_text(encoding="utf-8")
        lowered = content.lower()
        for forbidden in (
            "wealthadviserllmclient",
            "portfolio_ai_adviser",
            "openai",
            "fmpclient",
            "secfinancialclient",
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertIn("LLM calls:", content)
        self.assertIn("FMP calls:", content)
        self.assertIn("SEC calls:", content)

    def test_migration_contract(self) -> None:
        path = Path(__file__).resolve().parents[1] / "database" / "migration_monitor_wave2.sql"
        sql = path.read_text(encoding="utf-8")
        self.assertIn("monitor_events_dedupe_key_uidx", sql)
        self.assertIn("portfolio_ai_adviser_snapshots_identity_uidx", sql)
        self.assertIn("enable row level security", sql.lower())
        self.assertIn("PRE-DEPLOY MIGRATION REQUIRED", sql)


if __name__ == "__main__":
    unittest.main()
