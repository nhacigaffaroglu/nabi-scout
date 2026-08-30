"""Local mark-to-market history for Security Intelligence momentum.

Production owner: wealth_portfolio_snapshots.valuation_payload.priced_positions.

These snapshots copy CandidatePriceService marks. Consecutive identical prices
are one observation, not a time series. FMP historical-price-eod/light is
plan-restricted and is not called.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from services.security_intelligence_contract import (
    AUTHORITY_CANDIDATE,
    PERIOD_UNKNOWN,
    FactProvenance,
)


SOURCE = "wealth_portfolio_snapshots"
AUTHORITY = AUTHORITY_CANDIDATE

HORIZONS = {
    "return_1d": {"target_days": 1, "min_days": 0.5, "max_days": 2.0},
    "return_1w": {"target_days": 7, "min_days": 5, "max_days": 9},
    "return_1m": {"target_days": 30, "min_days": 24, "max_days": 40},
    "return_3m": {"target_days": 91, "min_days": 75, "max_days": 110},
    "return_6m": {"target_days": 182, "min_days": 150, "max_days": 210},
    "return_1y": {"target_days": 365, "min_days": 330, "max_days": 400},
}

HIGH_LOW_MIN_DAYS = 180
HIGH_LOW_MIN_OBS = 40
VOL_MIN_OBS = 20
VOL_MIN_DAYS = 30
VOL_MAX_MEDIAN_GAP_DAYS = 2.0


@dataclass(frozen=True)
class PriceObservation:
    as_of: datetime
    price: float
    source: str = SOURCE


@dataclass(frozen=True)
class LocalMomentumFacts:
    values: dict[str, Optional[float]]
    provenance: tuple[FactProvenance, ...]
    observations: int
    unique_prices: int
    span_days: Optional[float]
    source: str = SOURCE
    usable: bool = False
    authority: str = AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": dict(self.values),
            "provenance": [item.to_dict() for item in self.provenance],
            "observations": self.observations,
            "unique_prices": self.unique_prices,
            "span_days": self.span_days,
            "source": self.source,
            "usable": self.usable,
            "authority": self.authority,
        }


def _parse_ts(raw: Any) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _finite_price(raw: Any) -> Optional[float]:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def observations_from_wealth_rows(
    rows: Sequence[Mapping[str, Any]],
    symbol: str,
) -> tuple[PriceObservation, ...]:
    ticker = str(symbol or "").strip().upper()
    items: list[PriceObservation] = []
    for row in rows:
        as_of = _parse_ts(row.get("captured_at") or row.get("snapshot_date"))
        if as_of is None:
            continue
        payload = row.get("valuation_payload") or {}
        for pos in payload.get("priced_positions") or []:
            if str(pos.get("symbol") or "").strip().upper() != ticker:
                continue
            price = _finite_price(pos.get("price"))
            if price is None:
                continue
            items.append(PriceObservation(as_of=as_of, price=price))
            break
    items.sort(key=lambda item: item.as_of)
    collapsed: list[PriceObservation] = []
    for item in items:
        if collapsed and abs(collapsed[-1].price - item.price) < 1e-9:
            continue
        collapsed.append(item)
    return tuple(collapsed)


def _days(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 86400.0


def select_horizon_anchor(
    series: Sequence[PriceObservation],
    *,
    target_days: float,
    min_days: float,
    max_days: float,
) -> Optional[tuple[PriceObservation, PriceObservation]]:
    """Nearest observation to target_days among those inside [min_days, max_days]."""
    if len(series) < 2:
        return None
    end = series[-1]
    candidates = [
        item
        for item in series[:-1]
        if min_days <= _days(end.as_of, item.as_of) <= max_days
    ]
    if not candidates:
        return None
    start = min(candidates, key=lambda item: abs(_days(end.as_of, item.as_of) - target_days))
    if start.price <= 0 or end.price <= 0:
        return None
    return start, end


def _horizon_return(
    series: Sequence[PriceObservation],
    *,
    target_days: float,
    min_days: float,
    max_days: float,
) -> Optional[float]:
    pair = select_horizon_anchor(
        series,
        target_days=target_days,
        min_days=min_days,
        max_days=max_days,
    )
    if pair is None:
        return None
    start, end = pair
    return (end.price / start.price - 1.0) * 100.0


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def compute_local_momentum(
    series: Sequence[PriceObservation],
    *,
    source: str = SOURCE,
    authority: str = AUTHORITY,
    return_normalization: str = "LOCAL_MARK_RETURN",
    extreme_normalization: str = "LOCAL_WINDOW_EXTREME",
    require_unique_prices: bool = True,
) -> LocalMomentumFacts:
    values: dict[str, Optional[float]] = {
        name: None
        for name in (
            *HORIZONS,
            "high_52w",
            "low_52w",
            "drawdown",
            "volatility",
        )
    }
    provenance: list[FactProvenance] = []
    span = _days(series[-1].as_of, series[0].as_of) if len(series) >= 2 else None
    unique_prices = len({round(item.price, 6) for item in series})
    if len(series) < 2 or (require_unique_prices and unique_prices < 2):
        return LocalMomentumFacts(
            values=values,
            provenance=(),
            observations=len(series),
            unique_prices=unique_prices,
            span_days=span,
            source=source,
            usable=False,
            authority=authority,
        )

    end = series[-1]
    for field, spec in HORIZONS.items():
        raw = _horizon_return(
            series,
            target_days=spec["target_days"],
            min_days=spec["min_days"],
            max_days=spec["max_days"],
        )
        if raw is None:
            continue
        values[field] = round(raw, 4)
        provenance.append(
            FactProvenance(
                field=field,
                value=values[field],
                source=source,
                source_as_of=end.as_of.isoformat(),
                unit="percent",
                period_kind=PERIOD_UNKNOWN,
                normalization=return_normalization,
                confidence="MEDIUM",
                authority=authority,
            )
        )

    if span is not None and span >= HIGH_LOW_MIN_DAYS and len(series) >= HIGH_LOW_MIN_OBS:
        high = max(item.price for item in series)
        low = min(item.price for item in series)
        values["high_52w"] = high
        values["low_52w"] = low
        peak = high
        trough_after_peak = end.price
        running_peak = series[0].price
        max_dd = 0.0
        for item in series:
            running_peak = max(running_peak, item.price)
            if running_peak > 0:
                max_dd = max(max_dd, (running_peak - item.price) / running_peak * 100.0)
        values["drawdown"] = round(max_dd, 4)
        for field, value in (
            ("high_52w", high),
            ("low_52w", low),
            ("drawdown", values["drawdown"]),
        ):
            provenance.append(
                FactProvenance(
                    field=field,
                    value=value,
                    source=source,
                    source_as_of=end.as_of.isoformat(),
                    unit="price" if field != "drawdown" else "percent",
                    period_kind=PERIOD_UNKNOWN,
                    normalization=extreme_normalization,
                    confidence="LOW",
                    authority=authority,
                )
            )
        del peak, trough_after_peak

    gaps = [_days(series[idx].as_of, series[idx - 1].as_of) for idx in range(1, len(series))]
    median_gap = _median(gaps)
    if (
        span is not None
        and span >= VOL_MIN_DAYS
        and len(series) >= VOL_MIN_OBS
        and median_gap is not None
        and median_gap <= VOL_MAX_MEDIAN_GAP_DAYS
    ):
        import math

        logs: list[float] = []
        for idx in range(1, len(series)):
            prev = series[idx - 1].price
            curr = series[idx].price
            if prev > 0 and curr > 0:
                logs.append(math.log(curr / prev))
        if len(logs) >= VOL_MIN_OBS - 1:
            mean = sum(logs) / len(logs)
            var = sum((item - mean) ** 2 for item in logs) / len(logs)
            daily = math.sqrt(var)
            values["volatility"] = round(daily * math.sqrt(252.0) * 100.0, 4)
            provenance.append(
                FactProvenance(
                    field="volatility",
                    value=values["volatility"],
                    source=source,
                    source_as_of=end.as_of.isoformat(),
                    unit="percent",
                    period_kind=PERIOD_UNKNOWN,
                    normalization="LOCAL_LOG_RETURN_ANN",
                    confidence="LOW",
                    authority=authority,
                )
            )

    return LocalMomentumFacts(
        values=values,
        provenance=tuple(provenance),
        observations=len(series),
        unique_prices=unique_prices,
        span_days=span,
        source=source,
        usable=any(value is not None for value in values.values()),
        authority=authority,
    )


class LocalMarketHistoryService:
    TABLE = "wealth_portfolio_snapshots"

    def __init__(self, client) -> None:
        self.client = client

    def load_observations(self, symbol: str, *, limit: int = 400) -> tuple[PriceObservation, ...]:
        ticker = str(symbol or "").strip().upper()
        if not ticker or self.client is None:
            return ()
        try:
            rows = (
                self.client.table(self.TABLE)
                .select("captured_at,snapshot_date,valuation_payload")
                .order("captured_at", desc=False)
                .limit(max(1, min(int(limit), 500)))
                .execute()
                .data
            )
        except Exception:
            return ()
        if not isinstance(rows, list):
            return ()
        return observations_from_wealth_rows(rows, ticker)

    def compute(self, symbol: str) -> LocalMomentumFacts:
        return compute_local_momentum(self.load_observations(symbol))
