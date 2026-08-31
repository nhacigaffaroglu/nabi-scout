"""Official TEFAS 2026 unit-price history contract.

POST https://www.tefas.gov.tr/api/funds/fonFiyatBilgiGetir
{"fonKodu": "<CODE>", "dil": "TR", "periyod": <int>}

Working period buckets observed on the public site: 0, 1, 3, 6, 12, 13.
Canonical 1Y FI uses periyod=12. No date-window payloads. No fabricated days.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional

from services.fund_product_contract import PILOT_TEFAS_FUND_CODES, TEFAS_ENDPOINT_PRICES
from services.official_tefas import TEFAS_HOST, normalize_fund_code, parse_tefas_price_history
from services.official_turkiye_fund_evidence import load_tefas_price_rows
from services.turkiye_fund_source_capture import load_or_store

TEFAS_PRICE_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_PRICES}"
TEFAS_PUBLIC_ORIGIN = "https://www.tefas.gov.tr/"
TEFAS_HISTORY_DIL = "TR"
TEFAS_HISTORY_PERIOD_1Y = 12
TEFAS_HISTORY_PERIODS = (0, 1, 3, 6, 12, 13)
HISTORY_SOURCE_UNAVAILABLE = "HISTORY_SOURCE_UNAVAILABLE"


def tefas_history_payload(fund_code: str, *, periyod: int = TEFAS_HISTORY_PERIOD_1Y) -> dict[str, Any]:
    return {
        "fonKodu": normalize_fund_code(fund_code),
        "dil": TEFAS_HISTORY_DIL,
        "periyod": int(periyod),
    }


def rows_content_identity(rows: list[Mapping[str, Any]]) -> str:
    blob = "|".join(
        f"{row.get('fonKodu')}|{row.get('tarih')}|{row.get('fiyat')}"
        for row in rows
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def normalize_tefas_history_rows(
    rows: list[Mapping[str, Any]],
    *,
    fund_code: str,
    source_as_of: str,
    capture_time: str,
) -> list[dict[str, Any]]:
    """Keep actual official observations only. No weekend/holiday synthesis."""
    code = normalize_fund_code(fund_code)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        row = dict(raw or {})
        day = str(row.get("tarih") or "").strip()[:10]
        if not day or day in seen:
            continue
        seen.add(day)
        out.append(
            {
                "fonKodu": normalize_fund_code(row.get("fonKodu") or code),
                "fonUnvan": row.get("fonUnvan"),
                "tarih": day,
                "fiyat": row.get("fiyat"),
                "source": "TEFAS",
                "source_as_of": source_as_of,
                "capture_time": capture_time,
            }
        )
    out.sort(key=lambda item: str(item.get("tarih") or ""))
    return out


def _latest_date(rows: list[Mapping[str, Any]]) -> str:
    dates = [str(row.get("tarih") or "")[:10] for row in rows if row.get("tarih")]
    return max(dates) if dates else ""


def capture_tefas_history(
    session: Any,
    fund_code: str,
    *,
    periyod: int = TEFAS_HISTORY_PERIOD_1Y,
    as_of: Optional[date] = None,
    force: bool = False,
) -> dict[str, Any]:
    code = normalize_fund_code(fund_code)
    day = as_of or date(2026, 8, 31)
    if periyod not in TEFAS_HISTORY_PERIODS:
        return {
            "fonKodu": code,
            "available": False,
            "error": HISTORY_SOURCE_UNAVAILABLE,
            "periyod": periyod,
            "rows": [],
        }
    if code in PILOT_TEFAS_FUND_CODES and not force:
        try:
            frozen = load_tefas_price_rows(code, period_months=12)
        except (FileNotFoundError, ValueError, OSError):
            frozen = []
        if frozen:
            return {
                "fonKodu": code,
                "available": True,
                "periyod": periyod,
                "rows": list(frozen),
                "pilot_frozen": True,
                "source": "TEFAS",
                "latest_date": _latest_date(list(frozen)),
                "row_count": len(frozen),
            }

    def _fetch() -> dict[str, Any]:
        if hasattr(session, "tefas_warmed") and not getattr(session, "tefas_warmed", True):
            try:
                session.http_get_text(
                    TEFAS_PUBLIC_ORIGIN,
                    accept="text/html",
                    referer=TEFAS_PUBLIC_ORIGIN,
                )
            except Exception:  # noqa: BLE001 — public warmup is best-effort
                pass
            session.tefas_warmed = True
        payload = session.http_json(
            TEFAS_PRICE_URL,
            tefas_history_payload(code, periyod=periyod),
            referer=TEFAS_PUBLIC_ORIGIN,
        )
        error = payload.get("errorMessage")
        rows = list(payload.get("resultList") or [])
        if error or not rows:
            return {
                "fonKodu": code,
                "available": False,
                "error": error or HISTORY_SOURCE_UNAVAILABLE,
                "periyod": periyod,
                "rows": [],
                "http_error": error,
            }
        captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        normalized = normalize_tefas_history_rows(
            rows,
            fund_code=code,
            source_as_of=day.isoformat(),
            capture_time=captured_at,
        )
        latest = _latest_date(normalized)
        return {
            "fonKodu": code,
            "available": True,
            "periyod": periyod,
            "rows": normalized,
            "row_count": len(normalized),
            "latest_date": latest,
            "earliest_date": normalized[0]["tarih"] if normalized else None,
            "content_identity": rows_content_identity(normalized),
            "source": "TEFAS",
            "source_as_of": day.isoformat(),
            "capture_time": captured_at,
        }

    cached = None
    identity_key = f"{code}|periyod={periyod}"
    if not force:
        from services.turkiye_fund_source_capture import cache_identity, read_cached_payload

        cached = read_cached_payload(
            "tefas_prices_period",
            cache_identity(kind="tefas_prices_period", key=identity_key),
        )
        if cached and cached.get("available") and cached.get("latest_date"):
            latest = str(cached.get("latest_date") or "")[:10]
            if latest >= day.isoformat():
                return dict(cached)
    payload, _hit = load_or_store(
        kind="tefas_prices_period",
        key=identity_key,
        published_at="",
        fetcher=_fetch,
        force=force or bool(cached),
        stats=getattr(session, "stats", None),
    )
    return dict(payload)


def history_series_or_unavailable(payload: Mapping[str, Any], *, fund_code: str):
    rows = list(payload.get("rows") or [])
    if not payload.get("available") or not rows:
        return None
    return parse_tefas_price_history(
        rows,
        fund_code=fund_code,
        period_months=12,
        source_url=TEFAS_PRICE_URL,
    )
