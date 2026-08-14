from __future__ import annotations

import re
import statistics
from difflib import SequenceMatcher
from typing import Any, Iterable, List, Optional, Sequence


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
