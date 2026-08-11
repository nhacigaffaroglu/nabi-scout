from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

SIGNAL_FAMILY_RESEARCH = "RESEARCH"
SIGNAL_FAMILY_DATA_QUALITY = "DATA_QUALITY"
SIGNAL_FAMILY_DISCOVERY = "DISCOVERY"
SIGNAL_FAMILY_UNKNOWN = "UNKNOWN"

DIRECTION_RECOVERY = "RECOVERY"
DIRECTION_DEGRADATION = "DEGRADATION"
DIRECTION_CHANGE = "CHANGE"

_RESEARCH_CATEGORIES = frozenset({
    "DECISION",
    "SCORE",
    "GROWTH",
    "QUALITY",
    "VALUATION",
})

_DATA_QUALITY_CATEGORIES = frozenset({
    "COMPLETENESS",
    "AVAILABILITY",
    "FRESHNESS",
    "DATA_STATUS",
})

_RESEARCH_FIELDS = frozenset({
    "decision_label",
    "excluded",
    "nabi_score",
    "opportunity_score",
    "conviction_score",
    "roic",
    "revenue_growth_1y",
    "revenue_cagr_3y",
    "free_cash_flow_margin",
    "pe_ratio",
})

_DATA_QUALITY_FIELDS = frozenset({
    "data_completeness",
    "freshness_status",
    "pe_source",
    "research_confidence",
    "score_confidence",
    "status",
})

_FRESHNESS_RANK = {
    "FRESH": 0,
    "AGING": 1,
    "UNKNOWN": 1,
    "STALE": 2,
}


@dataclass(frozen=True)
class SignalSummary:
    families: FrozenSet[str] = field(default_factory=frozenset)
    research_event_count: int = 0
    data_quality_event_count: int = 0
    unknown_event_count: int = 0
    has_discovery: bool = False
    primary_data_quality_direction: Optional[str] = None
    is_research_actionable: bool = False
    is_data_quality_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["families"] = sorted(self.families)
        return payload


def classify_event(event: Any) -> str:
    if not isinstance(event, dict):
        return SIGNAL_FAMILY_UNKNOWN

    category = str(event.get("category") or "").strip().upper()
    field_name = str(event.get("field") or "").strip()

    if category in _RESEARCH_CATEGORIES or field_name in {"decision_label", "excluded"}:
        if field_name == "pe_ratio" and category == "AVAILABILITY":
            return SIGNAL_FAMILY_DATA_QUALITY
        if field_name == "pe_ratio" and category == "VALUATION":
            return SIGNAL_FAMILY_RESEARCH
        return SIGNAL_FAMILY_RESEARCH

    if category in _DATA_QUALITY_CATEGORIES:
        return SIGNAL_FAMILY_DATA_QUALITY

    if field_name in _DATA_QUALITY_FIELDS:
        return SIGNAL_FAMILY_DATA_QUALITY

    if field_name in _RESEARCH_FIELDS:
        if field_name == "pe_ratio":
            return SIGNAL_FAMILY_RESEARCH
        if field_name in {"research_confidence", "score_confidence", "status", "freshness_status", "pe_source"}:
            return SIGNAL_FAMILY_DATA_QUALITY
        return SIGNAL_FAMILY_RESEARCH

    if category == "STATUS" and field_name == "excluded":
        return SIGNAL_FAMILY_RESEARCH

    if category or field_name:
        return SIGNAL_FAMILY_UNKNOWN

    return SIGNAL_FAMILY_UNKNOWN


def classify_data_quality_direction(event: Any) -> str:
    if not isinstance(event, dict):
        return DIRECTION_CHANGE

    field_name = str(event.get("field") or "").strip()
    category = str(event.get("category") or "").strip().upper()
    old = event.get("old")
    new = event.get("new")
    delta = _as_float(event.get("delta"))

    if field_name == "data_completeness" or category == "COMPLETENESS":
        old_val = _as_float(old)
        new_val = _as_float(new)
        if old_val is not None and new_val is not None:
            if new_val > old_val:
                return DIRECTION_RECOVERY
            if new_val < old_val:
                return DIRECTION_DEGRADATION
        if delta is not None:
            if delta > 0:
                return DIRECTION_RECOVERY
            if delta < 0:
                return DIRECTION_DEGRADATION
        return DIRECTION_CHANGE

    if category == "AVAILABILITY" or field_name in {"pe_source", "pe_ratio"}:
        if new in {"quote", "ratios_ttm"} and old in {None, "missing", "unavailable", ""}:
            return DIRECTION_RECOVERY
        if new in {"unavailable", "missing", None} and old not in {None, "missing", "unavailable", ""}:
            return DIRECTION_DEGRADATION
        if _as_float(new) is not None and _as_float(old) is None:
            return DIRECTION_RECOVERY
        if _as_float(old) is not None and _as_float(new) is None:
            return DIRECTION_DEGRADATION
        return _direction_from_message(event.get("message"))

    if field_name == "freshness_status" or category == "FRESHNESS":
        old_key = str(old or "").strip().upper()
        new_key = str(new or "").strip().upper()
        if old_key and new_key:
            old_rank = _FRESHNESS_RANK.get(old_key, 1)
            new_rank = _FRESHNESS_RANK.get(new_key, 1)
            if new_rank > old_rank:
                return DIRECTION_DEGRADATION
            if new_rank < old_rank:
                return DIRECTION_RECOVERY
        return DIRECTION_CHANGE

    if field_name in {"research_confidence", "score_confidence"}:
        old_val = _as_float(old)
        new_val = _as_float(new)
        if old_val is not None and new_val is not None:
            if new_val > old_val:
                return DIRECTION_RECOVERY
            if new_val < old_val:
                return DIRECTION_DEGRADATION
        if delta is not None:
            if delta > 0:
                return DIRECTION_RECOVERY
            if delta < 0:
                return DIRECTION_DEGRADATION

    if field_name == "status" or category == "DATA_STATUS":
        return DIRECTION_CHANGE

    if delta is not None:
        if delta > 0:
            return DIRECTION_RECOVERY
        if delta < 0:
            return DIRECTION_DEGRADATION

    return DIRECTION_CHANGE


