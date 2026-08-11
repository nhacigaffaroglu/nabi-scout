from __future__ import annotations

import copy
import time
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st


MAX_TRANSIENT_RETRIES = 2
MAX_RETRY_AFTER_SLEEP_SECONDS = 3.0
MAX_RATE_LIMIT_BREAKER_SECONDS = 60.0
TRANSIENT_RETRY_SLEEP_SECONDS = 0.0


class FMPError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_class: str = "unknown",
        status_code: Optional[int] = None,
        endpoint: Optional[str] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.status_code = status_code
        self.endpoint = endpoint
        self.retry_after = retry_after


class FMPClient:
    BASE_URL = "https://financialmodelingprep.com/stable"
    TRANSIENT_STATUS = {502, 503, 504}

    def __init__(self, api_key: str, timeout: int = 20) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.session = requests.Session()
        self._scan_cache: Dict[
            Tuple[str, Tuple[Tuple[str, Any], ...]],
            Dict[str, Any],
        ] = {}
        self._rate_limited_until = 0.0

        if not self.api_key:
            raise FMPError(
                "FMP API key boş.",
                error_class="auth",
            )

    @classmethod
    def from_streamlit_secrets(cls):
        try:
            key = str(st.secrets["fmp"]["api_key"]).strip()
        except KeyError as exc:
            raise FMPError(
                "Streamlit Secrets içinde [fmp] api_key bulunamadı.",
                error_class="auth",
            ) from exc
        return cls(key)

    @classmethod
    def from_env(cls):
        import os

        key = (os.environ.get("FMP_API_KEY") or "").strip()
        if not key:
            raise FMPError(
                "FMP_API_KEY environment variable is required.",
                error_class="auth",
            )
        return cls(key)

    def reset_scan_state(self) -> None:
        self._scan_cache.clear()
        self._rate_limited_until = 0.0

    @staticmethod
    def _parse_retry_after(header: Optional[str]) -> Optional[float]:
        if not header:
            return None
        try:
            return float(header)
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(header)
            return max(0.0, retry_at.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None

    def _cache_key(
        self,
        endpoint: str,
        params: Dict[str, Any],
    ) -> Tuple[str, Tuple[Tuple[str, Any], ...]]:
        return endpoint, tuple(sorted(params.items()))

    @staticmethod
    def _copy_response_data(data: List[Any]) -> List[Any]:
        return copy.deepcopy(data)

    def _store_success(self, cache_key, data: List[Any]) -> List[Any]:
        stored = self._copy_response_data(data)
        self._scan_cache[cache_key] = {"ok": True, "data": stored}
        return self._copy_response_data(stored)

    def _store_error(self, cache_key, error: FMPError) -> None:
        self._scan_cache[cache_key] = {"ok": False, "error": error}

    def _cached_or_raise(self, cache_key) -> Optional[List[Any]]:
        if cache_key not in self._scan_cache:
            return None
        entry = self._scan_cache[cache_key]
        if entry["ok"]:
            return self._copy_response_data(entry["data"])
        raise entry["error"]

    def _activate_rate_limit_breaker(
        self,
        retry_after: Optional[float],
    ) -> None:
        wait_seconds = retry_after if retry_after is not None else 1.0
        self._rate_limited_until = time.time() + min(
            max(wait_seconds, 1.0),
            MAX_RATE_LIMIT_BREAKER_SECONDS,
        )

    def _classify_http_error(
        self,
        *,
        status_code: int,
        endpoint: str,
        response: Optional[requests.Response] = None,
    ) -> FMPError:
        retry_after = None
        if response is not None:
            retry_after = self._parse_retry_after(
                response.headers.get("Retry-After"),
            )

        if status_code == 401:
            return FMPError(
                "FMP API key geçersiz.",
                error_class="auth",
                status_code=status_code,
                endpoint=endpoint,
            )
        if status_code in {402, 403}:
            return FMPError(
                f"FMP endpoint erişimi reddedildi: {endpoint}",
                error_class="plan_restricted",
                status_code=status_code,
                endpoint=endpoint,
            )
        if status_code == 404:
            return FMPError(
                f"FMP endpoint bulunamadı: {endpoint}",
                error_class="not_found",
                status_code=status_code,
                endpoint=endpoint,
            )
        if status_code == 429:
            return FMPError(
                "FMP çağrı limiti aşıldı.",
                error_class="rate_limit",
                status_code=status_code,
                endpoint=endpoint,
                retry_after=retry_after,
            )
        if status_code in self.TRANSIENT_STATUS:
            return FMPError(
                f"FMP geçici sunucu hatası HTTP {status_code}: {endpoint}",
                error_class="transient_http",
                status_code=status_code,
                endpoint=endpoint,
            )
        if status_code >= 400:
            return FMPError(
                f"FMP HTTP {status_code}: {endpoint}",
                error_class="http_error",
                status_code=status_code,
                endpoint=endpoint,
            )
        return FMPError(
            f"FMP beklenmeyen HTTP {status_code}: {endpoint}",
            error_class="http_error",
            status_code=status_code,
            endpoint=endpoint,
        )

    def _get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ):
        query = dict(params or {})
        query["apikey"] = self.api_key
        cache_key = self._cache_key(endpoint, query)

        cached = self._cached_or_raise(cache_key)
        if cached is not None:
            return cached

        if time.time() < self._rate_limited_until:
            error = FMPError(
                "FMP çağrı limiti aktif; scan içinde tekrar denenmedi.",
                error_class="rate_limit",
                endpoint=endpoint,
            )
            self._store_error(cache_key, error)
            raise error

        last_error: Optional[FMPError] = None
        attempts = MAX_TRANSIENT_RETRIES + 1
        rate_limit_retried = False

        for attempt in range(attempts):
            try:
                response = self.session.get(
                    f"{self.BASE_URL}/{endpoint}",
                    params=query,
                    timeout=self.timeout,
                )
            except requests.Timeout as exc:
                last_error = FMPError(
                    f"FMP zaman aşımı: {endpoint}",
                    error_class="timeout",
                    endpoint=endpoint,
                )
                if attempt >= attempts - 1:
                    self._store_error(cache_key, last_error)
                    raise last_error from exc
                continue
            except requests.RequestException as exc:
                last_error = FMPError(
                    f"FMP bağlantı hatası: {endpoint}",
                    error_class="network",
                    endpoint=endpoint,
                )
                if attempt >= attempts - 1:
                    self._store_error(cache_key, last_error)
                    raise last_error from exc
                continue

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    error = FMPError(
                        f"FMP geçersiz JSON döndürdü: {endpoint}",
                        error_class="malformed",
                        status_code=200,
                        endpoint=endpoint,
                    )
                    self._store_error(cache_key, error)
                    raise error from exc

                if isinstance(data, dict):
                    if data.get("Error Message"):
                        error = FMPError(
                            f"FMP hata döndürdü: {endpoint}",
                            error_class="empty",
                            status_code=200,
                            endpoint=endpoint,
                        )
                        self._store_error(cache_key, error)
                        raise error
                    if data.get("message") and len(data) <= 3:
                        error = FMPError(
                            f"FMP erişim mesajı döndürdü: {endpoint}",
                            error_class="plan_restricted",
                            status_code=200,
                            endpoint=endpoint,
                        )
                        self._store_error(cache_key, error)
                        raise error
                    data = [data]

                normalized = data if isinstance(data, list) else []
                return self._store_success(cache_key, normalized)

            error = self._classify_http_error(
                status_code=response.status_code,
                endpoint=endpoint,
                response=response,
            )

            if error.error_class == "rate_limit":
                retry_after = error.retry_after or 1.0
                if (
                    not rate_limit_retried
                    and retry_after <= MAX_RETRY_AFTER_SLEEP_SECONDS
                ):
                    rate_limit_retried = True
                    time.sleep(retry_after)
                    continue

                self._activate_rate_limit_breaker(retry_after)
                self._store_error(cache_key, error)
                raise error

            if (
                error.error_class == "transient_http"
                and attempt < attempts - 1
            ):
                last_error = error
                if TRANSIENT_RETRY_SLEEP_SECONDS:
                    time.sleep(TRANSIENT_RETRY_SLEEP_SECONDS)
                continue

            self._store_error(cache_key, error)
            raise error

        if last_error is not None:
            self._store_error(cache_key, last_error)
            raise last_error

        error = FMPError(
            f"FMP isteği tamamlanamadı: {endpoint}",
            error_class="unknown",
            endpoint=endpoint,
        )
        self._store_error(cache_key, error)
        raise error

    def profile(self, symbol: str):
        rows = self._get("profile", {"symbol": symbol})
        return rows[0] if rows else {}

    def quote(self, symbol: str):
        rows = self._get("quote", {"symbol": symbol})
        return rows[0] if rows else {}

    def etf_info(self, symbol: str):
        rows = self._get("etf/info", {"symbol": symbol})
        return rows[0] if rows else {}

    def etf_holdings(self, symbol: str):
        rows = self._get("etf/holdings", {"symbol": symbol})
        return rows if isinstance(rows, list) else []

    def historical_price_eod_light(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
    ):
        rows = self._get(
            "historical-price-eod/light",
            {
                "symbol": symbol,
                "from": from_date,
                "to": to_date,
            },
        )
        return rows if isinstance(rows, list) else []

    def income_statement(self, symbol: str):
        return self._get(
            "income-statement",
            {"symbol": symbol, "limit": 5},
        )

    def balance_sheet(self, symbol: str):
        return self._get(
            "balance-sheet-statement",
            {"symbol": symbol, "limit": 5},
        )

    def cash_flow(self, symbol: str):
        return self._get(
            "cash-flow-statement",
            {"symbol": symbol, "limit": 5},
        )

    def ratios_ttm(self, symbol: str):
        rows = self._get("ratios-ttm", {"symbol": symbol})
        return rows[0] if rows else {}

    def key_metrics_ttm(self, symbol: str):
        rows = self._get(
            "key-metrics-ttm",
            {"symbol": symbol},
        )
        return rows[0] if rows else {}

    def income_growth(self, symbol: str):
        rows = self._get(
            "income-statement-growth",
            {"symbol": symbol, "limit": 1},
        )
        return rows[0] if rows else {}

    def pause(self, seconds: float = 0.15):
        time.sleep(seconds)
