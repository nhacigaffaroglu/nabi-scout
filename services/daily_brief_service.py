from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.research_monitor_service import build_monitor_feed
from services.research_workflow_service import build_research_workflow
from services.ui_formatters import (
    format_data_issue_summary,
    format_priority_reasons,
    format_scheduled_run_detail,
    format_scheduled_run_status,
    resolve_scheduled_run_status,
)

WORKFLOW_STATUS_ORDER = {
    "INCELEMEDE": 0,
    "TEKRAR_BAK": 1,
    "BEKLEMEDE": 2,
    "YENI": 3,
}

_EXCLUDED_DECISIONS = frozenset({"ELE", "ELENDİ"})
_EXCLUDED_ISSUER_CATEGORIES = frozenset({"FUND", "SPECIAL_SECURITY"})


def build_daily_brief(
    *,
    scan_repo,
    candidate_repo,
    watchlist_repo,
    as_of: Optional[datetime] = None,
    window_hours: int = 24,
    max_attention: int = 5,
    max_new: int = 3,
    max_watchlist: int = 3,
    max_open_research: int = 5,
    max_data_issues: int = 3,
) -> Dict[str, Any]:
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    window_start = now - timedelta(hours=window_hours)
    candidates = candidate_repo.get_all(order_by="nabi_score", descending=True)
    watched_ids = watchlist_repo.watched_candidate_ids()

    feed = build_monitor_feed(
        scan_repo=scan_repo,
        candidates=candidates,
        watched_candidate_ids=watched_ids,
        since=window_start,
    )

    raw_scheduled = scan_repo.get_latest_scheduled_run(now.date())
    scheduled_run = _build_scheduled_run(raw_scheduled)

    attention_items = _collect_brief_items(
        feed["categories"].get("ATTENTION") or [],
        max_attention,
    )
    attention_symbols = {
        str(item.get("symbol") or "").strip().upper()
        for item in attention_items
        if item.get("symbol")
    }

    new_candidates = _collect_brief_items(
        [
            entry
            for entry in (feed["categories"].get("NEW") or [])
            if str(entry.get("symbol") or "").strip().upper() not in attention_symbols
        ],
        max_new,
    )

    watchlist_changes = _collect_brief_items(
        [
            entry
            for entry in (feed["categories"].get("WATCHLIST") or [])
            if str(entry.get("symbol") or "").strip().upper() not in attention_symbols
        ],
        max_watchlist,
    )

    data_issues = [
        _monitor_entry_to_data_issue(entry)
        for entry in _eligible_monitor_entries(
            feed["categories"].get("DATA_ISSUES") or [],
        )[:max_data_issues]
    ]

    open_research = _build_open_research_items(candidates, max_open_research)

    meaningful_change_count = _count_meaningful_changes(feed)
    summary_stats = {
        "meaningful_change_count": meaningful_change_count,
        "attention_count": len(attention_items),
        "new_candidate_count": len(new_candidates),
        "watchlist_change_count": len(watchlist_changes),
        "open_research_count": len(open_research),
        "data_issue_count": len(data_issues),
    }

    headline = _build_headline(summary_stats)
    has_anything_to_report = (
        summary_stats["attention_count"] > 0
        or summary_stats["new_candidate_count"] > 0
        or summary_stats["watchlist_change_count"] > 0
        or summary_stats["open_research_count"] > 0
        or summary_stats["data_issue_count"] > 0
        or scheduled_run.get("status") not in {None, "missing"}
    )

    return {
        "generated_at": now,
        "window_start": window_start,
        "headline": headline,
        "scheduled_run": scheduled_run,
        "attention_items": attention_items,
        "new_candidates": new_candidates,
        "watchlist_changes": watchlist_changes,
        "open_research": open_research,
        "data_issues": data_issues,
        "summary_stats": summary_stats,
        "has_anything_to_report": has_anything_to_report,
    }


def _build_scheduled_run(run: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    status = resolve_scheduled_run_status(run)
    if not run:
        return {
            "status": status,
            "status_label": format_scheduled_run_status(status),
            "detail": format_scheduled_run_detail(status, None),
            "universe_name": None,
            "started_at": None,
            "completed_at": None,
            "scanned_symbols": None,
            "error_count": None,
        }

    return {
        "status": status,
        "status_label": format_scheduled_run_status(status),
        "detail": format_scheduled_run_detail(status, run),
        "universe_name": run.get("universe_name"),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "scanned_symbols": run.get("scanned_symbols"),
        "error_count": run.get("error_count"),
    }


def _is_brief_eligible_monitor_entry(entry: Dict[str, Any]) -> bool:
    candidate = entry.get("candidate") or {}
    latest_snapshot = entry.get("latest_snapshot") or {}

    if candidate.get("excluded") or latest_snapshot.get("excluded"):
        return False

    for source in (candidate, latest_snapshot):
        for key in ("decision", "decision_label", "investment_profile", "status"):
            value = str(source.get(key) or "").strip().upper()
            if value in _EXCLUDED_DECISIONS:
                return False

    issuer_category = str(
        latest_snapshot.get("issuer_category")
        or candidate.get("issuer_category")
        or ""
    ).strip().upper()
    if issuer_category in _EXCLUDED_ISSUER_CATEGORIES:
        return False

    return True


def _eligible_monitor_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        entry
        for entry in entries
        if _is_brief_eligible_monitor_entry(entry)
    ]


