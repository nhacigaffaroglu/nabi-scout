"""Compact recommendation-history presentation. No analytics dashboard."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from services.nabi_recommendation_history_contract import (
    OutcomeObservation,
    RecommendationHistoryRecord,
)
from services.nabi_recommendation_history_store import InMemoryRecommendationHistoryStore

TRACKING_READY = "Recommendation tracking ready"
HISTORY_EMPTY = "No recorded recommendations yet."
HISTORY_SECTION = "Öneri geçmişi"
PENDING_LABEL = "pending"
MATURE_LABEL = "mature"


def present_tracking_status(
    store: Optional[InMemoryRecommendationHistoryStore] = None,
) -> str:
    latest = store.latest_record() if store is not None else None
    if latest is None:
        return TRACKING_READY
    return f"Latest recorded recommendation: {latest.generated_at[:10]}"


def present_history_line(record: RecommendationHistoryRecord) -> str:
    when = record.generated_at[:10] if record.generated_at else "—"
    symbol = record.symbol or "—"
    return f"{when} · {symbol} · {record.final_action}"


def present_outcome_line(observation: OutcomeObservation) -> str:
    maturity = MATURE_LABEL if observation.mature else PENDING_LABEL
    if observation.return_pct is None:
        happened = observation.outcome_state
    else:
        happened = f"{observation.return_pct:.2f}% · {observation.outcome_state}"
    return (
        f"{observation.window} · {happened} · {maturity} · {observation.interpretation}"
    )


def present_history_rows(
    records: Sequence[RecommendationHistoryRecord],
    outcomes: Sequence[OutcomeObservation] = (),
) -> Tuple[str, ...]:
    by_id: dict[str, list[OutcomeObservation]] = {}
    for row in outcomes:
        by_id.setdefault(row.recommendation_id, []).append(row)
    lines: list[str] = []
    for record in records:
        lines.append(present_history_line(record))
        if record.why:
            lines.append(f"Why: {record.why}")
        if record.reason_codes:
            lines.append("Reasons: " + ", ".join(record.reason_codes))
        related = by_id.get(record.recommendation_id, [])
        if not related:
            lines.append("Outcome: pending")
        for observation in related:
            lines.append(present_outcome_line(observation))
    return tuple(lines)
