"""Official TEFAS/KAP capture for the Turkish fund universe.

Incremental cache by source identity / publication date / content hash.
Live network is opt-in. Default path reads captured official fixtures.
Does not persist production snapshots, 8E, or New Money.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from services.fund_product_contract import (
    KAP_FUNDS_BY_CRITERIA,
    PDR_SUBJECT_OID,
    TEFAS_ENDPOINT_PRICES,
    TEFAS_ENDPOINT_RETURNS,
    TEFAS_ENDPOINT_SNAPSHOT,
)
from services.official_kap_pdr import KAP_HOST
from services.official_tefas import TEFAS_HOST, normalize_fund_code
from services.official_turkiye_fund_evidence import EVIDENCE_DIR

USER_AGENT = "NABI-Scout/FUND-5 (official TEFAS/KAP research; polite read-only)"
CACHE_DIR = Path(".cache/turkiye_fund_universe")
KAP_PDR_URL = f"{KAP_HOST}{KAP_FUNDS_BY_CRITERIA}"
TEFAS_SNAPSHOT_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_SNAPSHOT}"
TEFAS_RETURNS_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_RETURNS}"
TEFAS_PRICE_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_PRICES}"
CATALOG_PATH = EVIDENCE_DIR / "kap_pdr_universe_catalog.json"
ACTIVITY_PATH = EVIDENCE_DIR / "tefas_participation_activity.json"
SAMPLE_SNAPSHOT_PATH = EVIDENCE_DIR / "tefas_universe_snapshot_sample.json"
PACK_CACHE_KIND = "evidence_pack"
PDR_TEXT_DIR = CACHE_DIR / "pdr_text"
MAX_RETRIES = 3
BACKOFF_SECONDS = (0.5, 1.0, 2.0)
REQUEST_TIMEOUT_SEC = 45
MIN_REQUEST_GAP_SEC = 0.35
PAID_HOST_BLOCKLIST = (
    "yahoo",
    "alphavantage",
    "financialmodelingprep",
    "fmpcloud",
    "polygon.io",
    "twelve.data",
)


@dataclass
class CaptureRunStats:
    requests_attempted: int = 0
    cache_hits: int = 0
    new_documents: int = 0
    unchanged_documents: int = 0
    failed_requests: int = 0
    retry_count: int = 0
    runtime_ms: int = 0
    funds_attempted: int = 0
    funds_ok: int = 0
    funds_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_identity(*, kind: str, key: str, published_at: str = "") -> str:
    return _sha(f"{kind}|{key}|{published_at}")[:24]


def _cache_path(kind: str, identity: str) -> Path:
    return CACHE_DIR / kind / f"{identity}.json"


def read_cached_payload(kind: str, identity: str) -> Optional[dict[str, Any]]:
    path = _cache_path(kind, identity)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_cached_payload(kind: str, identity: str, payload: Mapping[str, Any]) -> Path:
    path = _cache_path(kind, identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    if existing == body:
        return path
    path.write_text(body, encoding="utf-8")
    return path


def load_or_store(
    *,
    kind: str,
    key: str,
    published_at: str = "",
    fetcher: Callable[[], Mapping[str, Any]],
    force: bool = False,
    stats: Optional[CaptureRunStats] = None,
) -> tuple[dict[str, Any], bool]:
    """Return (payload, cache_hit). Unchanged documents are not rewritten."""
    identity = cache_identity(kind=kind, key=key, published_at=published_at)
    if not force:
        cached = read_cached_payload(kind, identity)
        if cached is not None:
            if stats is not None:
                stats.cache_hits += 1
                stats.unchanged_documents += 1
            return dict(cached), True
    payload = dict(fetcher())
    path = _cache_path(kind, identity)
    existed = path.is_file()
    previous = path.read_text(encoding="utf-8") if existed else None
    write_cached_payload(kind, identity, payload)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if stats is not None:
        if previous == body:
            stats.unchanged_documents += 1
        else:
            stats.new_documents += 1
    return payload, False


def assert_official_host(url: str) -> None:
    lowered = str(url or "").strip().casefold()
    if any(token in lowered for token in PAID_HOST_BLOCKLIST):
        raise ValueError(f"paid_or_unofficial_source_refused:{url}")
    if "tefas.gov.tr" not in lowered and "kap.org.tr" not in lowered:
        raise ValueError(f"unofficial_source_refused:{url}")


def _http_json(url: str, payload: Mapping[str, Any], *, referer: str = "") -> Any:
    assert_official_host(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if referer:
        headers["Origin"] = referer
        headers["Referer"] = referer
    request = Request(
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SEC) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass
class OfficialCaptureSession:
    """Polite official HTTP with retry/backoff, cache, and per-run stats."""

    live: bool = False
    stats: CaptureRunStats = field(default_factory=CaptureRunStats)
    sleep: Callable[[float], None] = time.sleep
    opener: Optional[Callable[..., Any]] = None
    last_request_at: float = 0.0
    timeout_sec: int = REQUEST_TIMEOUT_SEC
    min_gap_sec: float = MIN_REQUEST_GAP_SEC

    def _pace(self) -> None:
        if self.min_gap_sec <= 0:
            return
        now = time.monotonic()
        wait = self.min_gap_sec - (now - self.last_request_at)
        if wait > 0:
            self.sleep(wait)

    def _open(self, request: Request) -> bytes:
        opener = self.opener or urlopen
        self._pace()
        self.last_request_at = time.monotonic()
        self.stats.requests_attempted += 1
        last_error: Optional[BaseException] = None
        for attempt in range(MAX_RETRIES):
            try:
                with opener(request, timeout=self.timeout_sec) as response:
                    return bytes(response.read())
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = exc
                self.stats.retry_count += 1
                if attempt >= MAX_RETRIES - 1:
                    break
                self.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
        self.stats.failed_requests += 1
        raise last_error or URLError("official_http_failed")

    def http_json(self, url: str, payload: Mapping[str, Any], *, referer: str = "") -> Any:
        assert_official_host(url)
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if referer:
            headers["Origin"] = referer
            headers["Referer"] = referer
        request = Request(
            url,
            data=json.dumps(dict(payload)).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        raw = self._open(request)
        return json.loads(raw.decode("utf-8"))

    def http_get_bytes(
        self,
        url: str,
        *,
        accept: str = "*/*",
        referer: str = "",
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> bytes:
        assert_official_host(url)
        headers = {"User-Agent": USER_AGENT, "Accept": accept}
        if referer:
            headers["Referer"] = referer
        if extra_headers:
            headers.update(dict(extra_headers))
        request = Request(url, headers=headers, method="GET")
        return self._open(request)

    def http_get_text(
        self,
        url: str,
        *,
        accept: str = "text/html",
        referer: str = "",
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> str:
        return self.http_get_bytes(
            url, accept=accept, referer=referer, extra_headers=extra_headers
        ).decode("utf-8", "replace")

    def kap_rsc(self, url: str) -> str:
        if "?" in url:
            rsc_url = url if "_rsc=" in url else f"{url}&_rsc=1"
        else:
            rsc_url = f"{url}?_rsc=1"
        return self.http_get_text(
            rsc_url,
            accept="text/x-component",
            referer="https://www.kap.org.tr/",
            extra_headers={"RSC": "1"},
        )


def load_captured_kap_pdr_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def load_captured_tefas_activity() -> dict[str, Any]:
    return json.loads(ACTIVITY_PATH.read_text(encoding="utf-8"))


def load_captured_tefas_snapshots() -> dict[str, dict[str, Any]]:
    activity = dict(load_captured_tefas_activity().get("snapshots") or {})
    if SAMPLE_SNAPSHOT_PATH.is_file():
        sample = json.loads(SAMPLE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        for code, row in dict(sample.get("snapshots") or {}).items():
            key = normalize_fund_code(code)
            if row:
                activity[key] = {**dict(row), "tefas_present": True}
            elif key not in activity:
                activity[key] = {"fonKodu": key, "tefas_present": False}
    return {normalize_fund_code(code): dict(row) for code, row in activity.items()}


def fetch_kap_pdr_window(from_date: str, to_date: str, *, live: bool = False) -> list[dict[str, Any]]:
    key = f"{from_date}|{to_date}|{PDR_SUBJECT_OID}"

    def _fetch() -> dict[str, Any]:
        rows = _http_json(
            KAP_PDR_URL,
            {
                "fromDate": from_date,
                "toDate": to_date,
                "subjectList": [PDR_SUBJECT_OID],
            },
            referer="https://www.kap.org.tr/tr/bildirim-sorgu",
        )
        return {"rows": list(rows or [])}

    if not live:
        cached = read_cached_payload("kap_pdr_window", cache_identity(kind="kap_pdr_window", key=key))
        if cached is not None:
            return [dict(row) for row in cached.get("rows") or []]
        catalog = load_captured_kap_pdr_catalog()
        return [dict(row) for row in catalog.get("rows") or []]
    payload, _hit = load_or_store(kind="kap_pdr_window", key=key, fetcher=_fetch)
    return [dict(row) for row in payload.get("rows") or []]


def fetch_tefas_snapshot(fund_code: str, *, live: bool = False) -> Optional[dict[str, Any]]:
    code = normalize_fund_code(fund_code)
    if not live:
        return dict(load_captured_tefas_snapshots().get(code) or {"fonKodu": code, "tefas_present": False})

    def _fetch() -> dict[str, Any]:
        payload = _http_json(TEFAS_SNAPSHOT_URL, {"fonKodu": code})
        rows = list(payload.get("resultList") or [])
        if not rows:
            return {"fonKodu": code, "tefas_present": False}
        return {**dict(rows[0]), "tefas_present": True}

    payload, _hit = load_or_store(kind="tefas_snapshot", key=code, fetcher=_fetch)
    return dict(payload)


def cached_pdr_text_path(fund_code: str, period: str = "") -> Optional[Path]:
    code = normalize_fund_code(fund_code)
    if not code:
        return None
    if period:
        path = PDR_TEXT_DIR / f"{code}_{period.replace('-', '.')}.txt"
        return path if path.is_file() else None
    matches = sorted(PDR_TEXT_DIR.glob(f"{code}_*.txt"))
    return matches[-1] if matches else None


def write_cached_pdr_text(fund_code: str, period: str, text: str) -> Path:
    code = normalize_fund_code(fund_code)
    PDR_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = PDR_TEXT_DIR / f"{code}_{str(period or 'unknown').replace('-', '.')}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def evidence_pack_cache_key(fund_code: str) -> str:
    return cache_identity(kind=PACK_CACHE_KIND, key=normalize_fund_code(fund_code))


def read_evidence_pack(fund_code: str) -> Optional[dict[str, Any]]:
    return read_cached_payload(PACK_CACHE_KIND, evidence_pack_cache_key(fund_code))


def write_evidence_pack(fund_code: str, payload: Mapping[str, Any]) -> Path:
    return write_cached_payload(PACK_CACHE_KIND, evidence_pack_cache_key(fund_code), payload)


def load_cached_evidence_packs() -> dict[str, dict[str, Any]]:
    folder = CACHE_DIR / PACK_CACHE_KIND
    if not folder.is_dir():
        return {}
    packs: dict[str, dict[str, Any]] = {}
    for path in folder.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        code = normalize_fund_code(payload.get("fund_code") or "")
        if code:
            packs[code] = dict(payload)
    return packs
