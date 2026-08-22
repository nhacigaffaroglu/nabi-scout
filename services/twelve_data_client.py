from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import streamlit as st

BASE_URL = "https://api.twelvedata.com"


class TwelveDataError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_class: str = "unknown",
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.status_code = status_code


class TwelveDataClient:
    def __init__(self, api_key: str, timeout: int = 30) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        if not self.api_key:
            raise TwelveDataError(
                "Twelve Data API key boş.",
                error_class="auth",
            )

    @classmethod
    def from_env(cls) -> "TwelveDataClient":
        key = (os.environ.get("TWELVE_DATA_API_KEY") or "").strip()
        if not key:
            raise TwelveDataError(
                "TWELVE_DATA_API_KEY environment variable is required.",
                error_class="auth",
            )
        return cls(key)

    @classmethod
    def from_streamlit_secrets(cls) -> "TwelveDataClient":
        try:
            section = st.secrets["twelve_data"]
            key = str(section["api_key"]).strip()
        except KeyError as exc:
            raise TwelveDataError(
                "Streamlit Secrets içinde [twelve_data] api_key bulunamadı.",
                error_class="auth",
            ) from exc
        return cls(key)

    def quote(
        self,
        symbol: str,
        *,
        mic_code: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, str] = {"symbol": str(symbol or "").strip()}
        if mic_code:
            params["mic_code"] = str(mic_code).strip()
        if exchange:
            params["exchange"] = str(exchange).strip()
        return self._get("/quote", params)

    def exchange_rate(self, symbol: str) -> Dict[str, Any]:
        return self._get("/exchange_rate", {"symbol": str(symbol or "").strip()})

    def _get(self, path: str, params: Dict[str, str]) -> Dict[str, Any]:
        query = dict(params)
        query["apikey"] = self.api_key
        url = f"{BASE_URL}{path}?{urlencode(query)}"
        request = Request(url, headers={"User-Agent": "nabi-scout/1.0"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                status_code = getattr(response, "status", 200)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            payload = _safe_json(raw)
            raise _classify_error(payload, status_code=exc.code) from exc
        except URLError as exc:
            raise TwelveDataError(
                "Twelve Data ağ hatası.",
                error_class="network",
            ) from exc

        payload = _safe_json(body)
        if not isinstance(payload, dict):
            raise TwelveDataError(
                "Twelve Data yanıtı beklenmeyen biçimde.",
                error_class="malformed",
                status_code=status_code,
            )
        if str(payload.get("status") or "").strip().lower() == "error":
            raise _classify_error(payload, status_code=status_code)
        if payload.get("code") and not payload.get("symbol") and not payload.get("rate"):
            raise _classify_error(payload, status_code=status_code)
        return payload


def _safe_json(raw: str) -> Any:
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def _sanitize(message: str) -> str:
    return re.sub(r"(?i)apikey=[^&\s]+", "apikey=REDACTED", str(message or ""))


def _classify_error(payload: Dict[str, Any], *, status_code: Optional[int]) -> TwelveDataError:
    message = _sanitize(str(payload.get("message") or payload.get("status") or "Twelve Data hata döndürdü."))
    lowered = message.lower()
    code = payload.get("code")
    try:
        numeric_code = int(code) if code is not None else status_code
    except (TypeError, ValueError):
        numeric_code = status_code
    error_class = "provider_access_failure"
    if numeric_code == 401 or "api key" in lowered or "apikey" in lowered:
        error_class = "auth"
    elif numeric_code == 429 or "credit" in lowered or "limit" in lowered:
        error_class = "rate_limit"
    elif numeric_code in {402, 403} or "plan" in lowered or "subscribe" in lowered:
        error_class = "plan_restricted"
    elif numeric_code == 404 or "not found" in lowered:
        error_class = "not_found"
    return TwelveDataError(
        message,
        error_class=error_class,
        status_code=numeric_code,
    )
