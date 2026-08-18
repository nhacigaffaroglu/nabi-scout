from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Set

from repositories.fund_holdings_repository import FundHoldingsRepository
from repositories.wealth_automation_run_repository import WealthAutomationRunRepository
from services.fmp_client import FMPError
from services.participation_filter_service import PARTICIPATION_UNKNOWN
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)


LOOKTHROUGH_ONBOARDING_SYMBOLS = ("SPUS", "SPSK", "SPRE", "SPWO")

# Provider type strings only. No ticker/name inference.
_PROVIDER_ASSET_TYPE_MAP = {
    "equity": "equity",
    "equities": "equity",
    "stock": "equity",
    "stocks": "equity",
    "common stock": "equity",
    "commonstock": "equity",
    "preferred stock": "equity",
    "preferred": "equity",
    "sukuk": "sukuk",
    "fixed_income": "fixed_income",
    "fixed income": "fixed_income",
    "fixed-income": "fixed_income",
    "bond": "fixed_income",
    "bonds": "fixed_income",
    "corporate bond": "fixed_income",
    "government bond": "fixed_income",
    "treasury": "fixed_income",
    "reit": "real_estate",
    "reits": "real_estate",
    "real_estate": "real_estate",
    "real estate": "real_estate",
    "realestate": "real_estate",
    "cash": "cash",
    "cash_equivalent": "cash",
    "cash equivalent": "cash",
    "cash & cash equivalents": "cash",
    "money market": "cash",
    "commodity": "commodity",
    "commodities": "commodity",
    "gold": "commodity",
}


def normalize_provider_asset_type(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    key = str(raw).strip().lower()
    if not key or key in {"n/a", "na", "none", "null", "other", "unknown", "n.a."}:
        return None
    return _PROVIDER_ASSET_TYPE_MAP.get(key)


def holding_weight_pct(item: Dict[str, Any]) -> Optional[float]:
    raw = item.get("weightPercentage")
    if raw is None:
        raw = item.get("weight_pct")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _underlying_symbol(item: Dict[str, Any], fund_symbol: str) -> str:
    for key in ("asset", "holding", "ticker"):
        value = str(item.get(key) or "").strip().upper()
        if value:
            return value
    value = str(item.get("symbol") or "").strip().upper()
    if value and value != fund_symbol:
        return value
    return ""


class FundHoldingsRefreshService:
    """Scheduled / controlled fund holdings refresh — not used on page render."""

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
        results = self.refresh_requested_symbols(sorted(symbols), as_of=as_of)
        return sum(1 for row in results if row.get("persisted"))

    def refresh_requested_symbols(
        self,
        symbols: Sequence[str],
        *,
        as_of: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        snap_date = as_of or date.today()
        results: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for raw_symbol in symbols:
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            results.append(self._refresh_one(symbol, snap_date))
        return results

    def _refresh_one(self, symbol: str, snap_date: date) -> Dict[str, Any]:
        base = {
            "symbol": symbol,
            "supported": False,
            "holdings_count": 0,
            "coverage_pct": None,
            "persisted": False,
            "source": self.SOURCE,
            "as_of": snap_date.isoformat(),
            "limitation": "",
            "error_class": None,
        }
        if self._fmp is None:
            return {**base, "limitation": "provider_unavailable"}

        payload, error_class, limitation = self._fetch_holdings(symbol)
        if payload is None:
            return {**base, "limitation": limitation, "error_class": error_class}

        holdings, coverage_pct, underlying_count = payload
        if underlying_count <= 0 or coverage_pct is None or float(coverage_pct) <= 0:
            return {
                **base,
                "limitation": "empty_or_unweighted_holdings",
                "error_class": "empty",
                "holdings_count": underlying_count,
                "coverage_pct": coverage_pct,
            }

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
            underlying = _underlying_symbol(item, symbol)
            participation = self._participation_for(underlying)
            rows.append(
                {
                    "snapshot_id": snap["id"],
                    "underlying_symbol": underlying or None,
                    "underlying_name": item.get("name"),
                    "weight_pct": holding_weight_pct(item),
                    "asset_type": normalize_provider_asset_type(
                        item.get("assetType")
                        or item.get("asset_type")
                        or item.get("securityType")
                        or item.get("type")
                    ),
                    "participation_status": participation,
                    "research_status": None,
                }
            )
        self.repo.replace_holdings(str(snap["id"]), rows)
        return {
            **base,
            "supported": True,
            "holdings_count": underlying_count,
            "coverage_pct": coverage_pct,
            "persisted": True,
            "limitation": "" if coverage_pct >= 100 else "partial_coverage",
        }

    def _fetch_holdings(self, symbol: str):
        try:
            self.provider_calls += 1
            payload = self._fmp.etf_holdings(symbol)
        except FMPError as exc:
            return None, str(exc.error_class or "provider_error"), str(exc.error_class or "provider_error")
        except Exception:
            return None, "provider_error", "provider_error"
        if not payload:
            return None, "empty", "unsupported_or_empty"
        if isinstance(payload, dict):
            holdings = payload.get("holdings") or payload.get("assets") or []
        else:
            holdings = payload
        if not isinstance(holdings, list) or not holdings:
            return None, "empty", "unsupported_or_empty"
        weights = [holding_weight_pct(row) or 0.0 for row in holdings]
        total_weight = sum(weights)
        coverage = min(total_weight, 100.0) if total_weight else None
        return (holdings, coverage, len(holdings)), None, ""

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
