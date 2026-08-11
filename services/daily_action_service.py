from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set

from services.research_history_service import (
    CATEGORY_ATTENTION,
    CATEGORY_NEW,
    CATEGORY_WATCHLIST,
    RESEARCH_DECISIONS,
)
from services.research_priority_engine import compute_research_priority
from services.signal_classification_service import (
    SIGNAL_FAMILY_RESEARCH,
    SignalSummary,
    classify_event,
    classify_monitor_entry,
    data_quality_signal_caveat,
)
from services.research_workflow_service import (
    build_research_workflow,
    normalize_research_status,
)
from services.ui_formatters import format_research_status

ACTION_TIER_T1 = "T1"
ACTION_TIER_T2 = "T2"
ACTION_TIER_T3 = "T3"
ACTION_TIER_T4 = "T4"
ACTION_TIER_T5 = "T5"

TODAY_ACTION_TIERS = frozenset({ACTION_TIER_T1, ACTION_TIER_T2, ACTION_TIER_T3})

DATA_QUALITY_ACTIONABLE = "ACTIONABLE"
DATA_QUALITY_CAUTION = "CAUTION"
DATA_QUALITY_WAIT = "WAIT"

WORKFLOW_RANK = {
    "INCELEMEDE": 0,
    "TEKRAR_BAK": 1,
    "BEKLEMEDE": 2,
    "YENI": 3,
    "TAMAMLANDI": 4,
}

LOWER_RESEARCH_DECISIONS = frozenset({
    "İZLE",
    "İKİNCİL İNCELEME",
})

_EXCLUDED_DECISIONS = frozenset({"ELE", "ELENDİ"})
_EXCLUDED_ISSUER_CATEGORIES = frozenset({"FUND", "SPECIAL_SECURITY"})

ACTION_LABELS = {
    ACTION_TIER_T1: "Bugün devam et",
    ACTION_TIER_T2: "Bugün incele",
    ACTION_TIER_T3: "Bugün gözden geçir",
    ACTION_TIER_T4: "Yeni adayı gözden geçir",
    ACTION_TIER_T5: "Açık araştırma backlog",
}

DATA_QUALITY_CAVEATS = {
    DATA_QUALITY_CAUTION: "Veri güncelliği kontrol edilmeli.",
    DATA_QUALITY_WAIT: "Değerlendirme için yeterli veri bekleniyor.",
}


@dataclass(frozen=True)
class DailyActionItem:
    symbol: str
    company_name: str
    action_tier: str
    action_label: str
    reasons: List[str]
    workflow_status: str
    workflow_status_label: str
    next_action: Optional[str]
    last_reviewed_at: Optional[str]
    is_watchlisted: bool
    meaningful_change_count: int
    window_change_score: int
    research_priority_score: float
    research_priority_label: str
    is_first_seen: bool
    data_quality_band: str
    data_quality_caveat: Optional[str]
    latest_scan_at: Optional[str]
    company_report_target: Dict[str, Any] = field(default_factory=dict)
    candidate: Dict[str, Any] = field(default_factory=dict)
    is_availability_only: bool = False
    is_research_actionable: bool = False
    signal_summary: SignalSummary = field(default_factory=SignalSummary)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["signal_summary"] = self.signal_summary.to_dict()
        return payload


def build_today_actions(
    *,
    feed: Dict[str, Any],
    candidates: Optional[Sequence[Dict[str, Any]]] = None,
    watched_candidate_ids: Optional[Set[str]] = None,
    max_actions: int = 3,
) -> List[DailyActionItem]:
    watched = watched_candidate_ids or set()
    candidates_by_symbol = _index_candidates(candidates)
    monitor_by_symbol = _index_monitor_entries(feed)

    items: List[DailyActionItem] = []
    seen_symbols: Set[str] = set()

    for symbol, entry in monitor_by_symbol.items():
        if not _is_action_eligible_monitor_entry(entry):
            continue
        item = _build_action_from_monitor_entry(
            entry,
            watched_candidate_ids=watched,
        )
        if item is None:
            continue
        items.append(item)
        seen_symbols.add(symbol)

    for symbol, candidate in candidates_by_symbol.items():
        if symbol in seen_symbols:
            continue
        workflow = build_research_workflow(candidate)
        if not workflow.get("is_open"):
            continue
        item = _build_action_from_candidate_only(
            candidate,
            watched_candidate_ids=watched,
        )
        if item is not None:
            items.append(item)
            seen_symbols.add(symbol)

    ranked = sorted(items, key=_action_sort_key)
    return select_top_actions(ranked, max_actions=max_actions)


