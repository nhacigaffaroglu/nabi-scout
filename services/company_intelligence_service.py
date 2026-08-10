from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.research_history_service import (
    build_symbol_monitor_entry,
)
from services.research_priority_engine import compute_research_priority


def build_company_intelligence(
    candidate: Dict[str, Any],
    *,
    scan_repo,
    since: Optional[datetime] = None,
    is_watchlisted: bool = False,
    watchlist_note: Optional[str] = None,
) -> Dict[str, Any]:
    window_start = since or (datetime.now(timezone.utc) - timedelta(days=7))
    symbol = str(candidate.get("symbol") or "").strip().upper()

    runs = scan_repo.get_completed_runs_since(window_start)
    run_ids = [run["id"] for run in runs if run.get("id")]
    rows = (
        scan_repo.get_results_for_runs(run_ids, symbols=[symbol])
        if symbol and run_ids
        else []
    )

    pre_window_run_ids = scan_repo.get_all_completed_run_ids_before(window_start)
    pre_window_symbols = scan_repo.get_symbols_with_results_before(
        [symbol] if symbol else [],
        window_start,
        run_ids=pre_window_run_ids,
    )
    is_first_seen_in_window = (
        bool(symbol)
        and symbol not in pre_window_symbols
        and bool(rows)
    )

    if rows:
        monitor_entry = build_symbol_monitor_entry(
            symbol,
            rows,
            snapshot_fn=scan_repo.row_to_snapshot,
            candidate=candidate,
            is_watchlisted=is_watchlisted,
            is_first_seen_in_window=is_first_seen_in_window,
        )
    else:
        monitor_entry = _empty_monitor_entry(
            candidate,
            symbol=symbol,
            is_watchlisted=is_watchlisted,
            is_first_seen_in_window=is_first_seen_in_window and symbol not in pre_window_symbols,
        )

    timeline = build_timeline_items(monitor_entry.get("events") or [])
    data_quality = build_data_quality_context(candidate, monitor_entry)

    return {
        "symbol": symbol,
        "since": window_start,
        "priority": monitor_entry.get("research_priority") or {},
        "history_summary": {
            "history_count": monitor_entry.get("history_count") or 0,
            "pair_count": monitor_entry.get("pair_count") or 0,
            "window_change_score": monitor_entry.get("window_change_score") or 0,
            "latest_change_score": monitor_entry.get("latest_change_score") or 0,
            "meaningful_change_count": monitor_entry.get("meaningful_change_count") or 0,
            "latest_scan_at": monitor_entry.get("latest_scan_at"),
            "events": monitor_entry.get("events") or [],
            "recent_change": monitor_entry.get("recent_change"),
        },
        "timeline": timeline,
        "badges": _merge_badges(monitor_entry.get("badges") or [], data_quality.get("badges") or []),
        "data_quality": data_quality,
        "is_first_seen_in_window": monitor_entry.get("is_first_seen_in_window"),
        "has_legacy_history": monitor_entry.get("has_legacy_history"),
        "is_watchlisted": is_watchlisted,
        "watchlist_note": watchlist_note,
        "primary_category": monitor_entry.get("primary_category"),
        "monitor_entry": monitor_entry,
    }


def build_timeline_items(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen_messages: set[str] = set()

    ordered = sorted(
        events,
        key=lambda event: (
            event.get("occurred_at") or "",
            event.get("pair_index") or 0,
        ),
        reverse=True,
    )

    for event in ordered:
        message = event.get("message")
        if not message or message in seen_messages:
            continue
        seen_messages.add(message)
        items.append({
            "occurred_at": event.get("occurred_at"),
            "date_label": format_timeline_date(event.get("occurred_at")),
            "message": message,
            "severity": event.get("severity"),
            "category": event.get("category"),
        })
    return items


def build_data_quality_context(
    candidate: Dict[str, Any],
    monitor_entry: Dict[str, Any],
) -> Dict[str, Any]:
    badges: List[str] = []
    notes: List[str] = []
    freshness = candidate.get("freshness_status")

    if freshness == "STALE":
        badges.append("STALE")
        notes.append("Finansal veri güncel değil — doğrulama gerekir")
    elif freshness == "AGING":
        badges.append("AGING")
        notes.append("Finansal dönem eskiyor — doğrulama gerekebilir")
    elif freshness == "UNKNOWN":
        badges.append("UNKNOWN_FRESHNESS")
        notes.append("Finansal dönem doğrulanamadı")

    availability_events = [
        event
        for event in (monitor_entry.get("events") or [])
        if event.get("category") == "AVAILABILITY"
    ]
    if availability_events:
        badges.append("DATA_AVAILABILITY")
        notes.append(availability_events[0].get("message") or "Veri geçici olarak erişilemedi")

    if monitor_entry.get("has_legacy_history"):
        badges.append("LEGACY_HISTORY")
        notes.append(
            "Eski taramaların sınırlı snapshot verisi nedeniyle bazı geçmiş "
            "değişimler gösterilemeyebilir."
        )

    if monitor_entry.get("is_first_seen_in_window"):
        badges.append("NEW")

    return {
        "freshness_status": freshness,
        "research_confidence": candidate.get("research_confidence"),
        "badges": badges,
        "notes": notes,
    }


def format_timeline_date(value: Optional[str]) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    months = {
        1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz",
        7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara",
    }
    return f"{parsed.day} {months[parsed.month]}"


def _empty_monitor_entry(
    candidate: Dict[str, Any],
    *,
    symbol: str,
    is_watchlisted: bool,
    is_first_seen_in_window: bool,
) -> Dict[str, Any]:
    priority = compute_research_priority(
        candidate,
        recent_change={
            "has_meaningful_change": False,
            "change_score": 0,
            "changes": [],
            "no_previous": True,
        },
        is_user_watchlist=is_watchlisted,
        is_first_seen=is_first_seen_in_window,
    )
    return {
        "symbol": symbol,
        "company_name": candidate.get("company_name") or symbol,
        "candidate": candidate,
        "latest_snapshot": {},
        "latest_scan_at": None,
        "history_count": 0,
        "pair_count": 0,
        "events": [],
        "max_severity": None,
        "latest_change_score": 0,
        "window_change_score": 0,
        "meaningful_change_count": 0,
        "is_first_seen_in_window": is_first_seen_in_window,
        "is_watchlisted": is_watchlisted,
        "research_priority": priority,
        "has_legacy_history": False,
        "recent_change": {
            "has_meaningful_change": False,
            "change_score": 0,
            "changes": [],
            "no_previous": True,
        },
        "primary_category": "NONE",
        "badges": ["NEW"] if is_first_seen_in_window else [],
    }


def _merge_badges(*badge_groups: List[str]) -> List[str]:
    merged: List[str] = []
    seen: set[str] = set()
    for group in badge_groups:
        for badge in group:
            if badge not in seen:
                seen.add(badge)
                merged.append(badge)
    return merged
