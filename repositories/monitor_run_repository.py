from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class MonitorRunRepository:
    TABLE = "monitor_runs"

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_by_run_id(self, run_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("run_id", run_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def create_running(self, *, run_id: str, run_date: str, trigger_type: str) -> Dict[str, Any]:
        payload = {
            "run_id": run_id,
            "run_date": run_date,
            "trigger_type": trigger_type,
            "status": "RUNNING",
            "started_at": self._now_iso(),
            "updated_at": self._now_iso(),
        }
        response = self.client.table(self.TABLE).insert(payload).execute()
        rows = response.data or []
        return rows[0] if rows else payload

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        events_created: int,
        events_skipped: int,
        report_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = {
            "status": status,
            "events_created": events_created,
            "events_skipped": events_skipped,
            "report_payload": report_payload,
            "finished_at": self._now_iso(),
            "updated_at": self._now_iso(),
        }
        response = (
            self.client.table(self.TABLE)
            .update(payload)
            .eq("run_id", run_id)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else payload