def select_top_actions(
    items: Sequence[DailyActionItem],
    *,
    max_actions: int = 3,
) -> List[DailyActionItem]:
    eligible_today = [
        item
        for item in items
        if item.action_tier in TODAY_ACTION_TIERS
        and item.is_research_actionable
        and item.data_quality_band != DATA_QUALITY_WAIT
        and not _is_reviewed_without_new_change(item)
    ]

    selected: List[DailyActionItem] = []
    for item in eligible_today:
        if len(selected) >= max_actions:
            break
        selected.append(item)

    return selected


def classify_data_quality_band(
    candidate: Dict[str, Any],
    *,
    monitor_entry: Optional[Dict[str, Any]] = None,
    meaningful_change_count: int = 0,
    availability_only: bool = False,
) -> tuple[str, Optional[str]]:
    completeness = _as_float(
        candidate.get("data_completeness")
        or (monitor_entry or {}).get("latest_snapshot", {}).get("data_completeness")
    )
    freshness = (
        candidate.get("freshness_status")
        or (monitor_entry or {}).get("latest_snapshot", {}).get("freshness_status")
    )
    freshness_key = str(freshness or "").strip().upper()

    if completeness is not None and completeness < 40:
        return DATA_QUALITY_WAIT, DATA_QUALITY_CAVEATS[DATA_QUALITY_WAIT]

    if completeness is not None and completeness < 65:
        caveat = DATA_QUALITY_CAVEATS[DATA_QUALITY_CAUTION]
        if freshness_key in {"AGING", "UNKNOWN"}:
            return DATA_QUALITY_CAUTION, caveat
        return DATA_QUALITY_CAUTION, caveat

    if meaningful_change_count > 0 and not availability_only:
        return DATA_QUALITY_ACTIONABLE, None

    if completeness is not None and completeness >= 65:
        caveat = None
        if freshness_key in {"AGING", "UNKNOWN"}:
            caveat = DATA_QUALITY_CAVEATS[DATA_QUALITY_CAUTION]
            return DATA_QUALITY_CAUTION, caveat
        return DATA_QUALITY_ACTIONABLE, caveat

    if freshness_key in {"AGING", "UNKNOWN"}:
        return DATA_QUALITY_CAUTION, DATA_QUALITY_CAVEATS[DATA_QUALITY_CAUTION]

    if completeness is None:
        return DATA_QUALITY_CAUTION, DATA_QUALITY_CAVEATS[DATA_QUALITY_CAUTION]

    return DATA_QUALITY_ACTIONABLE, None


def is_availability_only_change(entry: Optional[Dict[str, Any]]) -> bool:
    if not entry:
        return False

    events = entry.get("events") or []
    if not events:
        recent = entry.get("recent_change") or {}
        changes = recent.get("changes") or []
        if not changes:
            return False
        events = changes

    meaningful_events = [
        event
        for event in events
        if event.get("severity") in {"HIGH", "MEDIUM", "LOW"}
        or event.get("field")
        or event.get("category")
    ]
    if not meaningful_events:
        return False

    if all(event.get("category") == "AVAILABILITY" for event in meaningful_events):
        return True

    if all(event.get("field") == "data_completeness" for event in meaningful_events):
        return True

    return False


def is_research_relevant_decision(decision_label: Optional[str]) -> bool:
    label = str(decision_label or "").strip().upper()
    return label in RESEARCH_DECISIONS


def assign_action_tier(
    *,
    meaningful_change_count: int,
    workflow_status: str,
    is_watchlisted: bool,
    next_action: Optional[str],
    data_quality_band: str,
    availability_only: bool,
    decision_label: Optional[str],
    is_first_seen: bool,
    is_open_workflow: bool,
) -> str:
    status = normalize_research_status(workflow_status)
    has_meaningful = meaningful_change_count > 0

    if data_quality_band == DATA_QUALITY_WAIT:
        return ACTION_TIER_T5

    if has_meaningful:
        if (
            status in {"INCELEMEDE", "TEKRAR_BAK"}
            and (is_watchlisted or _clean_text(next_action))
            and not availability_only
        ):
            return ACTION_TIER_T1

        if not availability_only and is_research_relevant_decision(decision_label):
            return ACTION_TIER_T2

        return ACTION_TIER_T3

    if is_first_seen and is_research_relevant_decision(decision_label):
        return ACTION_TIER_T4

    if is_open_workflow and status != "TAMAMLANDI":
        return ACTION_TIER_T5

    if is_first_seen:
        return ACTION_TIER_T4

    return ACTION_TIER_T5