def classify_monitor_entry(entry: Optional[Dict[str, Any]]) -> SignalSummary:
    if not isinstance(entry, dict):
        return SignalSummary()

    events = entry.get("events") or []
    families: set[str] = set()
    research_count = 0
    data_quality_count = 0
    unknown_count = 0
    directions: List[str] = []

    for raw_event in events:
        family = classify_event(raw_event)
        if family == SIGNAL_FAMILY_RESEARCH:
            research_count += 1
            families.add(SIGNAL_FAMILY_RESEARCH)
        elif family == SIGNAL_FAMILY_DATA_QUALITY:
            data_quality_count += 1
            families.add(SIGNAL_FAMILY_DATA_QUALITY)
            directions.append(classify_data_quality_direction(raw_event))
        elif family == SIGNAL_FAMILY_UNKNOWN:
            unknown_count += 1
            families.add(SIGNAL_FAMILY_UNKNOWN)
        else:
            unknown_count += 1
            families.add(SIGNAL_FAMILY_UNKNOWN)

    has_discovery = bool(entry.get("is_first_seen_in_window"))
    if has_discovery:
        families.add(SIGNAL_FAMILY_DISCOVERY)

    primary_direction = _primary_direction(directions)
    is_research_actionable = research_count > 0
    is_data_quality_only = (
        data_quality_count > 0
        and research_count == 0
        and unknown_count == 0
    )

    return SignalSummary(
        families=frozenset(families),
        research_event_count=research_count,
        data_quality_event_count=data_quality_count,
        unknown_event_count=unknown_count,
        has_discovery=has_discovery,
        primary_data_quality_direction=primary_direction,
        is_research_actionable=is_research_actionable,
        is_data_quality_only=is_data_quality_only,
    )


def summarize_data_quality_update(entry: Dict[str, Any], *, direction: Optional[str] = None) -> str:
    resolved = direction or classify_monitor_entry(entry).primary_data_quality_direction
    events = entry.get("events") or []
    dq_events = [
        event for event in events
        if classify_event(event) == SIGNAL_FAMILY_DATA_QUALITY
    ]
    event = dq_events[0] if dq_events else (events[0] if events else {})

    if resolved == DIRECTION_RECOVERY:
        if str(event.get("field") or "") == "data_completeness":
            return "Veri tamlığı yeniden yükseldi."
        if str(event.get("field") or "") == "freshness_status":
            return "Veri güncelliği iyileşti."
        return "Veri erişimi veya kalitesi iyileşti."

    if resolved == DIRECTION_DEGRADATION:
        message = str(event.get("message") or "").strip()
        if message:
            return message
        return "Veri kalitesi veya erişiminde bozulma var."

    message = str(event.get("message") or "").strip()
    if message:
        return message
    return "Veri kalitesi güncellendi."


def data_quality_signal_caveat(summary: SignalSummary) -> Optional[str]:
    if summary.research_event_count > 0 and summary.data_quality_event_count > 0:
        if summary.primary_data_quality_direction == DIRECTION_RECOVERY:
            return "Veri tamlığı veya erişim iyileşti; değerlendirme yeniden mümkün."
        if summary.primary_data_quality_direction == DIRECTION_DEGRADATION:
            return "Veri kalitesi uyarısı devam ediyor."
    return None


def _primary_direction(directions: List[str]) -> Optional[str]:
    if not directions:
        return None
    if DIRECTION_DEGRADATION in directions:
        return DIRECTION_DEGRADATION
    if DIRECTION_RECOVERY in directions:
        return DIRECTION_RECOVERY
    return DIRECTION_CHANGE


def _direction_from_message(message: Any) -> str:
    text = str(message or "").casefold()
    if any(token in text for token in ("erişilemedi", "mevcut değil", "stale")):
        return DIRECTION_DEGRADATION
    if any(token in text for token in ("yeniden erişilebilir", "artık mevcut")):
        return DIRECTION_RECOVERY
    return DIRECTION_CHANGE


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
