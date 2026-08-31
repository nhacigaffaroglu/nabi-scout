"""Official TEFAS/KAP capture for the Turkish fund universe.

Incremental cache by source identity / publication date / content hash.
Live network is opt-in. Default path reads captured official fixtures.
Does not persist production snapshots, 8E, or New Money.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.request import Request, urlopen

from services.fund_product_contract import KAP_FUNDS_BY_CRITERIA, PDR_SUBJECT_OID, TEFAS_ENDPOINT_SNAPSHOT
from services.official_kap_pdr import KAP_HOST
from services.official_tefas import TEFAS_HOST, normalize_fund_code
from services.official_turkiye_fund_evidence import EVIDENCE_DIR

USER_AGENT = "NABI-Scout/FUND-4 (official TEFAS/KAP research; polite read-only)"
CACHE_DIR = Path(".cache/turkiye_fund_universe")
KAP_PDR_URL = f"{KAP_HOST}{KAP_FUNDS_BY_CRITERIA}"
TEFAS_SNAPSHOT_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_SNAPSHOT}"
CATALOG_PATH = EVIDENCE_DIR / "kap_pdr_universe_catalog.json"
ACTIVITY_PATH = EVIDENCE_DIR / "tefas_participation_activity.json"
SAMPLE_SNAPSHOT_PATH = EVIDENCE_DIR / "tefas_universe_snapshot_sample.json"
PAID_HOST_BLOCKLIST = (
    "yahoo",
    "alphavantage",
    "financialmodelingprep",
    "fmpcloud",
    "polygon.io",
    "twelve.data",
)


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
) -> tuple[dict[str, Any], bool]:
    """Return (payload, cache_hit). Unchanged documents are not rewritten."""
    identity = cache_identity(kind=kind, key=key, published_at=published_at)
    if not force:
        cached = read_cached_payload(kind, identity)
        if cached is not None:
            return dict(cached), True
    payload = dict(fetcher())
    write_cached_payload(kind, identity, payload)
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
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


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
