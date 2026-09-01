"""Official TEFAS/KAP capture for the Turkish fund universe.

Incremental cache by source identity / publication date / content hash.
Live network is opt-in. Default path reads captured official fixtures.
Does not persist production snapshots, 8E, or New Money.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import asdict, dataclass, field
from http.cookiejar import CookieJar
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

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

USER_AGENT = "NABI-Scout/FUND-7 (official TEFAS/KAP research; polite read-only)"
CACHE_DIR = Path(".cache/turkiye_fund_universe")
KAP_PDR_URL = f"{KAP_HOST}{KAP_FUNDS_BY_CRITERIA}"
KAP_FUND_DIRECTORY_URL = f"{KAP_HOST}/tr/YatirimFonlari/ALL"
KAP_PUBLIC_ORIGIN = "https://www.kap.org.tr/"
TEFAS_SNAPSHOT_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_SNAPSHOT}"
TEFAS_RETURNS_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_RETURNS}"
TEFAS_PRICE_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_PRICES}"
CATALOG_PATH = EVIDENCE_DIR / "kap_pdr_universe_catalog.json"
ACTIVITY_PATH = EVIDENCE_DIR / "tefas_participation_activity.json"
SAMPLE_SNAPSHOT_PATH = EVIDENCE_DIR / "tefas_universe_snapshot_sample.json"
PACK_CACHE_KIND = "evidence_pack"
PDR_TEXT_DIR = CACHE_DIR / "pdr_text"
MAX_RETRIES = 3
MAX_THROTTLE_RETRIES = 2
BACKOFF_SECONDS = (0.5, 1.0, 2.0)
THROTTLE_BACKOFF_SECONDS = (8.0, 20.0, 45.0)
REQUEST_TIMEOUT_SEC = 45
MIN_REQUEST_GAP_SEC = 0.35
KAP_MIN_GAP_SEC = 1.0
KAP_MAX_GAP_SEC = 8.0
THROTTLE_STATUS = frozenset({429, 502, 503})
CLIENT_NO_RETRY = frozenset({400, 401, 404, 405, 410})
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
    successful_requests: int = 0
    cache_hits: int = 0
    new_documents: int = 0
    unchanged_documents: int = 0
    failed_requests: int = 0
    retry_count: int = 0
    throttle_responses: int = 0
    wait_seconds: float = 0.0
    interval_sum: float = 0.0
    interval_n: int = 0
    runtime_ms: int = 0
    funds_attempted: int = 0
    funds_ok: int = 0
    funds_failed: int = 0
    skipped_unchanged: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["average_interval_sec"] = (
            round(self.interval_sum / self.interval_n, 3) if self.interval_n else 0.0
        )
        return payload


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
    elif "kap.org.tr" in url:
        headers["Origin"] = KAP_PUBLIC_ORIGIN
        headers["Referer"] = KAP_PUBLIC_ORIGIN
    request = Request(
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SEC) as response:
        return json.loads(response.read().decode("utf-8"))


class _KapFundDirectoryTableParser(HTMLParser):
    """Best-effort parser for the public KAP fund directory table.

    The parser is deliberately conservative: only rows with a plausible fund
    code plus name/founder are emitted. If KAP changes the page shape and the
    parser cannot recover enough rows, the caller fails closed and the older
    per-fund path remains available.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_tr = False
        self._in_td = False
        self._cells: list[str] = []
        self._cell_parts: list[str] = []
        self._row_links: list[str] = []
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        lower = tag.casefold()
        if lower == "tr":
            self._in_tr = True
            self._cells = []
            self._row_links = []
        elif lower in {"td", "th"} and self._in_tr:
            self._in_td = True
            self._cell_parts = []
        elif lower == "a" and self._in_tr:
            href = dict(attrs).get("href") or ""
            if href:
                self._row_links.append(str(href))

    def handle_data(self, data: str) -> None:
        if self._in_td:
            text = " ".join(str(data or "").split())
            if text:
                self._cell_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.casefold()
        if lower in {"td", "th"} and self._in_td:
            self._cells.append(" ".join(self._cell_parts).strip())
            self._cell_parts = []
            self._in_td = False
        elif lower == "tr" and self._in_tr:
            self._finish_row()
            self._in_tr = False

    def _finish_row(self) -> None:
        if len(self._cells) < 3:
            return
        code = normalize_fund_code(self._cells[0])
        name = self._cells[1].strip()
        founder = self._cells[2].strip()
        if not code or not code.isalnum() or len(code) > 12 or not name or not founder:
            return
        slug = ""
        for href in self._row_links:
            marker = "/fon-bilgileri/ozet/"
            if marker in href:
                slug = href.split(marker, 1)[1].split("?", 1)[0].strip("/")
                break
        self.rows.append({"fund_code": code, "fund_name": name, "founder": founder, "slug": slug})


def parse_kap_fund_directory_html(text: str) -> dict[str, dict[str, str]]:
    parser = _KapFundDirectoryTableParser()
    parser.feed(str(text or ""))
    out: dict[str, dict[str, str]] = {}
    for row in parser.rows:
        code = row["fund_code"]
        if code not in out:
            out[code] = row
    return out


