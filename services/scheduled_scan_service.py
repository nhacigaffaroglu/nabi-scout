from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple

from services.scan_universe_service import scheduled_universe_name

STALE_RUNNING_AFTER = timedelta(hours=2)


def stale_running_cutoff(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current - STALE_RUNNING_AFTER


def evaluate_scheduled_run(
    scan_repo,
    run_date: Optional[date] = None,
    *,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], Optional[dict]]:
    current = now or datetime.now(timezone.utc)
    target_date = run_date or current.date()
    universe_name = scheduled_universe_name(target_date)
    existing = scan_repo.get_run_by_universe_name(universe_name)

    if not existing:
        return True, None, None

    status = existing.get("status")
    if status == "COMPLETED":
        return False, f"Daily scan already completed for {target_date.isoformat()}.", existing

    if status == "FAILED":
        return True, None, existing

    if status == "RUNNING":
        started_at = existing.get("started_at")
        if started_at:
            try:
                started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            except ValueError:
                started = None
        else:
            started = None

        if started is not None and started >= stale_running_cutoff(current):
            return False, f"Daily scan already running for {target_date.isoformat()}.", existing

    return True, None, existing
