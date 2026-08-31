"""Latest applicable published KAP PDR period.

On 2026-08-31 the August PDR publication window has not opened (starts
2026-09-01). July is the latest applicable published period. Missing the
unopened current-month PDR is not staleness.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Optional

from services.official_kap_pdr import parse_tr_datetime


def pdr_publication_window_opens(year: int, period: int) -> date:
    """PDR for calendar month `period` may be published from the 1st of the next month."""
    if period < 1 or period > 12:
        raise ValueError(f"invalid_pdr_period:{period}")
    if period == 12:
        return date(year + 1, 1, 1)
    return date(year, period + 1, 1)


def latest_applicable_pdr_period(as_of: date) -> tuple[int, int]:
    """Latest report period whose official publication window has opened."""
    if as_of.month == 1:
        return as_of.year - 1, 12
    return as_of.year, as_of.month - 1


def pdr_period_is_future(year: int, period: int, as_of: date) -> bool:
    return date(year, period, 1) > as_of.replace(day=1)


def pdr_period_is_applicable(year: int, period: int, as_of: date) -> bool:
    if pdr_period_is_future(year, period, as_of):
        return False
    return pdr_publication_window_opens(year, period) <= as_of


def pdr_row_is_applicable(row: Mapping[str, Any], as_of: date) -> bool:
    try:
        year = int(row.get("year"))
        period = int(row.get("period"))
    except (TypeError, ValueError):
        return False
    if period < 1 or period > 12:
        return False
    if not pdr_period_is_applicable(year, period, as_of):
        return False
    published = parse_tr_datetime(row.get("publishDate"))
    if published is not None and published.date() > as_of:
        return False
    return True


def current_month_pdr_missing_is_not_stale(as_of: date, *, has_current_month_pdr: bool) -> bool:
    """Absence of the in-window current-month PDR is expected until the window opens."""
    _ = has_current_month_pdr
    year, period = as_of.year, as_of.month
    return pdr_publication_window_opens(year, period) > as_of


def parse_as_of(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