def capture_kap_fund_directory(session: "OfficialCaptureSession") -> dict[str, dict[str, str]]:
    """Capture KAP's public all-funds directory once per cache cycle.

    This is identity evidence only. It does not replace YBF/izahname/PDR
    evidence and cannot by itself authorize Participation or FI.
    """

    def _fetch() -> dict[str, Any]:
        html = session.http_get_text(
            KAP_FUND_DIRECTORY_URL,
            accept="text/html",
            referer=KAP_PUBLIC_ORIGIN,
        )
        rows = parse_kap_fund_directory_html(html)
        if len(rows) < 100:
            raise ValueError(f"kap_fund_directory_parse_incomplete:{len(rows)}")
        return {"rows": list(rows.values())}

    payload, _hit = load_or_store(
        kind="kap_fund_directory_v1",
        key="ALL",
        fetcher=_fetch,
        stats=session.stats,
    )
    return {
        normalize_fund_code(row.get("fund_code")): dict(row)
        for row in list(payload.get("rows") or [])
        if normalize_fund_code(row.get("fund_code"))
    }


@dataclass
class OfficialCaptureSession:
    """Polite official HTTP: one client, cookie reuse, adaptive KAP pacing."""

    live: bool = False
    stats: CaptureRunStats = field(default_factory=CaptureRunStats)
    sleep: Callable[[float], None] = time.sleep
    opener: Optional[Callable[..., Any]] = None
    last_request_at: float = 0.0
    timeout_sec: int = REQUEST_TIMEOUT_SEC
    min_gap_sec: float = MIN_REQUEST_GAP_SEC
    tefas_warmed: bool = False
    kap_warmed: bool = False
    cookie_jar: CookieJar = field(default_factory=CookieJar)
    jitter_fn: Callable[[], float] = lambda: random.uniform(0.85, 1.15)
    consecutive_throttles: int = 0

    def __post_init__(self) -> None:
        if self.opener is None:
            self._urlopen = build_opener(HTTPCookieProcessor(self.cookie_jar)).open
        else:
            self._urlopen = self.opener

    def _pace(self) -> None:
        if self.min_gap_sec <= 0:
            return
        now = time.monotonic()
        wait = self.min_gap_sec - (now - self.last_request_at)
        if wait > 0:
            self.sleep(wait)
            self.stats.wait_seconds += wait

    def _mark_interval(self) -> None:
        now = time.monotonic()
        if self.last_request_at > 0:
            self.stats.interval_sum += now - self.last_request_at
            self.stats.interval_n += 1
        self.last_request_at = now

    def _retry_after_seconds(self, exc: HTTPError, attempt: int) -> float:
        raw = ""
        try:
            raw = str((exc.headers or {}).get("Retry-After") or "").strip()
        except Exception:  # noqa: BLE001
            raw = ""
        if raw.isdigit():
            return min(float(raw), 90.0)
        base = THROTTLE_BACKOFF_SECONDS[min(attempt, len(THROTTLE_BACKOFF_SECONDS) - 1)]
        return min(base * self.jitter_fn(), 90.0)

    def _on_throttle(self, exc: HTTPError, attempt: int) -> None:
        self.stats.throttle_responses += 1
        self.stats.retry_count += 1
        self.consecutive_throttles += 1
        self.min_gap_sec = min(max(self.min_gap_sec * 1.5, KAP_MIN_GAP_SEC), KAP_MAX_GAP_SEC)
        wait = self._retry_after_seconds(exc, attempt)
        if self.consecutive_throttles >= 8:
            wait = max(wait, 30.0)
            self.consecutive_throttles = 0
        self.stats.wait_seconds += wait
        self.sleep(wait)

    def _on_success(self) -> None:
        self.stats.successful_requests += 1
        self.consecutive_throttles = 0
        if self.min_gap_sec > KAP_MIN_GAP_SEC:
            self.min_gap_sec = max(KAP_MIN_GAP_SEC, round(self.min_gap_sec * 0.9, 3))

    def _open(self, request: Request) -> bytes:
        self._pace()
        self._mark_interval()
        self.stats.requests_attempted += 1
        last_error: Optional[BaseException] = None
        throttle_tries = 0
        for attempt in range(MAX_RETRIES):
            try:
                with self._urlopen(request, timeout=self.timeout_sec) as response:
                    payload = bytes(response.read())
                    self._on_success()
                    return payload
            except HTTPError as exc:
                last_error = exc
                code = int(getattr(exc, "code", 0) or 0)
                if code in THROTTLE_STATUS:
                    if throttle_tries >= MAX_THROTTLE_RETRIES:
                        break
                    throttle_tries += 1
                    self._on_throttle(exc, throttle_tries)
                    continue
                if code in CLIENT_NO_RETRY:
                    self.stats.failed_requests += 1
                    raise
                self.stats.retry_count += 1
                if attempt >= MAX_RETRIES - 1:
                    break
                self.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                self.stats.retry_count += 1
                if attempt >= MAX_RETRIES - 1:
                    break
                self.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
        self.stats.failed_requests += 1
        raise last_error or URLError("official_http_failed")

    def ensure_kap_session(self) -> None:
        """One public homepage hit to obtain KAP's normal session cookies."""
        if self.kap_warmed:
            return
        try:
            self.http_get_text(
                KAP_PUBLIC_ORIGIN,
                accept="text/html",
                referer=KAP_PUBLIC_ORIGIN,
            )
        except Exception:  # noqa: BLE001 — warmup is best-effort
            pass
        self.kap_warmed = True

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
        elif "kap.org.tr" in url:
            headers["Origin"] = KAP_PUBLIC_ORIGIN
            headers["Referer"] = KAP_PUBLIC_ORIGIN
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
        if "kap.org.tr" in url:
            headers.setdefault("Origin", "https://www.kap.org.tr")
            headers.setdefault("Referer", referer or KAP_PUBLIC_ORIGIN)
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
