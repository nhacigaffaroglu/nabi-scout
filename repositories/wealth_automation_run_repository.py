from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional


class WealthAutomationRunRepository:
    TABLE = "wealth_automation_runs"

    def __init__(self, client) -> None:
        self.client = client

    def try_start_run(
        self,
        *,
        job_name: str,
        run_date: date,
        trigger_type: str = "scheduled",
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "job_name": job_name,
            "run_date": run_date.isoformat(),
            "trigger_type": trigger_type,
            "status": "RUNNING",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            response = self.client.table(self.TABLE).insert(payload).execute()
            rows = response.data or []
            return rows[0] if rows else None
        except Exception:
            return None

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        records_updated: int = 0,
        provider_calls: int = 0,
        report_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.client.table(self.TABLE).update(
            {
                "status": status,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "records_updated": records_updated,
                "provider_calls": provider_calls,
                "report_payload": report_payload or {},
            }
        ).eq("id", run_id).execute()

    def get_run(
        self,
        *,
        job_name: str,
        run_date: date,
        trigger_type: str = "scheduled",
    ) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("job_name", job_name)
            .eq("run_date", run_date.isoformat())
            .eq("trigger_type", trigger_type)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None
