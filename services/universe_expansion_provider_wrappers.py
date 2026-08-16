from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from services.fmp_client import FMPClient, FMPError
from services.provider_budget_service import ProviderBudgetManager
from services.provider_call_ledger import ProviderCallLedger
from services.sec_financial_client import SECFinancialClient, SECFinancialError
from services.universe_expansion_contract import PROVIDER_FMP, PROVIDER_SEC


class BudgetAwareFMPClient(FMPClient):
    def __init__(
        self,
        *,
        ledger: ProviderCallLedger,
        budget: ProviderBudgetManager,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._ledger = ledger
        self._budget = budget

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None):
        query = dict(params or {})
        cache_key = self._cache_key(endpoint, query)
        if cache_key in self._scan_cache:
            try:
                data = self._cached_or_raise(cache_key)
                self._ledger.record_cache_hit(PROVIDER_FMP, endpoint)
                return data
            except FMPError:
                pass
        try:
            data = super()._get(endpoint, params)
        except FMPError as exc:
            if exc.error_class == "rate_limit":
                self._budget.mark_rate_limited(PROVIDER_FMP)
            raise
        self._ledger.record_remote(PROVIDER_FMP, endpoint)
        self._budget.record_spend(PROVIDER_FMP, endpoint, 1)
        return data


class BudgetAwareSECClient(SECFinancialClient):
    def __init__(
        self,
        *,
        ledger: ProviderCallLedger,
        budget: ProviderBudgetManager,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._ledger = ledger
        self._budget = budget

    def company_facts(self, cik: int | str):
        try:
            payload = super().company_facts(cik)
        except SECFinancialError as exc:
            message = str(exc).lower()
            if "429" in message or "rate" in message:
                self._budget.mark_rate_limited(PROVIDER_SEC)
            raise
        self._ledger.record_remote(PROVIDER_SEC, "company_facts")
        self._budget.record_spend(PROVIDER_SEC, "company_facts", 1)
        return payload

    def company_submissions(self, cik: int | str):
        cik_text = str(cik).strip().zfill(10)
        cached = cik_text in self._submissions_cache
        try:
            payload = super().company_submissions(cik)
        except SECFinancialError as exc:
            message = str(exc).lower()
            if "429" in message or "rate" in message:
                self._budget.mark_rate_limited(PROVIDER_SEC)
            raise
        if cached:
            self._ledger.record_cache_hit(PROVIDER_SEC, "company_submissions")
        else:
            self._ledger.record_remote(PROVIDER_SEC, "company_submissions")
            self._budget.record_spend(PROVIDER_SEC, "company_submissions", 1)
        return payload


def wrap_fmp_client(
    client: FMPClient,
    *,
    ledger: ProviderCallLedger,
    budget: ProviderBudgetManager,
) -> BudgetAwareFMPClient:
    if isinstance(client, BudgetAwareFMPClient):
        return client
    wrapped = BudgetAwareFMPClient(
        ledger=ledger,
        budget=budget,
        api_key=client.api_key,
        timeout=client.timeout,
    )
    wrapped._scan_cache = client._scan_cache
    wrapped._rate_limited_until = client._rate_limited_until
    return wrapped


def wrap_sec_client(
    client: SECFinancialClient,
    *,
    ledger: ProviderCallLedger,
    budget: ProviderBudgetManager,
) -> BudgetAwareSECClient:
    if isinstance(client, BudgetAwareSECClient):
        return client
    wrapped = BudgetAwareSECClient(
        ledger=ledger,
        budget=budget,
        contact_email=client.session.headers.get("User-Agent", "").split("contact=")[-1]
        if "contact=" in client.session.headers.get("User-Agent", "")
        else "nabi-scout@local",
        timeout=client.timeout,
    )
    wrapped._submissions_cache = client._submissions_cache
    return wrapped


def map_participation_calls_to_providers(
    provider_calls: Mapping[str, int],
) -> Dict[str, int]:
    fmp_keys = {
        "profile",
        "historical_price_eod_light",
        "quarterly_financials",
        "ratios",
        "metrics",
    }
    sec_keys = {
        "sec_submissions",
        "sec_inline_xbrl",
        "sec_revenue_segments",
        "company_facts",
    }
    totals = {PROVIDER_FMP: 0, PROVIDER_SEC: 0}
    for key, count in provider_calls.items():
        if key in fmp_keys:
            totals[PROVIDER_FMP] += int(count)
        elif key in sec_keys:
            totals[PROVIDER_SEC] += int(count)
    return totals
