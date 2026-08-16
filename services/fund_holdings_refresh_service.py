from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Set

from repositories.fund_holdings_repository import FundHoldingsRepository
from repositories.wealth_automation_run_repository import WealthAutomationRunRepository
from services.participation_filter_service import PARTICIPATION_UNKNOWN
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)


class FundHoldingsRefreshService:
    """Scheduled fund holdings refresh — not used on page render."""

    JOB_NAME = "daily_fund_holdings_refresh"
    SOURCE = "fmp_etf_holdings"

    def __init__(self, client, fmp_client=None, participation_loader=None) -> None:
        self.repo = FundHoldingsRepository(client)
        self.runs = WealthAutomationRunRepository(client)
        self._fmp = fmp_client
        self._load_participation = participation_loader
        self.provider_calls = 0

    def evaluate_run(
        self,
        *,
        run_date: Optional[date] = None,
        trigger_type: str = "scheduled",
        allow_second_run: bool = False,
    ) -> Dict[str, object]:
        today = run_date or date.today()
        existing = self.runs.get_run(
            job_name=self.JOB_NAME,
            run_date=today,
            trigger_type=trigger_type,
        )
        if existing and not allow_second_run:
            if str(existing.get("status") or "") in {"COMPLETED", "RUNNING"}:
                return {"skipped": True, "reason": "already_run", "run_id": existing.get("id")}
        started = self.runs.try_start_run(
            job_name=self.JOB_NAME,
            run_date=today,
            trigger_type=trigger_type,
        )
        if started is None and not allow_second_run:
            return {"skipped": True, "reason": "concurrent_or_duplicate"}
        return {"skipped": False, "run_id": (started or existing or {}).get("id")}

    def refresh_symbols(self, symbols: Set[str], *, as_of: Optional[date] = None) -> int:
        if self._fmp is None:
            return 0
        updated = 0
        snap_date = as_of or date.today()
        for symbol in sorted(symbols):
            if not symbol:
                continue
            holdings_payload = self._fetch_holdings(symbol)
            if holdings_payload is None:
                continue
            holdings, coverage_pct, underlying_count = holdings_payload
            snap = self.repo.upsert_snapshot(
                fund_symbol=symbol,
                fund_type="etf",
                as_of=snap_date,
                source=self.SOURCE,
                coverage_pct=coverage_pct,
                underlying_count=underlying_count,
            )
            rows = []
            for item in holdings:
                underlying = str(item.get("asset") or item.get("symbol") or "").upper()
                participation = self._participation_for(underlying)
                rows.append(
                    {
                        "snapshot_id": snap["id"],
                        "underlying_symbol": underlying or None,
                        "underlying_name": item.get("name"),
                        "weight_pct": item.get("weightPercentage") or item.get("weight_pct"),
                        "asset_type": item.get("assetType") or "equity",
                        "participation_status": participation,
                        "research_status": None,
                    }
                )
            self.repo.replace_holdings(str(snap["id"]), rows)
            updated += 1
        return updated

    def _fetch_holdings(self, symbol: str):
        try:
            self.provider_calls += 1
            payload = self._fmp.etf_holdings(symbol)
        except Exception:
            return None
        if not payload:
            return None
        if isinstance(payload, dict):
            holdings = payload.get("holdings") or payload.get("assets") or []
        else:
            holdings = payload
        if not isinstance(holdings, list):
            return None
        total_weight = sum(float(row.get("weightPercentage") or 0.0) for row in holdings)
        coverage = min(total_weight, 100.0) if total_weight else None
        return holdings, coverage, len(holdings)

    def _participation_for(self, symbol: str) -> str:
        if not symbol or self._load_participation is None:
            return PARTICIPATION_UNKNOWN
        try:
            return self._load_participation(symbol)
        except Exception:
            return PARTICIPATION_UNKNOWN

    def finish(
        self,
        run_id: str,
        *,
        records_updated: int,
        report: Optional[Dict[str, object]] = None,
        failed: bool = False,
    ) -> None:
        self.runs.finish_run(
            run_id,
            status="FAILED" if failed else "COMPLETED",
            records_updated=records_updated,
            provider_calls=self.provider_calls,
            report_payload=report or {},
        )
