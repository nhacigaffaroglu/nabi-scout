from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.change_detection_engine import detect_changes
from services.research_history_service import (
    CATEGORY_ATTENTION,
    CATEGORY_DATA_ISSUES,
    CATEGORY_NEW,
    CATEGORY_WATCHLIST,
    build_monitor_entries,
    group_entries_by_category,
    sort_monitor_entries,
    top_priority_entries,
)
from services.research_priority_engine import (
    compute_research_priority,
    rank_priority_entries,
)
from services.scan_snapshot import normalize_universe_name, snapshot_from_candidate

__all__ = (
    "build_monitor_feed",
    "build_priority_entries",
    "build_priority_teaser_from_monitor",
    "resolve_recent_change",
    "summarize_change",
)


def resolve_recent_change(
    scan_repo,
    candidate: Dict[str, Any],
) -> tuple[Optional[Dict[str, Any]], bool]:
    symbol = candidate.get("symbol")
    if not symbol:
        return None, True

    latest_row = scan_repo.get_latest_scan_row(symbol)
    if not latest_row:
        return None, True

    previous = scan_repo.row_to_snapshot(latest_row)
    current = snapshot_from_candidate(candidate)
    change = detect_changes(previous, current)
    return change, bool(change.get("no_previous"))


def build_priority_entries(
    candidates: List[Dict[str, Any]],
    *,
    scan_repo,
    watched_candidate_ids: Optional[set[str]] = None,
    latest_scan_rows: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    watched = watched_candidate_ids or set()
    scan_rows = latest_scan_rows
    if scan_rows is None and scan_repo is not None:
        symbols = [
            str(candidate.get("symbol"))
            for candidate in candidates
            if candidate.get("symbol")
        ]
        scan_rows = scan_repo.get_latest_scan_rows_for_symbols(symbols)

    entries: List[Dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate.get("id")
        change, is_first_seen = _resolve_change_for_candidate(
            candidate,
            scan_repo=scan_repo,
            latest_row=(scan_rows or {}).get(candidate.get("symbol")),
        )
        priority = compute_research_priority(
            candidate,
            recent_change=change,
            is_user_watchlist=str(candidate_id) in watched if candidate_id else False,
            is_first_seen=is_first_seen,
        )
        entries.append({
            **priority,
            "candidate": candidate,
            "recent_change": change,
            "is_first_seen": is_first_seen,
        })
    return rank_priority_entries(entries)


def _resolve_change_for_candidate(
    candidate: Dict[str, Any],
    *,
    scan_repo,
    latest_row: Optional[Dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], bool]:
    if latest_row is None and scan_repo is not None:
        symbol = candidate.get("symbol")
        if symbol:
            latest_row = scan_repo.get_latest_scan_row(symbol)

    if not latest_row:
        return None, True

    previous = scan_repo.row_to_snapshot(latest_row)
    current = snapshot_from_candidate(candidate)
    change = detect_changes(previous, current)
    return change, bool(change.get("no_previous"))


def summarize_change(recent_change: Optional[Dict[str, Any]]) -> str:
    if not recent_change:
        return "Önceki tarama bulunamadı"
    if not recent_change.get("has_meaningful_change"):
        return "Anlamlı değişiklik yok"
    changes = recent_change.get("changes") or []
    if not changes:
        return "Anlamlı değişiklik yok"
    return changes[0].get("message") or "Değişiklik var"


def build_monitor_feed(
    *,
    scan_repo,
    candidates: Optional[List[Dict[str, Any]]] = None,
    watched_candidate_ids: Optional[set[str]] = None,
    since: Optional[datetime] = None,
    universe_name: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    window_start = since or (datetime.now(timezone.utc) - timedelta(days=7))
    runs = scan_repo.get_completed_runs_since(window_start, universe_name)
    run_ids = [run["id"] for run in runs if run.get("id")]
    rows = scan_repo.get_results_for_runs(run_ids)

    candidates_by_symbol: Dict[str, Dict[str, Any]] = {}
    if candidates:
        for candidate in candidates:
            symbol = candidate.get("symbol")
            if symbol:
                candidates_by_symbol[str(symbol).strip().upper()] = candidate

    symbols = list({str(row.get("symbol")).strip().upper() for row in rows if row.get("symbol")})
    pre_window_run_ids = scan_repo.get_all_completed_run_ids_before(
        window_start,
        universe_name,
    )
    pre_window_symbols = scan_repo.get_symbols_with_results_before(
        symbols,
        window_start,
        run_ids=pre_window_run_ids,
    )

    entries = build_monitor_entries(
        rows,
        snapshot_fn=scan_repo.row_to_snapshot,
        candidates_by_symbol=candidates_by_symbol,
        watched_candidate_ids=watched_candidate_ids or set(),
        pre_window_symbols=pre_window_symbols,
    )
    grouped = group_entries_by_category(entries)
    ordered_entries = sort_monitor_entries([
        entry for entry in entries if entry.get("primary_category") != "NONE"
    ])
    if limit is not None:
        ordered_entries = ordered_entries[:limit]

    return {
        "since": window_start,
        "universe_name": normalize_universe_name(universe_name) or None,
        "runs": runs,
        "entries": ordered_entries,
        "by_category": grouped,
        "categories": {
            "ATTENTION": grouped.get(CATEGORY_ATTENTION, []),
            "WATCHLIST": grouped.get(CATEGORY_WATCHLIST, []),
            "NEW": grouped.get(CATEGORY_NEW, []),
            "DATA_ISSUES": grouped.get(CATEGORY_DATA_ISSUES, []),
        },
    }


def build_priority_teaser_from_monitor(
    *,
    scan_repo,
    candidates: List[Dict[str, Any]],
    watched_candidate_ids: Optional[set[str]] = None,
    since: Optional[datetime] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    feed = build_monitor_feed(
        scan_repo=scan_repo,
        candidates=candidates,
        watched_candidate_ids=watched_candidate_ids,
        since=since,
    )
    teaser_entries = top_priority_entries(feed["entries"], limit=limit)
    results: List[Dict[str, Any]] = []
    for entry in teaser_entries:
        candidate = entry.get("candidate") or {
            "symbol": entry.get("symbol"),
            "company_name": entry.get("company_name"),
        }
        results.append({
            **(entry.get("research_priority") or {}),
            "candidate": candidate,
            "recent_change": entry.get("recent_change"),
            "is_first_seen": entry.get("is_first_seen_in_window"),
            "primary_category": entry.get("primary_category"),
            "events": entry.get("events") or [],
        })
    return results
