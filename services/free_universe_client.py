from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

import requests


class UniverseSourceError(RuntimeError):
    pass


class FreeUniverseClient:
    SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
    NASDAQ_LISTED_URL = (
        "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
    )
    OTHER_LISTED_URL = (
        "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
    )

    def __init__(
        self,
        *,
        contact_email: str = "nabi-scout@example.com",
        timeout: int = 30,
    ) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                f"NABI Scout investment research app "
                f"contact={contact_email}"
            ),
            "Accept-Encoding": "gzip, deflate",
        })

    def get_sec_companies(self) -> List[Dict[str, Any]]:
        response = self.session.get(
            self.SEC_URL,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise UniverseSourceError(
                f"SEC kaynağı HTTP {response.status_code} döndürdü."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise UniverseSourceError(
                "SEC kaynağı geçerli JSON döndürmedi."
            ) from exc

        fields = payload.get("fields") or []
        data = payload.get("data") or []

        if not fields or not data:
            raise UniverseSourceError(
                "SEC ticker dosyasında beklenen alanlar bulunamadı."
            )

        rows = []
        for values in data:
            row = dict(zip(fields, values))
            ticker = str(row.get("ticker") or "").strip().upper()
            if not ticker:
                continue

            rows.append({
                "symbol": ticker,
                "company_name": row.get("name"),
                "exchange": row.get("exchange"),
                "cik": row.get("cik"),
                "source_sec": True,
            })

        return rows

    def get_nasdaq_listed(self) -> List[Dict[str, Any]]:
        text = self._download_text(self.NASDAQ_LISTED_URL)
        rows = self._parse_pipe_file(text)

        result = []
        for row in rows:
            if row.get("Test Issue") == "Y":
                continue
            if str(row.get("Symbol") or "").startswith("File Creation Time"):
                continue

            symbol = str(row.get("Symbol") or "").strip().upper()
            if not symbol:
                continue

            result.append({
                "symbol": symbol,
                "company_name": row.get("Security Name"),
                "exchange": "NASDAQ",
                "is_etf": row.get("ETF") == "Y",
                "test_issue": False,
                "source_nasdaq": True,
            })
        return result

    def get_other_listed(self) -> List[Dict[str, Any]]:
        text = self._download_text(self.OTHER_LISTED_URL)
        rows = self._parse_pipe_file(text)

        exchange_map = {
            "A": "NYSE American",
            "N": "NYSE",
            "P": "NYSE Arca",
            "Z": "Cboe BZX",
            "V": "IEX",
        }

        result = []
        for row in rows:
            if row.get("Test Issue") == "Y":
                continue
            if str(row.get("ACT Symbol") or "").startswith(
                "File Creation Time"
            ):
                continue

            symbol = str(
                row.get("NASDAQ Symbol")
                or row.get("ACT Symbol")
                or ""
            ).strip().upper()
            if not symbol:
                continue

            result.append({
                "symbol": symbol,
                "company_name": row.get("Security Name"),
                "exchange": exchange_map.get(
                    row.get("Exchange"),
                    row.get("Exchange"),
                ),
                "is_etf": row.get("ETF") == "Y",
                "test_issue": False,
                "source_nasdaq": True,
            })
        return result

    def _download_text(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        if response.status_code != 200:
            raise UniverseSourceError(
                f"Nasdaq Trader kaynağı HTTP "
                f"{response.status_code} döndürdü."
            )
        return response.text

    @staticmethod
    def _parse_pipe_file(text: str) -> List[Dict[str, str]]:
        reader = csv.DictReader(
            io.StringIO(text),
            delimiter="|",
        )
        return [dict(row) for row in reader]
