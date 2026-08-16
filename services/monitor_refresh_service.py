from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from repositories.monitor_run_repository import MonitorRunRepository
from services.monitor_intelligence_service import MonitorIntelligenceService


def evaluate_scheduled_monitor_run(
    repo: MonitorRunRepository,
    *,
    run_date: Optional[str] = None,
    trigger_type: str = "scheduled",
    allow_second_run_today: bool = False,
) -> Dict[str, Any]:
    today = run_date or date.today().isoformat()
    run_id = f"monitor-{today}-{trigger_type}"
    existing = repo.get_by_run_id(run_id)
    if existing and existing.get("status") == "COMPLETED" and not allow_second_run_today:
        return {
            "run_id": run_id,
            "skipped": True,
            "reason": "already_completed",
            "existing": existing,
        }
    if existing is None or (existing.get("status") == "COMPLETED" and allow_second_run_today):
        if existing is None:
            repo.create_running(run_id=run_id, run_date=today, trigger_type=trigger_type)
        else:
            repo.create_running(run_id=f"{run_id}-override", run_date=today, trigger_type=trigger_type)
            run_id = f"{run_id}-override"
    return {"run_id": run_id, "skipped": False, "run_date": today}


def finish_monitor_run(
    repo: MonitorRunRepository,
    *,
    run_id: str,
    events_created: int,
    events_skipped: int,
    report_payload: Dict[str, Any],
    status: str = "COMPLETED",
) -> Dict[str, Any]:
    return repo.finish(
        run_id,
        status=status,
        events_created=events_created,
        events_skipped=events_skipped,
        report_payload=report_payload,
    )
