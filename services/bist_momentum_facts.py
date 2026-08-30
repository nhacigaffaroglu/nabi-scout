"""Map official BIST THB history onto existing canonical Momentum.

Reuses local_market_history_service lookbacks and drawdown. Does not invent
volatility/beta/RSI. Does not fetch THB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from services.bist_corporate_action_audit import (
    OfficialCorporateAction,
    STATUS_UNRESOLVED,
    apply_official_adjustments,
    events_from_thb_flags,
    merge_official_events,
    window_adjustment_status,
)
from services.bist_symbol_mapping import normalize_bist_symbol
from services.bist_thb_history import BistHistoricalPrice, SOURCE_THB_HISTORY, history_quality
from services.local_market_history_service import (
    HIGH_LOW_MIN_DAYS,
    HIGH_LOW_MIN_OBS,
    HORIZONS,
    LocalMomentumFacts,
    PriceObservation,
    compute_local_momentum,
    select_horizon_anchor,
)
from services.security_intelligence_contract import AUTHORITY_BORSA_ISTANBUL
from services.wealth_contract import normalize_symbol


ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
MOMENTUM_FIELDS = ("return_3m", "return_6m", "return_1y", "drawdown")
RETURN_NORMALIZATION = "OFFICIAL_THB_PRICE_RETURN"
DRAWDOWN_NORMALIZATION = "OFFICIAL_THB_MAX_DRAWDOWN"
QUALITY_DUPLICATE = "DUPLICATE_TRADE_DATE"
QUALITY_CURRENCY = "NON_TRY_HISTORY"
QUALITY_INSUFFICIENT = "INSUFFICIENT_HISTORY"


def _canonical(symbol: str) -> str:
    return normalize_bist_symbol(symbol) or normalize_symbol(symbol)


def _as_of_dt(day: date) -> datetime:
    return datetime.combine(day, time(18, 0), tzinfo=ISTANBUL_TZ).astimezone(timezone.utc)


def observations_from_history(
    series: Sequence[BistHistoricalPrice],
) -> tuple[PriceObservation, ...]:
    return tuple(
        PriceObservation(as_of=_as_of_dt(item.trade_date), price=item.close, source=SOURCE_THB_HISTORY)
        for item in series
    )


def reject_duplicates(series: Sequence[BistHistoricalPrice]) -> Optional[str]:
    seen: set[date] = set()
    for item in series:
        if item.trade_date in seen:
            return QUALITY_DUPLICATE
        seen.add(item.trade_date)
    return None


def reject_non_try(series: Sequence[BistHistoricalPrice]) -> Optional[str]:
    if any(item.currency != "TRY" for item in series):
        return QUALITY_CURRENCY
    return None


@dataclass(frozen=True)
class BistMomentumBundle:
    symbol: str
    momentum: LocalMomentumFacts
    adjustment_status: str
    quality: dict[str, object]
    anchors: dict[str, dict[str, object]]
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "momentum": self.momentum.to_dict(),
            "adjustment_status": self.adjustment_status,
            "quality": dict(self.quality),
            "anchors": {key: dict(value) for key, value in self.anchors.items()},
            "blocked_reason": self.blocked_reason,
        }


def _empty_momentum(source: str = SOURCE_THB_HISTORY) -> LocalMomentumFacts:
    return LocalMomentumFacts(
        values={name: None for name in (*HORIZONS, "high_52w", "low_52w", "drawdown", "volatility")},
        provenance=(),
        observations=0,
        unique_prices=0,
        span_days=None,
        source=source,
        usable=False,
        authority=AUTHORITY_BORSA_ISTANBUL,
    )


def _anchor_payload(
    series: Sequence[BistHistoricalPrice],
    field: str,
) -> Optional[dict[str, object]]:
    spec = HORIZONS[field]
    observations = observations_from_history(series)
    pair = select_horizon_anchor(
        observations,
        target_days=spec["target_days"],
        min_days=spec["min_days"],
        max_days=spec["max_days"],
    )
    if pair is None:
        return None
    start, end = pair
    start_row = next(item for item in series if _as_of_dt(item.trade_date) == start.as_of)
    end_row = next(item for item in series if _as_of_dt(item.trade_date) == end.as_of)
    return {
        "target_days": spec["target_days"],
        "start_date": start_row.trade_date.isoformat(),
        "end_date": end_row.trade_date.isoformat(),
        "start_price": start_row.close,
        "end_price": end_row.close,
        "observation_count": len(series),
        "adjustment_status": start_row.adjustment_status,
    }


def momentum_from_bist_history(
    series: Sequence[BistHistoricalPrice],
    *,
    symbol: str,
    official_events: Iterable[OfficialCorporateAction] = (),
    as_of: Optional[date] = None,
) -> BistMomentumBundle:
    ticker = _canonical(symbol)
    ordered = tuple(sorted(series, key=lambda item: item.trade_date))
    quality = history_quality(ordered, as_of=as_of)
    events = merge_official_events(official_events, events_from_thb_flags(ordered))
    duplicate = reject_duplicates(ordered)
    currency = reject_non_try(ordered)
    if duplicate or currency:
        return BistMomentumBundle(
            symbol=ticker,
            momentum=_empty_momentum(),
            adjustment_status=STATUS_UNRESOLVED,
            quality=quality,
            anchors={},
            blocked_reason=duplicate or currency or QUALITY_INSUFFICIENT,
        )
    if len(ordered) < 2:
        return BistMomentumBundle(
            symbol=ticker,
            momentum=_empty_momentum(),
            adjustment_status=QUALITY_INSUFFICIENT,
            quality=quality,
            anchors={},
            blocked_reason=QUALITY_INSUFFICIENT,
        )

    adjusted, adj_status = apply_official_adjustments(ordered, events)
    working = ordered if adj_status == STATUS_UNRESOLVED else adjusted

    raw = compute_local_momentum(
        observations_from_history(working),
        source=SOURCE_THB_HISTORY,
        authority=AUTHORITY_BORSA_ISTANBUL,
        return_normalization=RETURN_NORMALIZATION,
        extreme_normalization=DRAWDOWN_NORMALIZATION,
        require_unique_prices=False,
    )
    values = dict(raw.values)
    provenance = list(raw.provenance)
    anchors: dict[str, dict[str, object]] = {}
    end_date = working[-1].trade_date

    for field in ("return_3m", "return_6m", "return_1y"):
        payload = _anchor_payload(working, field)
        if payload is None:
            values[field] = None
            provenance = [item for item in provenance if item.field != field]
            continue
        start = date.fromisoformat(str(payload["start_date"]))
        status = window_adjustment_status(events, start=start, end=end_date)
        payload["adjustment_status"] = status
        anchors[field] = payload
        if status == STATUS_UNRESOLVED:
            values[field] = None
            provenance = [item for item in provenance if item.field != field]

    if values.get("drawdown") is not None:
        span_start = working[0].trade_date
        draw_status = window_adjustment_status(events, start=span_start, end=end_date)
        anchors["drawdown"] = {
            "formula": "(running_peak - price) / running_peak * 100",
            "min_span_days": HIGH_LOW_MIN_DAYS,
            "min_observations": HIGH_LOW_MIN_OBS,
            "start_date": span_start.isoformat(),
            "end_date": end_date.isoformat(),
            "adjustment_status": draw_status,
        }
        if draw_status == STATUS_UNRESOLVED:
            values["drawdown"] = None
            provenance = [item for item in provenance if item.field != "drawdown"]

    momentum = LocalMomentumFacts(
        values=values,
        provenance=tuple(provenance),
        observations=raw.observations,
        unique_prices=raw.unique_prices,
        span_days=raw.span_days,
        source=SOURCE_THB_HISTORY,
        usable=any(values.get(name) is not None for name in MOMENTUM_FIELDS),
        authority=AUTHORITY_BORSA_ISTANBUL,
    )
    return BistMomentumBundle(
        symbol=ticker,
        momentum=momentum,
        adjustment_status=adj_status,
        quality=quality,
        anchors=anchors,
    )