def build_action_label(
    action_tier: str,
    *,
    workflow_status: str,
) -> str:
    status = normalize_research_status(workflow_status)
    if action_tier == ACTION_TIER_T3 and status == "TAMAMLANDI":
        return "Yeniden değerlendir"
    return ACTION_LABELS.get(action_tier, ACTION_LABELS[ACTION_TIER_T5])


def build_action_reasons(
    *,
    action_tier: str,
    monitor_entry: Optional[Dict[str, Any]],
    candidate: Dict[str, Any],
    workflow_status: str,
    is_watchlisted: bool,
    next_action: Optional[str],
    availability_only: bool,
    data_quality_caveat: Optional[str],
    signal_summary: Optional[SignalSummary] = None,
) -> List[str]:
    reasons: List[str] = []
    seen: Set[str] = set()

    def add(reason: Optional[str]) -> None:
        text = _clean_text(reason)
        if text and text not in seen:
            seen.add(text)
            reasons.append(text)

    meaningful = int((monitor_entry or {}).get("meaningful_change_count") or 0)
    summary = signal_summary or classify_monitor_entry(monitor_entry)
    if meaningful > 0:
        if summary.is_research_actionable:
            for event in (monitor_entry or {}).get("events") or []:
                if classify_event(event) != SIGNAL_FAMILY_RESEARCH:
                    continue
                add(event.get("message"))
                if len(reasons) >= 2:
                    break
            if not reasons:
                add("Son taramada araştırma açısından anlamlı değişiklik var.")
        elif availability_only or summary.is_data_quality_only:
            add("Veri tamlığı değişti; şirket yeniden gözden geçirilmeli.")
        else:
            for event in (monitor_entry or {}).get("events") or []:
                add(event.get("message"))
                if len(reasons) >= 2:
                    break
            if not reasons:
                add("Son taramada anlamlı değişiklik var.")

    status = normalize_research_status(workflow_status)
    if status == "INCELEMEDE":
        add("Araştırma süreci devam ediyor.")
    elif status == "TEKRAR_BAK":
        add("Tekrar bakılması gereken açık iş var.")
    elif status == "TAMAMLANDI" and meaningful > 0:
        add("Tamamlanmış araştırmada yeni değişiklik var.")

    if _clean_text(next_action):
        add(f"Sıradaki aksiyon: {next_action}")
    elif is_watchlisted:
        add("İzleme listende.")

    if action_tier == ACTION_TIER_T4 and (monitor_entry or {}).get("is_first_seen_in_window"):
        add("Bu zaman aralığında ilk kez göründü.")

    priority = (monitor_entry or {}).get("research_priority") or {}
    for reason in priority.get("reasons") or []:
        if len(reasons) >= 2:
            break
        if availability_only and "Fırsat potansiyeli" in str(reason):
            continue
        add(reason)

    if not reasons and data_quality_caveat:
        add(data_quality_caveat)

    if not reasons:
        decision = candidate.get("decision_label") or candidate.get("decision")
        if decision:
            add(str(decision))

    return reasons[:2]


def open_research_backlog_caveat(candidate: Dict[str, Any]) -> Optional[str]:
    completeness = _as_float(candidate.get("data_completeness"))
    if completeness is not None and completeness < 40:
        return "Veri bekle — değerlendirme için yeterli veri yok."
    return None


