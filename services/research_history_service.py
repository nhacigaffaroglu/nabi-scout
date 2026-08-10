from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from services.change_detection_engine import detect_changes
from services.research_priority_engine import compute_research_priority

CATEGORY_ATTENTION = "ATTENTION"
CATEGORY_WATCHLIST = "WATCHLIST"
CATEGORY_NEW = "NEW"
CATEGORY_DATA_ISSUES = "DATA_ISSUES"
CATEGORY_NONE = "NONE"

CATEGORY_RANK = {
    CATEGORY_ATTENTION: 1,
    CATEGORY_WATCHLIST: 2,
    CATEGORY_NEW: 3,
    CATEGORY_DATA_ISSUES: 4,
    CATEGORY_NONE: 5,
}

SEVERITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

RESEARCH_DECISIONS = frozenset({
    "ARAŞTIRMA ADAYI",
    "YÜKSEK ÖNCELİKLİ ARAŞTIRMA ADAYI",
})

COMPLETENESS_NET_THRESHOLD = 8.0


def row_to_snapshot(row: Dict[str, Any], snapshot_fn) -> Dict[str, Any]:
    return snapshot_fn(row)


def sort_timeline_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            row.get("created_at") or "",
            row.get("id") or "",
            row.get("scan_run_id") or "",
        ),
    )


