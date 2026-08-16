from __future__ import annotations

from typing import Any, Dict, Optional


def build_dedupe_key(*parts: Any) -> str:
    normalized = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    return ":".join(normalized)


def draft_to_row(draft, *, detected_at: str) -> Dict[str, Any]:
    return {
        "user_id": draft.user_id,
        "portfolio_id": draft.portfolio_id,
        "symbol": draft.symbol,
        "event_type": draft.event_type,
        "event_category": draft.event_category,
        "severity": draft.severity,
        "materiality": draft.materiality,
        "occurred_at": draft.occurred_at,
        "detected_at": detected_at,
        "dedupe_key": draft.dedupe_key,
        "title": draft.title,
        "summary": draft.summary,
        "evidence_type": draft.evidence_type,
        "evidence_reference": draft.evidence_reference,
        "previous_value": draft.previous_value,
        "current_value": draft.current_value,
        "absolute_change": draft.absolute_change,
        "percentage_change": draft.percentage_change,
        "event_payload": draft.event_payload,
        "notification_eligible": draft.notification_eligible,
        "notification_reason": draft.notification_reason,
    }
