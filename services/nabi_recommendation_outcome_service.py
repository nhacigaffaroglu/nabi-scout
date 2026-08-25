"""Outcome observation for recommendation history. No market-data engine."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Mapping, Optional, Protocol, Tuple

from services.nabi_recommendation_history_contract import (
    ACTION_INTERPRETATION,
    INTERPRET_NOT_INVESTMENT,
    OUTCOME_FLAT,
    OUTCOME_NEGATIVE,
    OUTCOME_POSITIVE,
    OUTCOME_UNKNOWN,
    OUTCOME_WINDOWS,
    WINDOW_DAYS,
    OutcomeObservation,
    RecommendationHistoryRecord,
)
from services.nabi_recommendation_history_store import InMemoryRecommendationHistoryStore


class PriceObservationSource(Protocol):
    def price_on(self, symbol: str, when: date) -> Optional["PricePoint"]:
        ...


class PricePoint:
    def __init__(
        self,
        price: float,
        currency: str,
        *,
        as_of: str,
        source_reference: str,
    ) -> None:
        self.price = price
        self.currency = str(currency or "").strip().upper()
        self.as_of = as_of
        self.source_reference = source_reference


class DictPriceBook:
    """Fixture / local evidence book. No provider calls."""

    def __init__(self, rows: Mapping[tuple[str, str], PricePoint]) -> None:
        self._rows = {
            (str(symbol).upper(), str(day)): point for (symbol, day), point in rows.items()
        }

    def price_on(self, symbol: str, when: date) -> Optional[PricePoint]:
        return self._rows.get((str(symbol or "").upper(), when.isoformat()))


def _as_date(value: str) -> date:
    text = str(value or "")[:10]
    return date.fromisoformat(text)


def window_end_date(recommendation_date: date, window: str) -> date:
    return recommendation_date + timedelta(days=WINDOW_DAYS[window])


def is_window_mature(
    recommendation_date: date, window: str, as_of: date
) -> bool:
    return as_of >= window_end_date(recommendation_date, window)


def _state_from_return(return_pct: Optional[float]) -> str:
    if return_pct is None:
        return OUTCOME_UNKNOWN
    if return_pct > 0:
        return OUTCOME_POSITIVE
    if return_pct < 0:
        return OUTCOME_NEGATIVE
    return OUTCOME_FLAT


def _unknown(
    record: RecommendationHistoryRecord,
    window: str,
    observation_date: str,
    *,
    observation_price: Optional[float] = None,
    currency: Optional[str] = None,
    source_reference: Optional[str] = None,
    mature: bool,
) -> OutcomeObservation:
    interpretation = ACTION_INTERPRETATION.get(
        record.final_action, INTERPRET_NOT_INVESTMENT
    )
    return OutcomeObservation(
        recommendation_id=record.recommendation_id,
        symbol=record.symbol,
        window=window,
        recommendation_date=record.generated_at[:10],
        observation_date=observation_date,
        entry_price=record.price_at_recommendation,
        observation_price=observation_price,
        price_currency=currency,
        return_pct=None,
        outcome_state=OUTCOME_UNKNOWN,
        source_reference=source_reference,
        interpretation=interpretation,
        mature=mature,
        action=record.final_action,
    )


def observe_window(
    record: RecommendationHistoryRecord,
    window: str,
    *,
    as_of: date,
    prices: PriceObservationSource,
    store: Optional[InMemoryRecommendationHistoryStore] = None,
) -> OutcomeObservation:
    if window not in OUTCOME_WINDOWS:
        raise ValueError(f"Unsupported outcome window: {window}")
    existing = store.find_outcome(record.recommendation_id, window) if store else None
    if existing is not None:
        return existing
    rec_date = _as_date(record.generated_at)
    observation_date = window_end_date(rec_date, window)
    mature = is_window_mature(rec_date, window, as_of)
    as_of_iso = as_of.isoformat()
    if not mature:
        return _unknown(
            record,
            window,
            as_of_iso,
            mature=False,
        )
    symbol = str(record.symbol or "").upper()
    point = prices.price_on(symbol, observation_date) if symbol else None
    entry = record.price_at_recommendation
    entry_ccy = str(record.price_currency or "").strip().upper()
    obs_ccy = str(point.currency if point else "").strip().upper()
    if (
        entry is None
        or point is None
        or point.price is None
        or not entry_ccy
        or not obs_ccy
        or entry_ccy != obs_ccy
    ):
        observation = _unknown(
            record,
            window,
            observation_date.isoformat(),
            observation_price=None if point is None else point.price,
            currency=obs_ccy or entry_ccy or None,
            source_reference=None if point is None else point.source_reference,
            mature=True,
        )
        return store.append_outcome(observation) if store else observation
    return_pct = (float(point.price) - float(entry)) / float(entry) * 100.0
    interpretation = ACTION_INTERPRETATION.get(
        record.final_action, INTERPRET_NOT_INVESTMENT
    )
    state = _state_from_return(return_pct)
    if interpretation == INTERPRET_NOT_INVESTMENT:
        state = OUTCOME_UNKNOWN
    observation = OutcomeObservation(
        recommendation_id=record.recommendation_id,
        symbol=record.symbol,
        window=window,
        recommendation_date=record.generated_at[:10],
        observation_date=observation_date.isoformat(),
        entry_price=float(entry),
        observation_price=float(point.price),
        price_currency=entry_ccy,
        return_pct=return_pct,
        outcome_state=state,
        source_reference=point.source_reference,
        interpretation=interpretation,
        mature=True,
        action=record.final_action,
    )
    return store.append_outcome(observation) if store else observation


def observe_matured_windows(
    record: RecommendationHistoryRecord,
    *,
    as_of: date,
    prices: PriceObservationSource,
    store: Optional[InMemoryRecommendationHistoryStore] = None,
    windows: Tuple[str, ...] = OUTCOME_WINDOWS,
) -> Tuple[OutcomeObservation, ...]:
    return tuple(
        observe_window(record, window, as_of=as_of, prices=prices, store=store)
        for window in windows
        if is_window_mature(_as_date(record.generated_at), window, as_of)
    )
