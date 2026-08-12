from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import streamlit as st

STATUS_OK = "OK"
STATUS_RATE_LIMIT = "RATE_LIMIT"
STATUS_PREMIUM_REQUIRED = "PREMIUM_REQUIRED"
STATUS_AUTH = "AUTH"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_MALFORMED = "MALFORMED"
STATUS_NETWORK = "NETWORK"

BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_class: str = "unknown",
        status: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.status = status or error_class


class AlphaVantageClient:
    def __init__(self, api_key: str, timeout: int = 30) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        if not self.api_key:
            raise AlphaVantageError(
                "Alpha Vantage API key boş.",
                error_class="auth",
                status=STATUS_AUTH,
            )

    @classmethod
    def from_env(cls) -> "AlphaVantageClient":
        key = (os.environ.get("ALPHA_VANTAGE_API_KEY") or "").strip()
        if not key:
            raise AlphaVantageError(
                "ALPHA_VANTAGE_API_KEY environment variable is required.",
                error_class="auth",
                status=STATUS_AUTH,
            )
        return cls(key)

    @classmethod
    def from_streamlit_secrets(cls) -> "AlphaVantageClient":
        try:
            section = st.secrets["alpha_vantage"]
            key = str(section["api_key"]).strip()
        except KeyError as exc:
            raise AlphaVantageError(
                "Streamlit Secrets içinde [alpha_vantage] api_key bulunamadı.",
                error_class="auth",
                status=STATUS_AUTH,
            ) from exc
        return cls(key)

    def etf_profile(self, symbol: str) -> Dict[str, Any]:
        payload = self._request(function="ETF_PROFILE", symbol=symbol)
        classify_alpha_payload(payload, expect="etf_profile")
        return payload

    def time_series_daily(
        self,
        symbol: str,
        *,
        outputsize: str = "compact",
    ) -> Dict[str, Any]:
        payload = self._request(
            function="TIME_SERIES_DAILY",
            symbol=symbol,
            outputsize=outputsize,
        )
        classify_alpha_payload(payload, expect="time_series_daily")
        return payload

    def _request(self, **params: str) -> Dict[str, Any]:
        query = dict(params)
        query["apikey"] = self.api_key
        url = f"{BASE_URL}?{urlencode(query)}"
        request = Request(url, headers={"User-Agent": "nabi-scout/1.0"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise AlphaVantageError(
                f"Alpha Vantage HTTP hatası: {exc.code}",
                error_class="network",
                status=STATUS_NETWORK,
            ) from exc
        except URLError as exc:
            raise AlphaVantageError(
                "Alpha Vantage ağ hatası.",
                error_class="network",
                status=STATUS_NETWORK,
            ) from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AlphaVantageError(
                "Alpha Vantage yanıtı geçersiz JSON.",
                error_class="malformed",
                status=STATUS_MALFORMED,
            ) from exc

        if not isinstance(payload, dict):
            raise AlphaVantageError(
                "Alpha Vantage yanıtı beklenmeyen biçimde.",
                error_class="malformed",
                status=STATUS_MALFORMED,
            )
        return payload


def classify_alpha_payload(payload: Dict[str, Any], *, expect: str) -> str:
    if "Note" in payload:
        raise AlphaVantageError(
            "Alpha Vantage rate limit.",
            error_class="rate_limit",
            status=STATUS_RATE_LIMIT,
        )

    if "Information" in payload:
        info = str(payload.get("Information") or "")
        lowered = info.lower()
        if any(token in lowered for token in ("premium", "plan", "subscription")):
            raise AlphaVantageError(
                "Alpha Vantage premium endpoint.",
                error_class="premium_required",
                status=STATUS_PREMIUM_REQUIRED,
            )
        raise AlphaVantageError(
            "Alpha Vantage bilgi yanıtı.",
            error_class="unavailable",
            status=STATUS_PREMIUM_REQUIRED,
        )

    if "Error Message" in payload:
        message = str(payload.get("Error Message") or "")
        lowered = message.lower()
        if "apikey" in lowered or "api key" in lowered:
            raise AlphaVantageError(
                "Alpha Vantage kimlik doğrulama hatası.",
                error_class="auth",
                status=STATUS_AUTH,
            )
        if "invalid" in lowered and "symbol" in lowered:
            raise AlphaVantageError(
                "Alpha Vantage sembol bulunamadı.",
                error_class="not_found",
                status=STATUS_NOT_FOUND,
            )
        raise AlphaVantageError(
            "Alpha Vantage istek hatası.",
            error_class="malformed",
            status=STATUS_MALFORMED,
        )

    if expect == "etf_profile":
        if any(key in payload for key in ("net_assets", "holdings", "net_expense_ratio")):
            return STATUS_OK
        raise AlphaVantageError(
            "Alpha Vantage ETF profili boş veya geçersiz.",
            error_class="malformed",
            status=STATUS_MALFORMED,
        )

    if expect == "time_series_daily":
        if any("Time Series" in key for key in payload):
            return STATUS_OK
        raise AlphaVantageError(
            "Alpha Vantage fiyat geçmişi boş veya geçersiz.",
            error_class="malformed",
            status=STATUS_MALFORMED,
        )

    raise AlphaVantageError(
        "Alpha Vantage yanıtı sınıflandırılamadı.",
        error_class="malformed",
        status=STATUS_MALFORMED,
    )


def alpha_error_status(exc: AlphaVantageError) -> str:
    mapping = {
        "rate_limit": STATUS_RATE_LIMIT,
        "premium_required": STATUS_PREMIUM_REQUIRED,
        "auth": STATUS_AUTH,
        "not_found": STATUS_NOT_FOUND,
        "malformed": STATUS_MALFORMED,
        "network": STATUS_NETWORK,
        "unavailable": STATUS_PREMIUM_REQUIRED,
    }
    return mapping.get(exc.error_class, STATUS_MALFORMED)
