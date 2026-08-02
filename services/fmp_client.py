from typing import Any, Dict, List, Optional
import time
import requests
import streamlit as st

class FMPError(RuntimeError):
    pass

class FMPClient:
    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(self, api_key: str, timeout: int = 20) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.session = requests.Session()
        if not self.api_key:
            raise FMPError("FMP API key boş.")

    @classmethod
    def from_streamlit_secrets(cls):
        try:
            key = str(st.secrets["fmp"]["api_key"]).strip()
        except KeyError as exc:
            raise FMPError("Streamlit Secrets içinde [fmp] api_key bulunamadı.") from exc
        return cls(key)

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None):
        query = dict(params or {})
        query["apikey"] = self.api_key
        response = self.session.get(
            f"{self.BASE_URL}/{endpoint}",
            params=query,
            timeout=self.timeout,
        )
        if response.status_code == 401:
            raise FMPError("FMP API key geçersiz.")
        if response.status_code == 403:
            raise FMPError(f"Endpoint planınızda kapalı: {endpoint}")
        if response.status_code == 429:
            raise FMPError("FMP çağrı limiti aşıldı.")
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            if data.get("Error Message"):
                raise FMPError(str(data["Error Message"]))
            if data.get("message") and len(data) <= 3:
                raise FMPError(str(data["message"]))
            data = [data]
        return data if isinstance(data, list) else []

    def profile(self, symbol: str):
        rows = self._get("profile", {"symbol": symbol})
        return rows[0] if rows else {}

    def quote(self, symbol: str):
        rows = self._get("quote", {"symbol": symbol})
        return rows[0] if rows else {}

    def income_statement(self, symbol: str):
        return self._get("income-statement", {"symbol": symbol, "limit": 5})

    def balance_sheet(self, symbol: str):
        return self._get("balance-sheet-statement", {"symbol": symbol, "limit": 5})

    def cash_flow(self, symbol: str):
        return self._get("cash-flow-statement", {"symbol": symbol, "limit": 5})

    def ratios_ttm(self, symbol: str):
        rows = self._get("ratios-ttm", {"symbol": symbol})
        return rows[0] if rows else {}

    def key_metrics_ttm(self, symbol: str):
        rows = self._get("key-metrics-ttm", {"symbol": symbol})
        return rows[0] if rows else {}

    def income_growth(self, symbol: str):
        rows = self._get("income-statement-growth", {"symbol": symbol, "limit": 1})
        return rows[0] if rows else {}

    def pause(self, seconds: float = 0.15):
        time.sleep(seconds)
