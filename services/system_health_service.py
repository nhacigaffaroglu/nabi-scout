from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Dict, List, Optional


JOB_LABELS = {
    "daily_scan": "Günlük Tarama",
    "daily_fx_refresh": "FX Yenileme",
    "daily_universe_expansion": "Evren Genişletme",
    "daily_fund_holdings_refresh": "Fon Holding Yenileme",
    "daily_monitor_refresh": "Monitör Yenileme",
    "daily_wealth_snapshot": "Servet Snapshot",
}


@dataclass(frozen=True)
class AutomationHealthRow:
    job_name: str
    label: str
    run_date: Optional[str]
    status: Optional[str]
    records_updated: Optional[int]
    provider_calls: Optional[int]
    finished_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SystemHealthService:
    """Read-only automation health from persisted run ledgers."""

    TABLE = "wealth_automation_runs"

    def __init__(self, client) -> None:
        self.client = client

    def list_automation_health(self, *, limit_per_job: int = 3) -> List[AutomationHealthRow]:
        rows: List[AutomationHealthRow] = []
        for job_name, label in JOB_LABELS.items():
            latest = self._latest_run(job_name)
            rows.append(
                AutomationHealthRow(
                    job_name=job_name,
                    label=label,
                    run_date=str(latest.get("run_date") or "") or None if latest else None,
                    status=str(latest.get("status") or "") or None if latest else None,
                    records_updated=int(latest.get("records_updated") or 0) if latest else None,
                    provider_calls=int(latest.get("provider_calls") or 0) if latest else None,
                    finished_at=str(latest.get("finished_at") or "") or None if latest else None,
                )
            )
        return rows

    def _latest_run(self, job_name: str) -> Optional[Dict[str, Any]]:
        try:
            response = (
                self.client.table(self.TABLE)
                .select("*")
                .eq("job_name", job_name)
                .order("run_date", desc=True)
                .limit(1)
                .execute()
            )
        except Exception:
            return None
        data = response.data or []
        return data[0] if data else None

    def last_successful_run(self, job_name: str) -> Optional[Dict[str, Any]]:
        try:
            response = (
                self.client.table(self.TABLE)
                .select("*")
                .eq("job_name", job_name)
                .eq("status", "COMPLETED")
                .order("run_date", desc=True)
                .limit(1)
                .execute()
            )
        except Exception:
            return None
        data = response.data or []
        return data[0] if data else None
