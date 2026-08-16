from __future__ import annotations

from services.monitor_contract import (
    EVENT_CONCENTRATION_CHANGED,
    EVENT_PARTICIPATION_STATUS_CHANGED,
    EVENT_PORTFOLIO_VALUE_CHANGED,
    EVENT_PORTFOLIO_WEIGHT_CHANGED,
    EVENT_POSSIBLE_INVALIDATION_SIGNAL,
    EVENT_RESEARCH_BECAME_STALE,
    EVENT_THESIS_CONFIDENCE_CHANGED,
    EVENT_THESIS_STATUS_CHANGED,
    MonitorEventDraft,
)

CONCENTRATION_HIGH_THRESHOLD_PCT = 15.0
WEIGHT_CHANGE_INFO_PCT = 0.5
WEIGHT_CHANGE_MEDIUM_PCT = 2.0
WEIGHT_CHANGE_HIGH_PCT = 5.0
PORTFOLIO_VALUE_MEDIUM_USD = 500.0
PORTFOLIO_VALUE_HIGH_USD = 5000.0

PARTICIPATION_CRITICAL_TRANSITIONS = {
    ("uygun", "uygun değil"),
}
PARTICIPATION_HIGH_TRANSITIONS = {
    ("uygun", "kontrol et"),
    ("kontrol et", "uygun değil"),
}


def classify_materiality(
    *,
    event_type: str,
    severity: str,
    portfolio_weight: float | None = None,
    absolute_change: float | None = None,
    previous_value: str | None = None,
    current_value: str | None = None,
) -> str:
    if event_type == EVENT_PARTICIPATION_STATUS_CHANGED:
        prev = str(previous_value or "").strip().lower()
        curr = str(current_value or "").strip().lower()
        if (prev, curr) in PARTICIPATION_CRITICAL_TRANSITIONS or curr == "uygun değil":
            return "critical"
        if (prev, curr) in PARTICIPATION_HIGH_TRANSITIONS:
            return "high"
        return "medium"

    if event_type in {EVENT_THESIS_STATUS_CHANGED, EVENT_POSSIBLE_INVALIDATION_SIGNAL}:
        return "high"

    if event_type == EVENT_THESIS_CONFIDENCE_CHANGED:
        return "medium"

    if event_type == EVENT_CONCENTRATION_CHANGED:
        return "high"

    if event_type == EVENT_PORTFOLIO_WEIGHT_CHANGED and portfolio_weight is not None:
        if portfolio_weight >= CONCENTRATION_HIGH_THRESHOLD_PCT:
            return "high"
        if absolute_change is not None and abs(absolute_change) >= WEIGHT_CHANGE_HIGH_PCT:
            return "medium"
        if absolute_change is not None and abs(absolute_change) >= WEIGHT_CHANGE_MEDIUM_PCT:
            return "low"
        return "info"

    if event_type == EVENT_PORTFOLIO_VALUE_CHANGED and absolute_change is not None:
        if abs(absolute_change) >= PORTFOLIO_VALUE_HIGH_USD:
            return "medium"
        if abs(absolute_change) >= PORTFOLIO_VALUE_MEDIUM_USD:
            return "low"
        return "info"

    if event_type == EVENT_RESEARCH_BECAME_STALE:
        return "low"

    if severity == "critical":
        return "critical"
    if severity == "high":
        return "high"
    if severity == "watch":
        return "medium"
    return "info"


def notification_for_materiality(
    materiality: str,
    *,
    held: bool,
    event_type: str,
) -> tuple[bool, str | None]:
    if materiality not in {"high", "critical"}:
        return False, None
    if not held and event_type.startswith("PORTFOLIO"):
        return False, None
    if materiality == "critical":
        return True, "Kritik portföy veya katılım değişikliği"
    return True, "Yüksek öncelikli inceleme önerilir"


def severity_from_materiality(materiality: str) -> str:
    if materiality == "critical":
        return "critical"
    if materiality == "high":
        return "high"
    if materiality in {"medium", "low"}:
        return "watch"
    return "info"


def apply_materiality_to_draft(
    draft: MonitorEventDraft,
    *,
    portfolio_weight: float | None = None,
) -> MonitorEventDraft:
    materiality = classify_materiality(
        event_type=draft.event_type,
        severity=draft.severity,
        portfolio_weight=portfolio_weight,
        absolute_change=draft.absolute_change,
        previous_value=draft.previous_value,
        current_value=draft.current_value,
    )
    severity = severity_from_materiality(materiality)
    eligible, reason = notification_for_materiality(
        materiality,
        held=portfolio_weight is not None and portfolio_weight > 0,
        event_type=draft.event_type,
    )
    return MonitorEventDraft(
        user_id=draft.user_id,
        portfolio_id=draft.portfolio_id,
        symbol=draft.symbol,
        event_type=draft.event_type,
        event_category=draft.event_category,
        severity=severity,
        materiality=materiality,
        occurred_at=draft.occurred_at,
        dedupe_key=draft.dedupe_key,
        title=draft.title,
        summary=draft.summary,
        evidence_type=draft.evidence_type,
        evidence_reference=draft.evidence_reference,
        previous_value=draft.previous_value,
        current_value=draft.current_value,
        absolute_change=draft.absolute_change,
        percentage_change=draft.percentage_change,
        event_payload=draft.event_payload,
        notification_eligible=eligible,
        notification_reason=reason,
    )
