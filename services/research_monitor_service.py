from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.change_detection_engine import detect_changes
from services.research_priority_engine import (
    compute_research_priority,
    rank_priority_entries,
)
from services.scan_snapshot import snapshot_from_candidate


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
