from __future__ import annotations

import re
import statistics
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def fiscal_period_key(row: Dict[str, Any]) -> Optional[Tuple[int, str]]:
    period = row.get("period")
    year = row.get("calendarYear")
    if year is not None and period:
        try:
            return int(year), str(period).strip().upper()
        except (TypeError, ValueError):
            pass
    period_text = str(period or "").strip().upper()
    if "-" in period_text:
        year_part, quarter_part = period_text.split("-", 1)
        if year_part.isdigit() and quarter_part.startswith("Q"):
            return int(year_part), quarter_part
    date_text = str(row.get("date") or "").strip()
    if len(date_text) >= 7:
        try:
            year_part = int(date_text[:4])
            month = int(date_text[5:7])
            quarter = f"Q{(month - 1) // 3 + 1}"
            return year_part, quarter
        except (TypeError, ValueError):
            return None
    return None


def find_yoy_pair(
    rows: Sequence[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not rows:
        return None, None
    latest = rows[0]
    latest_key = fiscal_period_key(latest)
    if latest_key is not None:
        target = (latest_key[0] - 1, latest_key[1])
        for row in rows[1:]:
            if fiscal_period_key(row) == target:
                return latest, row
    if len(rows) >= 5:
        return latest, rows[4]
    return latest, None


def find_matching_statement_row(
    rows: Sequence[Dict[str, Any]],
    anchor: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not rows or anchor is None:
        return None
    anchor_key = fiscal_period_key(anchor)
    anchor_date = str(anchor.get("date") or "").strip()
    if anchor_key is not None:
        for row in rows:
            if fiscal_period_key(row) == anchor_key:
                return row
    if anchor_date:
        for row in rows:
            if str(row.get("date") or "").strip() == anchor_date:
                return row
    return rows[0] if rows else None


def safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, "", "None", "null"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    if previous < 0 and current > 0:
        return None
    return ((current - previous) / abs(previous)) * 100.0


def direction_from_change(
    change_pct: Optional[float],
    *,
    higher_is_better: bool = True,
) -> str:
    if change_pct is None:
        return "UNKNOWN"
    if abs(change_pct) <= 2.0:
        return "STABLE"
    improving = change_pct > 0 if higher_is_better else change_pct < 0
    if improving:
        return "IMPROVING"
    if change_pct < 0 if higher_is_better else change_pct > 0:
        return "DETERIORATING"
    return "MIXED"


def median_value(values: Sequence[Optional[float]]) -> Optional[float]:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return float(statistics.median(clean))


def percentile_rank(value: Optional[float], sample: Sequence[Optional[float]]) -> Optional[float]:
    clean = sorted(item for item in sample if item is not None)
    if value is None or not clean:
        return None
    below = sum(1 for item in clean if item < value)
    return round((below / len(clean)) * 100.0, 2)


def normalize_headline(text: str) -> str:
    lowered = re.sub(r"\s+", " ", (text or "").strip().lower())
    return re.sub(r"[^\w\s]", "", lowered)


def headlines_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, normalize_headline(a), normalize_headline(b)).ratio() >= 0.92


def normalize_url(url: str) -> str:
    return re.sub(r"[?#].*$", "", (url or "").strip().lower())


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def serialize_optional(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, (list, tuple)):
        return [serialize_optional(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_optional(item) for key, item in value.items()}
    return value
