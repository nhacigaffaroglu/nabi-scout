from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _parse_ts(value: Optional[str]) -> datetime:
    normalized = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def snapshot_sort_key(row: Dict[str, Any]) -> Tuple[datetime, datetime, str]:
    """Deterministic ordering for canonical snapshot selection.

    Matches repository list order (captured_at desc, created_at desc) with id
    as final tie-breaker so concurrent inserts resolve consistently.
    """
    captured = _parse_ts(str(row.get("captured_at") or "1970-01-01T00:00:00+00:00"))
    created = _parse_ts(str(row.get("created_at") or row.get("captured_at") or "1970-01-01T00:00:00+00:00"))
    return (captured, created, str(row.get("id") or ""))


def select_canonical_snapshot_row(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    materialized = list(rows)
    if not materialized:
        raise ValueError("select_canonical_snapshot_row requires at least one row")
    return max(materialized, key=snapshot_sort_key)


def group_duplicate_snapshot_rows(
    rows: Iterable[Dict[str, Any]],
) -> Dict[Tuple[str, date], List[Dict[str, Any]]]:
    groups: Dict[Tuple[str, date], List[Dict[str, Any]]] = {}
    for row in rows:
        portfolio_id = str(row.get("portfolio_id") or "")
        snapshot_date_raw = row.get("snapshot_date")
        if snapshot_date_raw is None:
            captured = str(row.get("captured_at") or "")
            if not captured:
                continue
            snapshot_day = _parse_ts(captured).date()
        else:
            snapshot_day = date.fromisoformat(str(snapshot_date_raw)[:10])
        key = (portfolio_id, snapshot_day)
        groups.setdefault(key, []).append(row)
    return {key: value for key, value in groups.items() if len(value) > 1}


def nullable_field_diffs(
    canonical: Dict[str, Any],
    duplicate: Dict[str, Any],
    *,
    fields: Tuple[str, ...] = (
        "priced_market_value",
        "total_cost_basis",
        "unrealized_pl",
        "cash_value",
        "invested_value",
        "liabilities_total",
        "net_wealth_partial",
        "priced_position_coverage_pct",
        "unpriced_position_count",
        "mixed_currency_warning",
    ),
) -> Dict[str, Tuple[Any, Any]]:
    diffs: Dict[str, Tuple[Any, Any]] = {}
    for field in fields:
        left = canonical.get(field)
        right = duplicate.get(field)
        if left != right and not (left is None and right is None):
            diffs[field] = (left, right)
    return diffs


def merge_nullable_fields_into_canonical(
    canonical: Dict[str, Any],
    duplicates: Iterable[Dict[str, Any]],
    *,
    fields: Tuple[str, ...] = ("liabilities_total", "net_wealth_partial"),
) -> Dict[str, Any]:
    merged = dict(canonical)
    ordered_dupes = sorted(duplicates, key=snapshot_sort_key, reverse=True)
    for field in fields:
        if merged.get(field) is not None:
            continue
        for dupe in ordered_dupes:
            value = dupe.get(field)
            if value is not None:
                merged[field] = value
                break
    return merged