def _build_action_from_monitor_entry(
    entry: Dict[str, Any],
    *,
    watched_candidate_ids: Set[str],
) -> Optional[DailyActionItem]:
    candidate = dict(entry.get("candidate") or {})
    symbol = str(entry.get("symbol") or candidate.get("symbol") or "").strip().upper()
    if not symbol:
        return None

    candidate.setdefault("symbol", symbol)
    workflow = build_research_workflow(candidate)
    workflow_status = workflow["research_status"]
    if workflow_status == "TAMAMLANDI" and int(entry.get("meaningful_change_count") or 0) <= 0:
        return None

    candidate_id = candidate.get("id")
    is_watchlisted = (
        str(candidate_id) in watched_candidate_ids if candidate_id else False
    ) or bool(entry.get("is_watchlisted"))

    availability_only = is_availability_only_change(entry)
    signal_summary = classify_monitor_entry(entry)
    meaningful_change_count = int(entry.get("meaningful_change_count") or 0)
    data_quality_band, data_quality_caveat = classify_data_quality_band(
        candidate,
        monitor_entry=entry,
        meaningful_change_count=meaningful_change_count,
        availability_only=availability_only,
    )

    decision_label = (
        candidate.get("decision_label")
        or candidate.get("decision")
        or (entry.get("latest_snapshot") or {}).get("decision_label")
    )

    action_tier = assign_action_tier(
        meaningful_change_count=meaningful_change_count,
        workflow_status=workflow_status,
        is_watchlisted=is_watchlisted,
        next_action=workflow.get("research_next_action"),
        data_quality_band=data_quality_band,
        availability_only=availability_only,
        decision_label=decision_label,
        is_first_seen=bool(entry.get("is_first_seen_in_window")),
        is_open_workflow=workflow.get("is_open", False),
    )

    priority = entry.get("research_priority") or compute_research_priority(
        candidate,
        recent_change=entry.get("recent_change"),
        is_user_watchlist=is_watchlisted,
        is_first_seen=bool(entry.get("is_first_seen_in_window")),
    )

    action_label = build_action_label(
        action_tier,
        workflow_status=workflow_status,
    )
    mixed_quality_caveat = data_quality_signal_caveat(signal_summary)
    if mixed_quality_caveat and data_quality_caveat is None:
        data_quality_caveat = mixed_quality_caveat

    reasons = build_action_reasons(
        action_tier=action_tier,
        monitor_entry=entry,
        candidate=candidate,
        workflow_status=workflow_status,
        is_watchlisted=is_watchlisted,
        next_action=workflow.get("research_next_action"),
        availability_only=availability_only,
        data_quality_caveat=data_quality_caveat,
        signal_summary=signal_summary,
    )

    return DailyActionItem(
        symbol=symbol,
        company_name=str(entry.get("company_name") or candidate.get("company_name") or symbol),
        action_tier=action_tier,
        action_label=action_label,
        reasons=reasons,
        workflow_status=workflow_status,
        workflow_status_label=workflow["research_status_label"],
        next_action=workflow.get("research_next_action"),
        last_reviewed_at=workflow.get("last_reviewed_at"),
        is_watchlisted=is_watchlisted,
        meaningful_change_count=meaningful_change_count,
        window_change_score=int(entry.get("window_change_score") or 0),
        research_priority_score=float(priority.get("priority_score") or 0),
        research_priority_label=str(priority.get("priority_label") or "—"),
        is_first_seen=bool(entry.get("is_first_seen_in_window")),
        data_quality_band=data_quality_band,
        data_quality_caveat=data_quality_caveat,
        latest_scan_at=entry.get("latest_scan_at"),
        company_report_target=candidate,
        candidate=candidate,
        is_availability_only=availability_only,
        is_research_actionable=signal_summary.is_research_actionable,
        signal_summary=signal_summary,
    )


