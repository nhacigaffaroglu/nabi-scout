from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.fund_analysis_contract import FundHolding

MAX_EXPENSE_RATIO_PCT = 10.0
MAX_WEIGHT_PCT = 100.0


def normalize_alpha_expense_ratio(value: Any) -> Optional[float]:
    number = _parse_percent_like(value)
    if number is None or number <= 0:
        return None
    if number <= 0.05:
        number *= 100.0
    if number > MAX_EXPENSE_RATIO_PCT:
        return None
    return round(number, 4)


def normalize_alpha_weight_pct(value: Any) -> Optional[float]:
    number = _parse_percent_like(value)
    if number is None or number <= 0:
        return None
    if number <= 1.0:
        number *= 100.0
    if number > MAX_WEIGHT_PCT:
        return None
    return round(number, 4)


def normalize_alpha_yield_pct(value: Any) -> Optional[float]:
    number = _parse_percent_like(value)
    if number is None or number <= 0:
        return None
    if number <= 1.0:
        number *= 100.0
    if number > 100.0:
        return None
    return round(number, 4)


def parse_alpha_holdings(rows: Any) -> List[FundHolding]:
    if not isinstance(rows, list):
        return []
    parsed: List[FundHolding] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        weight = normalize_alpha_weight_pct(row.get("weight"))
        if weight is None:
            continue
        parsed.append(
            FundHolding(
                symbol=_first_text(row.get("symbol")),
                name=_first_text(row.get("description"), row.get("name")),
                weight_pct=weight,
            )
        )
    parsed.sort(key=lambda item: item.weight_pct or 0.0, reverse=True)
    return parsed


def parse_alpha_sector_weights(rows: Any) -> Optional[Dict[str, float]]:
    if not isinstance(rows, list) or not rows:
        return None
    weights: Dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sector = _first_text(row.get("sector"))
        weight = normalize_alpha_weight_pct(row.get("weight"))
        if sector and weight is not None:
            weights[sector] = weight
    return weights or None


def alpha_daily_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    series_key = next((key for key in payload if "Time Series" in key), None)
    if not series_key:
        return []
    series = payload.get(series_key)
    if not isinstance(series, dict):
        return []
    rows: List[Dict[str, Any]] = []
    for date_text, values in series.items():
        if not isinstance(values, dict):
            continue
        close = values.get("4. close")
        volume = values.get("5. volume")
        if close in (None, ""):
            continue
        row: Dict[str, Any] = {"date": date_text, "close": close}
        if volume not in (None, ""):
            row["volume"] = volume
        rows.append(row)
    return rows


def alpha_profile_indicates_etf(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("holdings"), list) and payload["holdings"]:
        return True
    if payload.get("net_assets") not in (None, ""):
        return True
    if payload.get("net_expense_ratio") not in (None, ""):
        return True
    return False


def _parse_percent_like(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1].strip()
        try:
            return float(text)
        except ValueError:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_text(*values: Any) -> Optional[str]:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None
