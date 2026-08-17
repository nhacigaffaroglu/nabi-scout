from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_COMPLETED = "COMPLETED"
RUN_STATUS_SKIPPED = "SKIPPED"
RUN_STATUS_FAILED = "FAILED"

TRIGGER_SCHEDULED = "scheduled"
TRIGGER_MANUAL = "manual"
TRIGGER_WORKFLOW_DISPATCH = "workflow_dispatch"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_missing_runs_table_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "universe_expansion_runs" in message and (
        "pgrst205" in message
        or "could not find the table" in message
        or "schema cache" in message
    )


class UniverseExpansionRunRepository:
    TABLE = "universe_expansion_runs"

    def __init__(self, client=None) -> None:
        self.client = client
        self._memory: List[Dict[str, Any]] = []
        self.ledger_available = True

    def _disable_ledger(self, exc: BaseException) -> None:
        if is_missing_runs_table_error(exc):
            self.ledger_available = False
            return
        raise exc

    def start_run(
        self,
        *,
        run_id: str,
        run_date: date,
        trigger_type: str,
        dry_run: bool,
        allow_second_run_today: bool,
        started_at: datetime,
    ) -> Dict[str, Any]:
        payload = {
            "id": str(uuid4()),
            "run_id": run_id,
            "run_date": run_date.isoformat(),
            "trigger_type": trigger_type,
            "dry_run": dry_run,
            "allow_second_run_today": allow_second_run_today,
            "status": RUN_STATUS_RUNNING,
            "started_at": started_at.isoformat(),
            "updated_at": started_at.isoformat(),
        }
        if self.client is None:
            self._memory.append(dict(payload))
            return payload
        if not self.ledger_available:
            self._memory.append(dict(payload))
            return payload
        try:
            response = self.client.table(self.TABLE).insert(payload).execute()
        except Exception as exc:
            self._disable_ledger(exc)
            self._memory.append(dict(payload))
            return payload
        return response.data[0] if response.data else payload

    def finalize_run(
        self,
        run_id: str,
        *,
        status: str,
        stop_reason: str,
        report: Dict[str, Any],
        finished_at: datetime,
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "status": status,
            "stop_reason": stop_reason or None,
            "symbols_considered": int(report.get("symbols_considered") or 0),
            "symbols_started": int(report.get("symbols_started") or 0),
            "symbols_completed": int(report.get("symbols_completed") or 0),
            "symbols_retryable": int(report.get("symbols_retryable") or 0),
            "symbols_blocked": int(report.get("symbols_blocked") or 0),
            "symbols_skipped": int(report.get("symbols_skipped") or 0),
            "fmp_calls_used": int(report.get("fmp_calls_used") or 0),
            "sec_calls_used": int(report.get("sec_calls_used") or 0),
            "report_payload": report,
            "finished_at": finished_at.isoformat(),
            "updated_at": finished_at.isoformat(),
        }
        if self.client is None:
            for index, row in enumerate(self._memory):
                if row.get("run_id") == run_id:
                    merged = {**row, **payload}
                    self._memory[index] = merged
                    return merged
            return None
        if not self.ledger_available:
            for index, row in enumerate(self._memory):
                if row.get("run_id") == run_id:
                    merged = {**row, **payload}
                    self._memory[index] = merged
                    return merged
            return None
        try:
            response = (
                self.client.table(self.TABLE)
                .update(payload)
                .eq("run_id", run_id)
                .execute()
            )
        except Exception as exc:
            self._disable_ledger(exc)
            return None
        return response.data[0] if response.data else None

    def list_for_date(self, run_date: date) -> List[Dict[str, Any]]:
        if self.client is None or not self.ledger_available:
            target = run_date.isoformat()
            return [row for row in self._memory if row.get("run_date") == target]
        try:
            response = (
                self.client.table(self.TABLE)
                .select("*")
                .eq("run_date", run_date.isoformat())
                .order("started_at", desc=True)
                .execute()
            )
        except Exception as exc:
            self._disable_ledger(exc)
            return []
        return response.data or []

    def get_latest_completed_paid_run(self, run_date: date) -> Optional[Dict[str, Any]]:
        for row in self.list_for_date(run_date):
            if row.get("dry_run"):
                continue
            if row.get("status") != RUN_STATUS_COMPLETED:
                continue
            if int(row.get("symbols_started") or 0) <= 0:
                continue
            return row
        return None

    def get_active_run(self, run_date: date) -> Optional[Dict[str, Any]]:
        for row in self.list_for_date(run_date):
            if row.get("status") == RUN_STATUS_RUNNING:
                return row
        return None