def _build_action_from_candidate_only(
    candidate: Dict[str, Any],
    *,
    watched_candidate_ids: Set[str],
) -> Optional[DailyActionItem]:
    symbol = str(candidate.get("symbol") or "").strip().upper()
    if not symbol:
        return None

    workflow = build_research_workflow(candidate)
    if not workflow.get("is_open"):
        return None

    candidate_id = candidate.get("id")
    is_watchlisted = str(candidate_id) in watched_candidate_ids if candidate_id else False
    data_quality_band, data_quality_caveat = classify_data_quality_band(
        candidate,
        meaningful_change_count=0,
        availability_only=False,
    )

    action_tier = assign_action_tier(
        meaningful_change_count=0,
        workflow_status=workflow["research_status"],
        is_watchlisted=is_watchlisted,
        next_action=workflow.get("research_next_action"),
        data_quality_band=data_quality_band,
        availability_only=False,
        decision_label=candidate.get("decision_label") or candidate.get("decision"),
        is_first_seen=False,
        is_open_workflow=True,
    )

    priority = compute_research_priority(
        candidate,
        recent_change={
            "has_meaningful_change": False,
            "change_score": 0,
            "changes": [],
        },
        is_user_watchlist=is_watchlisted,
        is_first_seen=False,
    )

    return DailyActionItem(
        symbol=symbol,
        company_name=str(candidate.get("company_name") or symbol),
        action_tier=action_tier,
        action_label=build_action_label(action_tier, workflow_status=workflow["research_status"]),
        reasons=[data_quality_caveat or "Açık araştırma işi backlog'ta."][:1],
        workflow_status=workflow["research_status"],
        workflow_status_label=workflow["research_status_label"],
        next_action=workflow.get("research_next_action"),
        last_reviewed_at=workflow.get("last_reviewed_at"),
        is_watchlisted=is_watchlisted,
        meaningful_change_count=0,
        window_change_score=0,
        research_priority_score=float(priority.get("priority_score") or 0),
        research_priority_label=str(priority.get("priority_label") or "—"),
        is_first_seen=False,
        data_quality_band=data_quality_band,
        data_quality_caveat=data_quality_caveat,
        latest_scan_at=None,
        company_report_target=candidate,
        candidate=candidate,
        is_availability_only=False,
        is_research_actionable=False,
        signal_summary=SignalSummary(),
    )


def _merge_monitor_entries(
    base: Dict[str, Any],
    overlay: Dict[str, Any],
) -> Dict[str, Any]:
    merged = dict(overlay)

    base_events = list(base.get("events") or [])
    overlay_events = list(overlay.get("events") or [])
    seen = {
        (event.get("field"), event.get("category"), event.get("message"))
        for event in overlay_events
    }
    for event in base_events:
        key = (event.get("field"), event.get("category"), event.get("message"))
        if key not in seen:
            overlay_events.append(event)
            seen.add(key)
    merged["events"] = overlay_events

    merged["meaningful_change_count"] = max(
        int(base.get("meaningful_change_count") or 0),
        int(overlay.get("meaningful_change_count") or 0),
    )
    merged["window_change_score"] = max(
        int(base.get("window_change_score") or 0),
        int(overlay.get("window_change_score") or 0),
    )
    merged["is_first_seen_in_window"] = bool(
        base.get("is_first_seen_in_window")
        or overlay.get("is_first_seen_in_window")
    )
    return merged


def _index_monitor_entries(feed: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    categories = feed.get("categories") or {}
    for category in (
        "DATA_ISSUES",
        CATEGORY_NEW,
        CATEGORY_WATCHLIST,
        CATEGORY_ATTENTION,
    ):
        for entry in categories.get(category) or []:
            symbol = str(entry.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            if symbol in indexed:
                indexed[symbol] = _merge_monitor_entries(indexed[symbol], entry)
            else:
                indexed[symbol] = dict(entry)

    for entry in feed.get("entries") or []:
        symbol = str(entry.get("symbol") or "").strip().upper()
        if symbol and symbol not in indexed:
            indexed[symbol] = entry

    return indexed


def _index_candidates(
    candidates: Optional[Sequence[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates or []:
        symbol = str(candidate.get("symbol") or "").strip().upper()
        if symbol:
            indexed[symbol] = candidate
    return indexed


def _is_action_eligible_monitor_entry(entry: Dict[str, Any]) -> bool:
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


def _is_reviewed_without_new_change(item: DailyActionItem) -> bool:
    if item.meaningful_change_count <= 0:
        return False

    reviewed_at = _parse_datetime(item.last_reviewed_at)
    latest_at = _parse_datetime(item.latest_scan_at)
    if reviewed_at is None or latest_at is None:
        return False

    return reviewed_at >= latest_at


def _action_sort_key(item: DailyActionItem) -> tuple:
    tier_rank = {
        ACTION_TIER_T1: 0,
        ACTION_TIER_T2: 1,
        ACTION_TIER_T3: 2,
        ACTION_TIER_T4: 3,
        ACTION_TIER_T5: 4,
    }
    return (
        tier_rank.get(item.action_tier, 99),
        -item.meaningful_change_count,
        -item.window_change_score,
        WORKFLOW_RANK.get(item.workflow_status, 99),
        0 if _clean_text(item.next_action) else 1,
        0 if item.is_watchlisted else 1,
        -item.research_priority_score,
        str(item.latest_scan_at or ""),
        item.symbol,
    )


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None