def group_rows_by_symbol(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        grouped.setdefault(symbol, []).append(row)
    for symbol in grouped:
        grouped[symbol] = sort_timeline_rows(grouped[symbol])
    return grouped


def compute_consecutive_pair_changes(
    timeline: List[Dict[str, Any]],
    snapshot_fn,
) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    if len(timeline) < 2:
        return pairs

    for index in range(1, len(timeline)):
        previous_row = timeline[index - 1]
        current_row = timeline[index]
        previous = snapshot_fn(previous_row)
        current = snapshot_fn(current_row)
        change = detect_changes(previous, current)
        pairs.append({
            "pair_index": index,
            "occurred_at": current_row.get("created_at"),
            "previous_row": previous_row,
            "current_row": current_row,
            "previous_snapshot": previous,
            "current_snapshot": current,
            "change": change,
        })
    return pairs


def aggregate_monitor_events(
    pair_results: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int, int, bool]:
    raw_events: List[Dict[str, Any]] = []
    pair_scores: List[int] = []
    has_legacy_history = False

    for pair in pair_results:
        change = pair.get("change") or {}
        score = int(change.get("change_score") or 0)
        if score == 0 and not change.get("changes"):
            continue
        pair_scores.append(score)

        prev_source = (pair.get("previous_snapshot") or {}).get("_comparison_source")
        curr_source = (pair.get("current_snapshot") or {}).get("_comparison_source")
        if prev_source == "legacy_sparse" or curr_source == "legacy_sparse":
            has_legacy_history = True

        for event in change.get("changes") or []:
            raw_events.append({
                **event,
                "occurred_at": pair.get("occurred_at"),
                "pair_index": pair.get("pair_index"),
                "pair_change_score": score,
            })

    deduped = _dedupe_events(raw_events, pair_results=pair_results)
    window_change_score = max(pair_scores) if pair_scores else 0
    latest_change_score = _latest_pair_score(pair_results)
    meaningful_change_count = sum(
        1
        for pair in pair_results
        if (pair.get("change") or {}).get("has_meaningful_change")
    )
    return deduped, window_change_score, latest_change_score, has_legacy_history


def build_symbol_monitor_entry(
    symbol: str,
    timeline: List[Dict[str, Any]],
    *,
    snapshot_fn,
    candidate: Optional[Dict[str, Any]] = None,
    is_watchlisted: bool = False,
    is_first_seen_in_window: bool = False,
) -> Dict[str, Any]:
    pair_results = compute_consecutive_pair_changes(timeline, snapshot_fn)
    events, window_change_score, latest_change_score, has_legacy_history = (
        aggregate_monitor_events(pair_results)
    )

    latest_row = timeline[-1] if timeline else {}
    latest_snapshot = snapshot_fn(latest_row) if latest_row else {}
    company_name = (
        (candidate or {}).get("company_name")
        or latest_snapshot.get("company_name")
        or symbol
    )

    synthetic_change = _synthetic_recent_change(
        events,
        window_change_score,
        meaningful_change_count=sum(
            1
            for pair in pair_results
            if (pair.get("change") or {}).get("has_meaningful_change")
        ),
    )

    priority = compute_research_priority(
        candidate or _candidate_from_snapshot(latest_snapshot, symbol),
        recent_change=synthetic_change,
        is_user_watchlist=is_watchlisted,
        is_first_seen=is_first_seen_in_window,
    )

    entry = {
        "symbol": symbol,
        "company_name": company_name,
        "candidate": candidate,
        "latest_snapshot": latest_snapshot,
        "latest_scan_at": latest_row.get("created_at"),
        "history_count": len(timeline),
        "pair_count": len(pair_results),
        "events": events,
        "max_severity": _max_severity(events),
        "latest_change_score": latest_change_score,
        "window_change_score": window_change_score,
        "meaningful_change_count": synthetic_change["meaningful_change_count"],
        "is_first_seen_in_window": is_first_seen_in_window,
        "is_watchlisted": is_watchlisted,
        "research_priority": priority,
        "has_legacy_history": has_legacy_history,
        "recent_change": synthetic_change,
    }

    primary_category, badges = assign_category_and_badges(entry)
    entry["primary_category"] = primary_category
    entry["badges"] = badges
    return entry


def build_monitor_entries(
    rows: List[Dict[str, Any]],
    *,
    snapshot_fn,
    candidates_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    watched_candidate_ids: Optional[set[str]] = None,
    pre_window_symbols: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    grouped = group_rows_by_symbol(rows)
    candidates_by_symbol = candidates_by_symbol or {}
    watched_candidate_ids = watched_candidate_ids or set()
    pre_window_symbols = pre_window_symbols or set()

    entries: List[Dict[str, Any]] = []
    for symbol, timeline in grouped.items():
        candidate = candidates_by_symbol.get(symbol)
        candidate_id = str(candidate.get("id")) if candidate and candidate.get("id") else None
        is_watchlisted = candidate_id in watched_candidate_ids if candidate_id else False
        is_first_seen = symbol not in pre_window_symbols and bool(timeline)

        entries.append(
            build_symbol_monitor_entry(
                symbol,
                timeline,
                snapshot_fn=snapshot_fn,
                candidate=candidate,
                is_watchlisted=is_watchlisted,
                is_first_seen_in_window=is_first_seen,
            )
        )
    return entries


def assign_category_and_badges(entry: Dict[str, Any]) -> Tuple[str, List[str]]:
    badges: List[str] = []
    events = entry.get("events") or []
    candidate = entry.get("candidate") or {}
    latest_snapshot = entry.get("latest_snapshot") or {}

    if entry.get("is_watchlisted"):
        badges.append("WATCHLIST")
    if entry.get("is_first_seen_in_window"):
        badges.append("NEW")
    if entry.get("has_legacy_history"):
        badges.append("LEGACY_HISTORY")

    has_high = any(event.get("severity") == "HIGH" for event in events)
    has_decision_change = any(
        event.get("field") == "decision_label" for event in events
    )
    has_availability = any(
        event.get("category") == "AVAILABILITY" for event in events
    )
    has_confidence_downgrade = any(
        event.get("field") in {"research_confidence", "score_confidence"}
        and _is_downgrade_event(event)
        for event in events
    )
    has_completeness_deterioration = any(
        event.get("field") == "data_completeness"
        and _is_deterioration_event(event)
        for event in events
    )

    freshness = candidate.get("freshness_status") or latest_snapshot.get("freshness_status")
    has_data_issue = (
        freshness in {"STALE", "UNKNOWN"}
        or has_availability
        or has_confidence_downgrade
        or has_completeness_deterioration
    )
    if has_data_issue:
        badges.append("DATA_ISSUE")

    window_change_score = int(entry.get("window_change_score") or 0)
    meaningful_change_count = int(entry.get("meaningful_change_count") or 0)
    has_new_research_transition = _has_new_research_transition(events)

    if has_high or has_decision_change or window_change_score >= 15:
        return CATEGORY_ATTENTION, _unique_badges(badges)

    if entry.get("is_watchlisted") and meaningful_change_count > 0:
        return CATEGORY_WATCHLIST, _unique_badges(badges)

    if entry.get("is_first_seen_in_window") or has_new_research_transition:
        return CATEGORY_NEW, _unique_badges(badges)

    if has_data_issue:
        return CATEGORY_DATA_ISSUES, _unique_badges(badges)

    return CATEGORY_NONE, _unique_badges(badges)


def group_entries_by_category(
    entries: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    grouped = {
        CATEGORY_ATTENTION: [],
        CATEGORY_WATCHLIST: [],
        CATEGORY_NEW: [],
        CATEGORY_DATA_ISSUES: [],
        CATEGORY_NONE: [],
    }
    for entry in entries:
        category = entry.get("primary_category") or CATEGORY_NONE
        if category == CATEGORY_NONE:
            continue
        grouped.setdefault(category, []).append(entry)

    for category in grouped:
        grouped[category] = sort_monitor_entries(grouped[category])
    return grouped


def sort_monitor_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(entry: Dict[str, Any]) -> tuple:
        priority = entry.get("research_priority") or {}
        events = entry.get("events") or []
        high_count = sum(1 for event in events if event.get("severity") == "HIGH")
        max_severity = SEVERITY_RANK.get(entry.get("max_severity") or "", 0)
        return (
            CATEGORY_RANK.get(entry.get("primary_category") or CATEGORY_NONE, 99),
            -float(priority.get("priority_score") or 0),
            -high_count,
            -max_severity,
            -int(entry.get("window_change_score") or 0),
            str(entry.get("latest_scan_at") or ""),
            str(entry.get("symbol") or ""),
        )

    return sorted(entries, key=sort_key, reverse=False)


def top_priority_entries(
    entries: List[Dict[str, Any]],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    visible = [
        entry for entry in entries
        if entry.get("primary_category") != CATEGORY_NONE
    ]
    return sort_monitor_entries(visible)[:limit]


def _dedupe_events(
    events: List[Dict[str, Any]],
    *,
    pair_results: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if not events:
        return []

    decision_high = [
        event for event in events
        if event.get("field") == "decision_label" and event.get("severity") == "HIGH"
    ]
    kept: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()

    for event in decision_high:
        key = _semantic_key(event)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        kept.append(event)

    availability_events = [
        event for event in events if event.get("category") == "AVAILABILITY"
    ]
    if availability_events:
        kept.append(_collapse_availability_events(availability_events))
        for event in availability_events:
            seen_keys.add(_semantic_key(event))

    freshness_events = [
        event for event in events if event.get("field") == "freshness_status"
    ]
    net_freshness = _net_freshness_event(
        freshness_events,
        pair_results=pair_results,
    )
    if net_freshness:
        kept.append(net_freshness)
    for event in freshness_events:
        seen_keys.add(_semantic_key(event))

    completeness_events = [
        event for event in events if event.get("field") == "data_completeness"
    ]
    net_completeness = _net_completeness_event(
        completeness_events,
        pair_results=pair_results,
    )
    if net_completeness:
        kept.append(net_completeness)
    for event in completeness_events:
        seen_keys.add(_semantic_key(event))

    for event in events:
        key = _semantic_key(event)
        if key in seen_keys:
            continue
        if event.get("severity") == "HIGH":
            kept.append(event)
            seen_keys.add(key)
            continue
        if key not in seen_keys:
            kept.append(event)
            seen_keys.add(key)

    kept = _collapse_repeated_medium_low(kept)
    kept.sort(
        key=lambda event: (
            event.get("occurred_at") or "",
            event.get("pair_index") or 0,
        ),
        reverse=True,
    )
    return kept


def _collapse_repeated_medium_low(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest_by_key: Dict[str, Dict[str, Any]] = {}
    ordered_keys: List[str] = []

    for event in events:
        if event.get("severity") == "HIGH":
            continue
        key = _semantic_key(event)
        if key not in latest_by_key:
            ordered_keys.append(key)
        latest_by_key[key] = event

    high_events = [event for event in events if event.get("severity") == "HIGH"]
    collapsed = high_events + [latest_by_key[key] for key in ordered_keys if key in latest_by_key]
    collapsed.sort(
        key=lambda event: (
            event.get("occurred_at") or "",
            event.get("pair_index") or 0,
        ),
        reverse=True,
    )
    return collapsed


def _collapse_availability_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    latest = max(
        events,
        key=lambda event: (
            event.get("occurred_at") or "",
            event.get("pair_index") or 0,
        ),
    )
    message = latest.get("message") or "Veri erişilebilirliği değişti"
    if "erişilemedi" in message.lower() or "mevcut değil" in message.lower():
        severity = "MEDIUM"
    else:
        severity = latest.get("severity") or "MEDIUM"
    return {
        **latest,
        "severity": severity,
        "category": "AVAILABILITY",
        "message": message,
    }


def _net_freshness_event(
    events: List[Dict[str, Any]],
    *,
    pair_results: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    if pair_results:
        first_status = (pair_results[0].get("previous_snapshot") or {}).get("freshness_status")
        last_status = (pair_results[-1].get("current_snapshot") or {}).get("freshness_status")
        if first_status and last_status:
            if first_status == last_status:
                return None
            if last_status == "STALE":
                latest = events[-1] if events else {}
                return {
                    **latest,
                    "field": "freshness_status",
                    "category": "FRESHNESS",
                    "old": first_status,
                    "new": last_status,
                    "severity": "HIGH",
                    "message": f"Freshness {first_status} → {last_status}",
                }
            return {
                "field": "freshness_status",
                "category": "FRESHNESS",
                "old": first_status,
                "new": last_status,
                "severity": "MEDIUM",
                "message": f"Freshness {first_status} → {last_status}",
                "occurred_at": (pair_results[-1].get("occurred_at")),
                "pair_index": pair_results[-1].get("pair_index"),
            }

    if not events:
        return None
    ordered = sorted(
        events,
        key=lambda event: (
            event.get("occurred_at") or "",
            event.get("pair_index") or 0,
        ),
    )
    first_old = ordered[0].get("old")
    last_new = ordered[-1].get("new")
    if first_old == last_new:
        return None
    if last_new == "STALE":
        latest = ordered[-1]
        return {**latest, "severity": "HIGH"}
    return ordered[-1]


def _net_completeness_event(
    events: List[Dict[str, Any]],
    *,
    pair_results: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    if pair_results:
        first_val = _as_float(
            (pair_results[0].get("previous_snapshot") or {}).get("data_completeness")
        )
        last_val = _as_float(
            (pair_results[-1].get("current_snapshot") or {}).get("data_completeness")
        )
        if first_val is not None and last_val is not None:
            if abs(last_val - first_val) < COMPLETENESS_NET_THRESHOLD:
                return None
            delta = round(last_val - first_val, 1)
            latest = events[-1] if events else {}
            return {
                **latest,
                "field": "data_completeness",
                "category": "COMPLETENESS",
                "old": first_val,
                "new": last_val,
                "delta": delta,
                "severity": latest.get("severity") or "MEDIUM",
                "message": f"Veri tamlığı %{first_val:.0f} → %{last_val:.0f}",
                "occurred_at": pair_results[-1].get("occurred_at"),
                "pair_index": pair_results[-1].get("pair_index"),
            }

    if not events:
        return None
    ordered = sorted(
        events,
        key=lambda event: (
            event.get("occurred_at") or "",
            event.get("pair_index") or 0,
        ),
    )
    first_old = _as_float(ordered[0].get("old"))
    last_new = _as_float(ordered[-1].get("new"))
    if first_old is None or last_new is None:
        return ordered[-1]
    if abs(last_new - first_old) < COMPLETENESS_NET_THRESHOLD:
        return None
    delta = round(last_new - first_old, 1)
    latest = ordered[-1]
    return {
        **latest,
        "old": first_old,
        "new": last_new,
        "delta": delta,
        "message": f"Veri tamlığı %{first_old:.0f} → %{last_new:.0f}",
    }


def _synthetic_recent_change(
    events: List[Dict[str, Any]],
    window_change_score: int,
    *,
    meaningful_change_count: int,
) -> Dict[str, Any]:
    stripped = [
        {
            key: value
            for key, value in event.items()
            if key not in {"occurred_at", "pair_index", "pair_change_score"}
        }
        for event in events
    ]
    has_high = any(event.get("severity") == "HIGH" for event in stripped)
    has_meaningful_change = meaningful_change_count > 0 or has_high
    return {
        "has_meaningful_change": has_meaningful_change,
        "change_score": window_change_score,
        "changes": stripped,
        "no_previous": False,
        "meaningful_change_count": meaningful_change_count,
    }


def _candidate_from_snapshot(snapshot: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "company_name": snapshot.get("company_name") or symbol,
        "decision_label": snapshot.get("decision_label"),
        "nabi_score": snapshot.get("nabi_score"),
        "opportunity_score": snapshot.get("opportunity_score"),
        "conviction_score": snapshot.get("conviction_score"),
        "research_confidence": snapshot.get("research_confidence"),
        "freshness_status": snapshot.get("freshness_status"),
        "data_completeness": snapshot.get("data_completeness"),
    }


def _semantic_key(event: Dict[str, Any]) -> str:
    dedupe_key = event.get("dedupe_key")
    if dedupe_key:
        return str(dedupe_key)
    field = event.get("field") or "unknown"
    category = event.get("category") or "unknown"
    return f"{category}:{field}"


def _max_severity(events: List[Dict[str, Any]]) -> Optional[str]:
    best = None
    best_rank = 0
    for event in events:
        rank = SEVERITY_RANK.get(event.get("severity") or "", 0)
        if rank > best_rank:
            best_rank = rank
            best = event.get("severity")
    return best


def _latest_pair_score(pair_results: List[Dict[str, Any]]) -> int:
    if not pair_results:
        return 0
    latest = pair_results[-1].get("change") or {}
    return int(latest.get("change_score") or 0)


def _has_new_research_transition(events: List[Dict[str, Any]]) -> bool:
    for event in events:
        if event.get("field") != "decision_label":
            continue
        new_decision = event.get("new")
        old_decision = event.get("old")
        if new_decision in RESEARCH_DECISIONS and old_decision not in RESEARCH_DECISIONS:
            return True
    return False


def _is_downgrade_event(event: Dict[str, Any]) -> bool:
    message = str(event.get("message") or "").lower()
    return "→" in message or "düş" in message


def _is_deterioration_event(event: Dict[str, Any]) -> bool:
    old = _as_float(event.get("old"))
    new = _as_float(event.get("new"))
    if old is None or new is None:
        return False
    return new < old


def _unique_badges(badges: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for badge in badges:
        if badge not in seen:
            seen.add(badge)
            ordered.append(badge)
    return ordered


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