def _collect_brief_items(
    entries: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for entry in _eligible_monitor_entries(entries):
        items.append(_monitor_entry_to_brief_item(entry))
        if len(items) >= limit:
            break
    return items


def _monitor_entry_to_brief_item(entry: Dict[str, Any]) -> Dict[str, Any]:
    priority = entry.get("research_priority") or {}
    candidate = entry.get("candidate") or {}
    latest_snapshot = entry.get("latest_snapshot") or {}
    decision = (
        candidate.get("decision_label")
        or candidate.get("decision")
        or latest_snapshot.get("decision_label")
        or "—"
    )

    reasons: List[str] = []
    for event in entry.get("events") or []:
        message = event.get("message")
        if message and message not in reasons:
            reasons.append(message)
    for reason in format_priority_reasons(priority.get("reasons") or []):
        if reason not in reasons:
            reasons.append(reason)

    return {
        "symbol": entry.get("symbol"),
        "company_name": entry.get("company_name"),
        "priority_score": priority.get("priority_score"),
        "priority_label": priority.get("priority_label"),
        "decision_label": decision,
        "reasons": reasons[:3],
        "candidate": candidate,
        "events": entry.get("events") or [],
        "primary_category": entry.get("primary_category"),
        "is_first_seen_in_window": entry.get("is_first_seen_in_window"),
    }


def _monitor_entry_to_data_issue(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": entry.get("symbol"),
        "company_name": entry.get("company_name"),
        "summary": format_data_issue_summary(entry),
        "candidate": entry.get("candidate") or {},
        "events": entry.get("events") or [],
    }


def _build_open_research_items(
    candidates: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    open_items: List[Dict[str, Any]] = []
    for candidate in candidates:
        workflow = build_research_workflow(candidate)
        if not workflow.get("is_open"):
            continue
        open_items.append({
            "symbol": candidate.get("symbol"),
            "company_name": candidate.get("company_name"),
            "workflow_status": workflow["research_status"],
            "workflow_status_label": workflow["research_status_label"],
            "research_next_action": workflow.get("research_next_action"),
            "last_reviewed_at": workflow.get("last_reviewed_at"),
            "candidate": candidate,
        })

    open_items.sort(
        key=lambda item: (
            WORKFLOW_STATUS_ORDER.get(item.get("workflow_status") or "YENI", 99),
            str(item.get("symbol") or ""),
        )
    )
    return open_items[:limit]


def _count_meaningful_changes(feed: Dict[str, Any]) -> int:
    symbols: set[str] = set()
    for category in ("ATTENTION", "WATCHLIST"):
        for entry in _eligible_monitor_entries(feed["categories"].get(category) or []):
            if int(entry.get("meaningful_change_count") or 0) <= 0:
                continue
            symbol = str(entry.get("symbol") or "").strip().upper()
            if symbol:
                symbols.add(symbol)
    return len(symbols)


def _build_headline(summary_stats: Dict[str, int]) -> str:
    parts: List[str] = []
    meaningful = int(summary_stats.get("meaningful_change_count") or 0)
    open_count = int(summary_stats.get("open_research_count") or 0)
    watchlist_count = int(summary_stats.get("watchlist_change_count") or 0)

    if meaningful == 0:
        parts.append("Son 24 saatte anlamlı bir değişiklik bulunmadı.")
    elif meaningful == 1:
        parts.append("Son 24 saatte 1 şirkette anlamlı değişiklik bulundu.")
    else:
        parts.append(
            f"Son 24 saatte {meaningful} şirkette anlamlı değişiklik bulundu."
        )

    if open_count == 1:
        parts.append("1 açık araştırma işi bulunuyor.")
    elif open_count > 1:
        parts.append(f"{open_count} açık araştırma işi bulunuyor.")

    if watchlist_count == 1:
        parts.append("İzleme listende 1 önemli değişiklik var.")
    elif watchlist_count > 1:
        parts.append(f"İzleme listende {watchlist_count} önemli değişiklik var.")

    return " ".join(parts)
