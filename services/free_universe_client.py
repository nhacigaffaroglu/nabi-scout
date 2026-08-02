from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

import requests


class UniverseSourceError(RuntimeError):
    pass


class FreeUniverseClient:
    SEC_URL = (
        "https://www.sec.gov/files/company_tickers_exchange.json"
    )
    NASDAQ_LISTED_URL = (
        "https://www.nasdaqtrader.com/dynamic/"
        "symdir/nasdaqlisted.txt"
    )
    OTHER_LISTED_URL = (
        "https://www.nasdaqtrader.com/dynamic/"
        "symdir/otherlisted.txt"
    )

    EXCLUDED_NAME_TERMS = (
        "warrant",
        "warrants",
        "unit",
        "units",
        "right",
        "rights",
        "preferred",
        "depositary share",
        "depositary shares",
        "note due",
        "notes due",
        "bond",
        "debenture",
        "acquisition corp",
        "acquisition corporation",
        "acquisition company",
        "blank check",
        "special purpose acquisition",
        "spac",
    )

    def __init__(
        self,
        *,
        contact_email: str,
        timeout: int = 30,
    ) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "NABI Scout investment research app "
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
                f"SEC kaynağı HTTP "
                f"{response.status_code} döndürdü."
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
                "SEC ticker dosyası boş veya beklenmeyen biçimde."
            )

        rows = []
        for values in data:
            row = dict(zip(fields, values))
            ticker = str(
                row.get("ticker") or ""
            ).strip().upper()
            name = str(row.get("name") or "").strip()

            if not ticker:
                continue
            if self._excluded_security_name(name):
                continue

            rows.append({
                "symbol": ticker,
                "company_name": name or ticker,
                "exchange": row.get("exchange"),
                "cik": row.get("cik"),
                "source_sec": True,
            })

        return rows

    def get_nasdaq_listed(self) -> List[Dict[str, Any]]:
        rows = self._parse_pipe_file(
            self._download_text(self.NASDAQ_LISTED_URL)
        )
        result = []

        for row in rows:
            symbol = str(
                row.get("Symbol") or ""
            ).strip().upper()
            name = str(
                row.get("Security Name") or ""
            ).strip()

            if not symbol or row.get("Test Issue") == "Y":
                continue
            if symbol.startswith("File Creation Time"):
                continue
            if self._excluded_security_name(name):
                continue

            result.append({
                "symbol": symbol,
                "company_name": name,
                "exchange": "NASDAQ",
                "is_etf": row.get("ETF") == "Y",
                "source_nasdaq": True,
            })

        return result

    def get_other_listed(self) -> List[Dict[str, Any]]:
        rows = self._parse_pipe_file(
            self._download_text(self.OTHER_LISTED_URL)
        )
        exchange_map = {
            "A": "NYSE American",
            "N": "NYSE",
            "P": "NYSE Arca",
            "Z": "Cboe BZX",
            "V": "IEX",
        }
        result = []

        for row in rows:
            symbol = str(
                row.get("NASDAQ Symbol")
                or row.get("ACT Symbol")
                or ""
            ).strip().upper()
            name = str(
                row.get("Security Name") or ""
            ).strip()

            if not symbol or row.get("Test Issue") == "Y":
                continue
            if symbol.startswith("File Creation Time"):
                continue
            if self._excluded_security_name(name):
                continue

            result.append({
                "symbol": symbol,
                "company_name": name,
                "exchange": exchange_map.get(
                    row.get("Exchange"),
                    row.get("Exchange"),
                ),
                "is_etf": row.get("ETF") == "Y",
                "source_nasdaq": True,
            })

        return result

    def _download_text(self, url: str) -> str:
        response = self.session.get(
            url,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise UniverseSourceError(
                f"Nasdaq Trader HTTP "
                f"{response.status_code}."
            )
        return response.text

    @staticmethod
    def _parse_pipe_file(
        text: str,
    ) -> List[Dict[str, str]]:
        return list(csv.DictReader(
            io.StringIO(text),
            delimiter="|",
        ))

    def _excluded_security_name(self, name: str) -> bool:
        lowered = name.lower()
        return any(
            term in lowered
            for term in self.EXCLUDED_NAME_TERMS
        )
