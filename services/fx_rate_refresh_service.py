from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from repositories.fx_rate_repository import FxRateRepository
from repositories.wealth_automation_run_repository import WealthAutomationRunRepository
from services.wealth_price_service import normalize_currency


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

    def __init__(self, client, fmp_client=None) -> None:
        self.repo = FxRateRepository(client)
        self.runs = WealthAutomationRunRepository(client)
        self._fmp = fmp_client
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
            rate = self._fetch_rate(base, quote)
            if rate is None:
                continue
            self.repo.upsert_rate(
                base_currency=base,
                quote_currency=quote,
                rate=rate,
                rate_date=as_of,
                source="fmp_quote" if self._fmp else "manual_seed",
            )
            updated += 1
        return updated

    def _quote_price(self, symbol: str) -> Optional[float]:
        if self._fmp is None:
            return None
        try:
            self.provider_calls += 1
            payload = self._fmp.quote(symbol)
            if isinstance(payload, list) and payload:
                price = payload[0].get("price")
            elif isinstance(payload, dict):
                price = payload.get("price")
            else:
                price = None
            if price is None or price == "":
                return None
            value = float(price)
            if value <= 0 or value != value:
                return None
            return value
        except Exception:
            return None

    def _fetch_rate(self, base: str, quote: str) -> Optional[float]:
        """Return quote-currency units per 1 base-currency unit.

        Stored pair (USD, TRY) therefore means TRY per 1 USD. Conversion
        of a TRY amount into USD is amount / rate.
        """
        if self._fmp is None:
            return None
        base_code = normalize_currency(base)
        quote_code = normalize_currency(quote)
        direct_symbol = f"{base_code}{quote_code}"
        inverse_symbol = f"{quote_code}{base_code}"
        direct = self._quote_price(direct_symbol)
        if direct is not None:
            return direct
        inverse = self._quote_price(inverse_symbol)
        if inverse is not None:
            return 1.0 / inverse
        return None

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
