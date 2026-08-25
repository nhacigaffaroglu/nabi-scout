"""Append-only in-memory recommendation history store. No production backend."""

from __future__ import annotations

from typing import Optional, Tuple

from services.nabi_recommendation_history_contract import (
    OutcomeObservation,
    RecommendationHistoryRecord,
)


class InMemoryRecommendationHistoryStore:
    """History-preserving store for tests and explicit future persist paths."""

    def __init__(self) -> None:
        self._records: list[RecommendationHistoryRecord] = []
        self._outcomes: list[OutcomeObservation] = []

    def append_record(self, record: RecommendationHistoryRecord) -> RecommendationHistoryRecord:
        self._records.append(record)
        return record

    def append_outcome(self, observation: OutcomeObservation) -> OutcomeObservation:
        self._outcomes.append(observation)
        return observation

    def find_by_logical_id(self, logical_event_id: str) -> Optional[RecommendationHistoryRecord]:
        for row in reversed(self._records):
            if row.logical_event_id == logical_event_id:
                return row
        return None

    def get_record(self, recommendation_id: str) -> Optional[RecommendationHistoryRecord]:
        for row in self._records:
            if row.recommendation_id == recommendation_id:
                return row
        return None

    def find_outcome(
        self, recommendation_id: str, window: str
    ) -> Optional[OutcomeObservation]:
        for row in reversed(self._outcomes):
            if row.recommendation_id == recommendation_id and row.window == window:
                return row
        return None

    def list_records(self) -> Tuple[RecommendationHistoryRecord, ...]:
        return tuple(self._records)

    def list_outcomes(
        self, recommendation_id: Optional[str] = None
    ) -> Tuple[OutcomeObservation, ...]:
        if recommendation_id is None:
            return tuple(self._outcomes)
        return tuple(
            row for row in self._outcomes if row.recommendation_id == recommendation_id
        )

    def latest_record(self) -> Optional[RecommendationHistoryRecord]:
        return self._records[-1] if self._records else None
