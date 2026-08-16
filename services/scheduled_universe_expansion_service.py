from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from repositories.universe_expansion_run_repository import (
    RUN_STATUS_RUNNING,
    UniverseExpansionRunRepository,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")
STALE_RUNNING_AFTER = timedelta(hours=2)


def expansion_run_date(now: Optional[datetime] = None) -> date:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(ISTANBUL).date()


def stale_running_cutoff(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current - STALE_RUNNING_AFTER


def evaluate_scheduled_expansion_run(
    run_repo: UniverseExpansionRunRepository,
    *,
    run_date: Optional[date] = None,
    now: Optional[datetime] = None,
    dry_run: bool = False,
    allow_second_run_today: bool = False,
    trigger_type: str = "scheduled",
) -> Tuple[bool, Optional[str], Optional[dict]]:
    current = now or datetime.now(timezone.utc)
    target_date = run_date or expansion_run_date(current)

    if dry_run:
        return True, None, None

    if not allow_second_run_today:
        completed = run_repo.get_latest_completed_paid_run(target_date)
        if completed is not None and trigger_type in {"scheduled", "workflow_dispatch"}:
            return (
                False,
                f"Universe expansion already completed for {target_date.isoformat()}.",
                completed,
            )

    active = run_repo.get_active_run(target_date)
    if active is not None:
        started_at_raw = active.get("started_at")
        started_at = None
        if started_at_raw:
            try:
                started_at = datetime.fromisoformat(str(started_at_raw).replace("Z", "+00:00"))
            except ValueError:
                started_at = None
        if started_at is None or started_at >= stale_running_cutoff(current):
            return (
                False,
                f"Universe expansion already running for {target_date.isoformat()}.",
                active,
            )

    return True, None, None
