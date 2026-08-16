from __future__ import annotations

from typing import Iterable, Mapping, Tuple

from services.monitor_contract import (
    EVENT_CONCENTRATION_THRESHOLD_CROSSED,
    EVENT_DECISION_EVIDENCE_GAP,
    EVENT_REFERENCE_LIMIT_BREACHED,
    MonitorEventDraft,
)
from services.monitor_materiality_engine import apply_materiality_to_draft
from services.portfolio_construction_contract import ReferenceLimitGap


def detect_reference_limit_events(
    *,
    user_id: str,
    portfolio_id: str,
    reference_gaps: Iterable[ReferenceLimitGap],
) -> Tuple[MonitorEventDraft, ...]:
    drafts: list[MonitorEventDraft] = []
    for gap in reference_gaps:
        if gap.status != "breach":
            continue
        event_type = (
            EVENT_CONCENTRATION_THRESHOLD_CROSSED
            if "concentration" in gap.dimension or "position" in gap.dimension
            else EVENT_REFERENCE_LIMIT_BREACHED
        )
        draft = MonitorEventDraft(
            user_id=user_id,
            portfolio_id=portfolio_id,
            symbol=None,
            event_type=event_type,
            event_category="wealth",
            severity="watch",
            materiality="medium",
            occurred_at="",
            dedupe_key=f"wave3:{portfolio_id}:{gap.dimension}:{gap.reference_limit}",
            title=f"Referans limit aşımı: {gap.dimension}",
            summary=gap.note,
            previous_value=(
                f"{gap.reference_limit:.1f}%"
                if gap.reference_limit is not None
                else None
            ),
            current_value=(
                f"{gap.current_value:.1f}%"
                if gap.current_value is not None
                else None
            ),
            event_payload={"dimension": gap.dimension, "gap_pp": gap.gap_pp},
            notification_eligible=False,
        )
        drafts.append(apply_materiality_to_draft(draft))
    return tuple(drafts)


def detect_decision_evidence_gap_event(
    *,
    user_id: str,
    portfolio_id: str,
    unavailable_count: int,
    total_count: int,
) -> Tuple[MonitorEventDraft, ...]:
    if unavailable_count <= 0 or total_count <= 0:
        return ()
    ratio = unavailable_count / total_count
    if ratio < 0.25:
        return ()
    draft = MonitorEventDraft(
        user_id=user_id,
        portfolio_id=portfolio_id,
        symbol=None,
        event_type=EVENT_DECISION_EVIDENCE_GAP,
        event_category="wealth",
        severity="info",
        materiality="low",
        occurred_at="",
        dedupe_key=f"wave3:{portfolio_id}:decision_evidence_gap",
        title="Karar sonucu kanıt boşluğu",
        summary=(
            f"{unavailable_count}/{total_count} karar kaydında geçmiş fiyat "
            "kanıtı eksik; sonuçlar PARTIAL/UNAVAILABLE."
        ),
        event_payload={
            "unavailable_count": unavailable_count,
            "total_count": total_count,
        },
        notification_eligible=False,
    )
    return (apply_materiality_to_draft(draft),)
