from __future__ import annotations

from datetime import date
from typing import Dict, Optional, Tuple

from repositories.fx_rate_repository import FxRateRepository
from repositories.wealth_automation_run_repository import WealthAutomationRunRepository
from services.current_market_data import (
    AlphaVantageCurrentMarketData,
    FmpCurrentMarketData,
    TwelveDataCurrentMarketData,
    fetch_fx_rate,
)
from services.current_market_data_contract import persistence_source


DEFAULT_FX_PAIRS = (
    ("USD", "EUR"),
    ("USD", "TRY"),
    ("USD", "GBP"),
    ("USD", "SAR"),
    ("USD", "AED"),
    ("EUR", "TRY"),
    ("EUR", "GBP"),
)


class FxRateRefreshService:
    """Scheduled FX refresh — not used on page render."""

    JOB_NAME = "daily_fx_refresh"

    def __init__(
        self,
        client,
        fmp_client=None,
        alpha_vantage_client=None,
        twelve_data_client=None,
    ) -> None:
        self.repo = FxRateRepository(client)
        self.runs = WealthAutomationRunRepository(client)
        self._fmp = fmp_client
        self._fallbacks = []
        if twelve_data_client is not None:
            self._fallbacks.append(TwelveDataCurrentMarketData(twelve_data_client))
        if alpha_vantage_client is not None:
            self._fallbacks.append(AlphaVantageCurrentMarketData(alpha_vantage_client))
        if fmp_client is not None:
            self._primary = FmpCurrentMarketData(fmp_client)
        elif self._fallbacks:
            self._primary = self._fallbacks.pop(0)
        else:
            self._primary = None
        self._fallback = self._fallbacks[0] if self._fallbacks else None
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
            status = str(existing.get("status") or "")
            if status in {"COMPLETED", "RUNNING"}:
                return {"skipped": True, "reason": "already_run", "run_id": existing.get("id")}
        started = self.runs.try_start_run(
            job_name=self.JOB_NAME,
            run_date=today,
            trigger_type=trigger_type,
        )
        if started is None and not allow_second_run:
            return {"skipped": True, "reason": "concurrent_or_duplicate"}
        return {"skipped": False, "run_id": (started or existing or {}).get("id"), "run_date": today.isoformat()}

    def refresh_pairs(
        self,
        pairs: Optional[Tuple[Tuple[str, str], ...]] = None,
        *,
        rate_date: Optional[date] = None,
    ) -> int:
        target_pairs = pairs or DEFAULT_FX_PAIRS
        as_of = rate_date or date.today()
        updated = 0
        for base, quote in target_pairs:
            result = self._fetch_rate_result(base, quote)
            if result is None or not result.ok or result.rate is None:
                continue
            self.repo.upsert_rate(
                base_currency=base,
                quote_currency=quote,
                rate=result.rate,
                rate_date=as_of,
                source=persistence_source(result.provider),
            )
            updated += 1
        return updated

    def _sync_provider_calls(self) -> None:
        self.provider_calls = 0
        if self._primary is not None:
            self.provider_calls += self._primary.calls
        for provider in self._fallbacks:
            self.provider_calls += provider.calls

    def _fetch_rate_result(self, base: str, quote: str):
        """Return quote-currency units per 1 base-currency unit.

        Stored pair (USD, TRY) therefore means TRY per 1 USD. Conversion
        of a TRY amount into USD is amount / rate.
        """
        if self._primary is None:
            return None
        result = fetch_fx_rate(
            base,
            quote,
            primary=self._primary,
            fallbacks=self._fallbacks,
        )
        self._sync_provider_calls()
        return result

    def _fetch_rate(self, base: str, quote: str) -> Optional[float]:
        result = self._fetch_rate_result(base, quote)
        if result is None or not result.ok:
            return None
        return result.rate

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
