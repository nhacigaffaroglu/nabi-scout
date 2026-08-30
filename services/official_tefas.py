"""Parse official TEFAS JSON. No name/ticker country or profile inference."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Optional, Sequence

from services.fund_product_contract import (
    TEFAS_ENDPOINT_PRICES,
    TEFAS_PRICE_FIELD,
    TEFAS_PRICE_SEMANTICS,
    TefasPriceObservation,
    TefasPriceSeries,
)

TEFAS_HOST = "https://www.tefas.gov.tr"
TEFAS_PRICE_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_PRICES}"

SNAPSHOT_FIELDS = (
    "fonKodu",
    "fonUnvan",
    "sonFiyat",
    "gunlukGetiri",
    "payAdet",
    "portBuyukluk",
    "fonKategori",
    "kategoriDerece",
    "kategoriFonSay",
    "yatirimciSayi",
    "pazarPayi",
)
RETURNS_FIELDS = (
    "fonKodu",
    "fonUnvan",
    "fonTurAciklama",
    "tefasDurum",
    "riskDegeri",
)
PRICE_FIELDS = ("fonKodu", "fonUnvan", "tarih", "fiyat")


def normalize_fund_code(raw: Any) -> str:
    return str(raw or "").strip().upper()


def _text(raw: Any) -> Optional[str]:
    text = str(raw or "").strip()
    return text or None


def _float(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_tefas_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(payload or {})
    return {key: row.get(key) for key in SNAPSHOT_FIELDS}


def parse_tefas_returns(payload: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(payload or {})
    return {key: row.get(key) for key in RETURNS_FIELDS}


def _parse_iso_date(raw: str) -> Optional[date]:
    text = str(raw or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_tefas_price_history(
    rows: Sequence[Mapping[str, Any]],
    *,
    fund_code: str,
    period_months: Optional[int] = None,
    source_url: str = TEFAS_PRICE_URL,
) -> TefasPriceSeries:
    code = normalize_fund_code(fund_code)
    observations: list[TefasPriceObservation] = []
    seen: dict[str, int] = {}
    for raw in rows or ():
        row = dict(raw or {})
        row_code = normalize_fund_code(row.get("fonKodu") or code)
        if row_code != code:
            continue
        day = _text(row.get("tarih"))
        price = _float(row.get("fiyat"))
        if not day or price is None:
            continue
        seen[day] = seen.get(day, 0) + 1
        observations.append(
            TefasPriceObservation(
                date=day,
                price=price,
                fund_code=code,
                official_name=_text(row.get("fonUnvan")),
            )
        )
    observations.sort(key=lambda item: item.date)
    duplicate_dates = tuple(sorted(day for day, count in seen.items() if count > 1))
    first = observations[0].date if observations else None
    last = observations[-1].date if observations else None
    observed = {item.date for item in observations}
    missing: list[str] = []
    weekday_gaps: list[str] = []
    if first and last:
        cursor = date.fromisoformat(first)
        end = date.fromisoformat(last)
        while cursor <= end:
            key = cursor.isoformat()
            if key not in observed:
                missing.append(key)
                if cursor.weekday() < 5:
                    weekday_gaps.append(key)
            cursor += timedelta(days=1)
    return TefasPriceSeries(
        fund_code=code,
        first_date=first,
        last_date=last,
        observation_count=len(observations),
        duplicate_dates=duplicate_dates,
        missing_dates=tuple(missing),
        weekday_gaps=tuple(weekday_gaps),
        price_field=TEFAS_PRICE_FIELD,
        price_semantics=TEFAS_PRICE_SEMANTICS,
        source="tefas",
        source_url=source_url,
        period_months=period_months,
        observations=tuple(observations),
    )
