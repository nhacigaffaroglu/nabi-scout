"""Read-only OpenFIGI mapping client. Anonymous by default.

No database. Missing API key uses public limits (10 jobs/request, 25/min).
Does not classify instrument type.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
ID_SEDOL = "ID_SEDOL"
ID_CUSIP = "ID_CUSIP"
ID_TICKER = "TICKER"
SUPPORTED_ID_TYPES = frozenset({ID_SEDOL, ID_CUSIP, ID_TICKER})
# Bloomberg/OpenFIGI exchCode for a canonical U.S. listing exchange.
US_LISTING_TO_OPENFIGI_EXCH = {
    "NYSE": "UN",
    "NASDAQ": "UW",
    "AMEX": "UA",
    "ARCA": "UP",
}

ANON_MAX_JOBS_PER_REQUEST = 10
ANON_MAX_REQUESTS_PER_MINUTE = 25
KEYED_MAX_JOBS_PER_REQUEST = 100
MAX_429_SLEEP_SECONDS = 60.0
MAX_429_RETRIES = 1

MATCH_EXACT_SINGLE = "EXACT_SINGLE"
MATCH_MULTIPLE = "MULTIPLE_MATCHES"
MATCH_NONE = "NO_MATCH"
MATCH_ERROR = "PROVIDER_ERROR"


class OpenFigiError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenFigiJob:
    id_type: str
    id_value: str
    exch_code: str = ""

    def to_payload(self) -> dict[str, str]:
        payload = {"idType": self.id_type, "idValue": self.id_value}
        exch = str(self.exch_code or "").strip().upper()
        if exch:
            payload["exchCode"] = exch
        return payload


def openfigi_exch_code_for_listing(exchange: Any) -> str:
    from services.universe_listing_identity import normalize_us_exchange

    return US_LISTING_TO_OPENFIGI_EXCH.get(normalize_us_exchange(exchange), "")


@dataclass(frozen=True)
class OpenFigiCandidate:
    figi: str
    name: str
    ticker: str
    exch_code: str
    security_type: str
    security_type2: str
    market_sector: str
    composite_figi: str
    share_class_figi: str

    def to_dict(self) -> dict[str, str]:
        return {
            "figi": self.figi,
            "name": self.name,
            "ticker": self.ticker,
            "exchCode": self.exch_code,
            "securityType": self.security_type,
            "securityType2": self.security_type2,
            "marketSector": self.market_sector,
            "compositeFIGI": self.composite_figi,
            "shareClassFIGI": self.share_class_figi,
        }


@dataclass(frozen=True)
class OpenFigiJobResult:
    job: OpenFigiJob
    match_status: str
    http_status: int
    candidates: tuple[OpenFigiCandidate, ...] = ()
    warning: str = ""
    error: str = ""
    rate_limit_headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id_type": self.job.id_type,
            "id_value": self.job.id_value,
            "match_status": self.match_status,
            "http_status": self.http_status,
            "candidate_count": len(self.candidates),
            "warning": self.warning,
            "error": self.error,
            "candidates": [row.to_dict() for row in self.candidates],
        }


def resolve_openfigi_api_key(raw: Optional[str] = None) -> Optional[str]:
    """Optional key only. Missing/blank → anonymous public limits."""
    text = str(raw if raw is not None else os.environ.get("OPENFIGI_API_KEY") or "").strip()
    return text or None


def max_jobs_per_request(api_key: Optional[str]) -> int:
    return KEYED_MAX_JOBS_PER_REQUEST if api_key else ANON_MAX_JOBS_PER_REQUEST


def _candidate(row: Mapping[str, Any]) -> OpenFigiCandidate:
    return OpenFigiCandidate(
        figi=str(row.get("figi") or "").strip(),
        name=str(row.get("name") or "").strip(),
        ticker=str(row.get("ticker") or "").strip(),
        exch_code=str(row.get("exchCode") or "").strip(),
        security_type=str(row.get("securityType") or "").strip(),
        security_type2=str(row.get("securityType2") or "").strip(),
        market_sector=str(row.get("marketSector") or "").strip(),
        composite_figi=str(row.get("compositeFIGI") or "").strip(),
        share_class_figi=str(row.get("shareClassFIGI") or "").strip(),
    )


def parse_mapping_entry(entry: Any, *, job: OpenFigiJob, http_status: int) -> OpenFigiJobResult:
    if not isinstance(entry, Mapping):
        return OpenFigiJobResult(
            job=job,
            match_status=MATCH_ERROR,
            http_status=http_status,
            error="INVALID_ENTRY",
        )
    if entry.get("error"):
        return OpenFigiJobResult(
            job=job,
            match_status=MATCH_ERROR,
            http_status=http_status,
            error=str(entry.get("error")),
        )
    raw_rows = entry.get("data")
    if raw_rows is None:
        return OpenFigiJobResult(
            job=job,
            match_status=MATCH_NONE,
            http_status=http_status,
            warning=str(entry.get("warning") or "NO_IDENTIFIER_FOUND"),
        )
    if not isinstance(raw_rows, list):
        return OpenFigiJobResult(
            job=job,
            match_status=MATCH_ERROR,
            http_status=http_status,
            error="INVALID_DATA",
        )
    candidates = tuple(_candidate(row) for row in raw_rows if isinstance(row, Mapping))
    if not candidates:
        return OpenFigiJobResult(
            job=job,
            match_status=MATCH_NONE,
            http_status=http_status,
            warning=str(entry.get("warning") or "EMPTY_DATA"),
        )
    figis = {row.figi for row in candidates if row.figi}
    status = MATCH_EXACT_SINGLE if len(candidates) == 1 or len(figis) == 1 else MATCH_MULTIPLE
    if status == MATCH_EXACT_SINGLE and len(candidates) > 1:
        candidates = (candidates[0],)
    return OpenFigiJobResult(
        job=job,
        match_status=status,
        http_status=http_status,
        candidates=candidates,
        warning=str(entry.get("warning") or ""),
    )


def _rate_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    interesting = (
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "retry-after",
    )
    out: dict[str, str] = {}
    for key in interesting:
        value = None
        if hasattr(headers, "get"):
            value = headers.get(key) or headers.get(key.title())
        if value is not None:
            out[key] = str(value)
    return out


def _retry_after_seconds(headers: Mapping[str, Any]) -> float:
    raw = ""
    if hasattr(headers, "get"):
        raw = str(headers.get("Retry-After") or headers.get("retry-after") or "").strip()
    if not raw:
        return 5.0
    try:
        return min(MAX_429_SLEEP_SECONDS, max(1.0, float(raw)))
    except ValueError:
        return 5.0


class OpenFigiClient:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        timeout: int = 30,
        transport: Optional[Callable[..., tuple[int, Mapping[str, Any], Any]]] = None,
        sleeper: Callable[[float], None] = time.sleep,
        min_interval_seconds: Optional[float] = None,
    ) -> None:
        self.api_key = resolve_openfigi_api_key(api_key)
        self.timeout = timeout
        self.transport = transport
        self.sleeper = sleeper
        self.max_jobs = max_jobs_per_request(self.api_key)
        if min_interval_seconds is None:
            self.min_interval_seconds = 0.0 if self.api_key else 60.0 / ANON_MAX_REQUESTS_PER_MINUTE
        else:
            self.min_interval_seconds = float(min_interval_seconds)
        self.request_count = 0
        self._last_request_at = 0.0

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "NABI Scout investment research app openfigi-mapping/1.0",
        }
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key
        return headers

    def _pace(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self.min_interval_seconds - elapsed
        if self._last_request_at and wait > 0:
            self.sleeper(wait)

    def _post(self, payload: list[dict[str, str]]) -> tuple[int, Mapping[str, Any], Any]:
        if len(payload) > self.max_jobs:
            raise OpenFigiError(f"batch exceeds max jobs {self.max_jobs}")
        if self.transport is not None:
            self.request_count += 1
            self._last_request_at = time.monotonic()
            return self.transport(
                OPENFIGI_MAPPING_URL, self._headers(), payload
            )
        self._pace()
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            OPENFIGI_MAPPING_URL,
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = int(getattr(response, "status", 200) or 200)
                raw = response.read()
                headers = dict(response.headers.items())
        except HTTPError as exc:
            status = int(exc.code)
            raw = exc.read() if exc.fp is not None else b""
            headers = dict(exc.headers.items()) if exc.headers is not None else {}
        except URLError as exc:
            raise OpenFigiError(f"openfigi transport error: {exc}") from exc
        self.request_count += 1
        self._last_request_at = time.monotonic()
        parsed: Any
        try:
            parsed = json.loads(raw.decode("utf-8") or "null")
        except json.JSONDecodeError:
            parsed = None
        return status, headers, parsed

    def map_jobs(self, jobs: Sequence[OpenFigiJob]) -> tuple[OpenFigiJobResult, ...]:
        validated: list[OpenFigiJob] = []
        for job in jobs:
            id_type = str(job.id_type or "").strip()
            id_value = str(job.id_value or "").strip()
            exch_code = str(job.exch_code or "").strip().upper()
            if id_type not in SUPPORTED_ID_TYPES or not id_value:
                raise OpenFigiError(f"unsupported mapping job: {id_type}")
            if id_type == ID_TICKER and not exch_code:
                raise OpenFigiError("TICKER requires exchCode")
            validated.append(
                OpenFigiJob(id_type=id_type, id_value=id_value, exch_code=exch_code)
            )
        results: list[OpenFigiJobResult] = []
        for start in range(0, len(validated), self.max_jobs):
            batch = validated[start : start + self.max_jobs]
            status, headers, parsed = self._post([job.to_payload() for job in batch])
            retries = 0
            while status == 429 and retries < MAX_429_RETRIES:
                self.sleeper(_retry_after_seconds(headers))
                status, headers, parsed = self._post([job.to_payload() for job in batch])
                retries += 1
            rate = _rate_headers(headers)
            if status != 200 or not isinstance(parsed, list):
                error = f"HTTP_{status}"
                for job in batch:
                    results.append(
                        OpenFigiJobResult(
                            job=job,
                            match_status=MATCH_ERROR,
                            http_status=status,
                            error=error,
                            rate_limit_headers=rate,
                        )
                    )
                continue
            for job, entry in zip(batch, parsed + [None] * len(batch)):
                if entry is None:
                    results.append(
                        OpenFigiJobResult(
                            job=job,
                            match_status=MATCH_ERROR,
                            http_status=status,
                            error="MISSING_ENTRY",
                            rate_limit_headers=rate,
                        )
                    )
                    continue
                row = parse_mapping_entry(entry, job=job, http_status=status)
                results.append(
                    OpenFigiJobResult(
                        job=row.job,
                        match_status=row.match_status,
                        http_status=row.http_status,
                        candidates=row.candidates,
                        warning=row.warning,
                        error=row.error,
                        rate_limit_headers=rate,
                    )
                )
        return tuple(results)
