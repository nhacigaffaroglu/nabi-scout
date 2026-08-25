"""Observational performance summary over recommendation outcomes. No score."""

from __future__ import annotations

from statistics import median
from typing import Iterable, Optional, Sequence, Tuple

from services.nabi_recommendation_history_contract import (
    INTERPRET_INVESTMENT_MEASURED,
    OUTCOME_NEGATIVE,
    OUTCOME_POSITIVE,
    OUTCOME_UNKNOWN,
    POLICY_LEARNING_STATE,
    SMALL_SAMPLE_THRESHOLD,
    OBSERVATION_NOT_CAUSAL,
    PerformanceBucket,
    PerformanceSummary,
    OutcomeObservation,
    RecommendationHistoryRecord,
)


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _bucket(
    outcomes: Sequence[OutcomeObservation],
    *,
    action: Optional[str] = None,
    window: Optional[str] = None,
    research_completeness: Optional[str] = None,
    timing_state: Optional[str] = None,
    portfolio_fit: Optional[str] = None,
    decision_class: Optional[str] = None,
    investment_evaluated: bool,
) -> PerformanceBucket:
    observed = [
        row.return_pct
        for row in outcomes
        if row.return_pct is not None and row.outcome_state != OUTCOME_UNKNOWN
    ]
    unknown = sum(1 for row in outcomes if row.outcome_state == OUTCOME_UNKNOWN)
    positive = sum(1 for row in outcomes if row.outcome_state == OUTCOME_POSITIVE)
    negative = sum(1 for row in outcomes if row.outcome_state == OUTCOME_NEGATIVE)
    return PerformanceBucket(
        action=action,
        window=window,
        research_completeness=research_completeness,
        timing_state=timing_state,
        portfolio_fit=portfolio_fit,
        decision_class=decision_class,
        count=len(outcomes),
        observed_count=len(observed),
        unknown_count=unknown,
        average_return=_mean(observed),
        median_return=median(observed) if observed else None,
        positive_count=positive,
        negative_count=negative,
        small_sample=len(outcomes) < SMALL_SAMPLE_THRESHOLD,
        investment_evaluated=investment_evaluated,
    )


def summarize_outcomes(
    records: Sequence[RecommendationHistoryRecord],
    outcomes: Sequence[OutcomeObservation],
) -> PerformanceSummary:
    by_id = {row.recommendation_id: row for row in records}
    buckets: list[PerformanceBucket] = []
    by_action: dict[str, list[OutcomeObservation]] = {}
    by_window: dict[str, list[OutcomeObservation]] = {}
    by_completeness: dict[str, list[OutcomeObservation]] = {}
    by_timing: dict[str, list[OutcomeObservation]] = {}
    by_fit: dict[str, list[OutcomeObservation]] = {}
    by_class: dict[str, list[OutcomeObservation]] = {}
    measured: list[OutcomeObservation] = []
    for row in outcomes:
        by_action.setdefault(row.action, []).append(row)
        by_window.setdefault(row.window, []).append(row)
        record = by_id.get(row.recommendation_id)
        if record is not None:
            if record.research_completeness:
                by_completeness.setdefault(record.research_completeness, []).append(row)
            if record.timing_state:
                by_timing.setdefault(record.timing_state, []).append(row)
            if record.portfolio_fit:
                by_fit.setdefault(record.portfolio_fit, []).append(row)
            if record.decision_class:
                by_class.setdefault(record.decision_class, []).append(row)
        if row.interpretation == INTERPRET_INVESTMENT_MEASURED:
            measured.append(row)
    for action, rows in sorted(by_action.items()):
        buckets.append(
            _bucket(
                rows,
                action=action,
                investment_evaluated=action
                in {
                    row.action
                    for row in rows
                    if row.interpretation == INTERPRET_INVESTMENT_MEASURED
                },
            )
        )
    for window, rows in sorted(by_window.items()):
        buckets.append(
            _bucket(
                rows,
                window=window,
                investment_evaluated=any(
                    row.interpretation == INTERPRET_INVESTMENT_MEASURED for row in rows
                ),
            )
        )
    for completeness, rows in sorted(by_completeness.items()):
        buckets.append(
            _bucket(
                rows,
                research_completeness=completeness,
                investment_evaluated=any(
                    row.interpretation == INTERPRET_INVESTMENT_MEASURED for row in rows
                ),
            )
        )
    for timing, rows in sorted(by_timing.items()):
        buckets.append(
            _bucket(
                rows,
                timing_state=timing,
                investment_evaluated=any(
                    row.interpretation == INTERPRET_INVESTMENT_MEASURED for row in rows
                ),
            )
        )
    for fit, rows in sorted(by_fit.items()):
        buckets.append(
            _bucket(
                rows,
                portfolio_fit=fit,
                investment_evaluated=any(
                    row.interpretation == INTERPRET_INVESTMENT_MEASURED for row in rows
                ),
            )
        )
    for decision, rows in sorted(by_class.items()):
        buckets.append(
            _bucket(
                rows,
                decision_class=decision,
                investment_evaluated=any(
                    row.interpretation == INTERPRET_INVESTMENT_MEASURED for row in rows
                ),
            )
        )
    buckets.append(
        _bucket(measured, investment_evaluated=True)
        if measured
        else _bucket((), investment_evaluated=True)
    )
    return PerformanceSummary(
        buckets=tuple(buckets),
        limitation=OBSERVATION_NOT_CAUSAL,
        auto_policy_learning=POLICY_LEARNING_STATE,
    )


def investment_failure_count(outcomes: Iterable[OutcomeObservation]) -> int:
    return sum(
        1
        for row in outcomes
        if row.interpretation == INTERPRET_INVESTMENT_MEASURED
        and row.outcome_state == OUTCOME_NEGATIVE
    )
