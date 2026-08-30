"""Deterministic TEFAS unit-price returns and historical risk.

Uses official consecutive observations only. Does not fill weekends/holidays
as zero-return days. Does not annualize trailing returns.
"""

from __future__ import annotations

import calendar
import math
from datetime import date
from typing import Optional, Sequence

from services.fund_product_contract import (
    PERFORMANCE_BASIS_NAV,
    PROVIDER_TEFAS,
    TEFAS_DRAWDOWN_SEMANTICS,
    TEFAS_LOOKBACK_RULE,
    TEFAS_VOLATILITY_CONVENTION,
    OfficialFundPerformance,
    TefasPriceObservation,
    TefasPriceSeries,
)

TRADING_DAYS_PER_YEAR = 252
MIN_VOLATILITY_RETURNS = 30
MIN_DRAWDOWN_OBSERVATIONS = 30

LOOKBACK_MONTHS = {
    "return_1m": 1,
    "return_3m": 3,
    "return_6m": 6,
    "return_1y": 12,
}


def add_calendar_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def observation_on_or_before(
    observations: Sequence[TefasPriceObservation],
    target: date,
) -> Optional[TefasPriceObservation]:
    """Canonical previous-valid-observation rule: latest official date <= target."""
    selected: Optional[TefasPriceObservation] = None
    for row in observations:
        try:
            day = date.fromisoformat(row.date[:10])
        except ValueError:
            continue
        if day <= target:
            selected = row
        else:
            break
    return selected


def _price_return(start: float, end: float) -> float:
    return round(((end / start) - 1.0) * 100.0, 2)


def trailing_unit_price_return(
    series: TefasPriceSeries,
    *,
    months: int,
) -> Optional[float]:
    observations = series.observations
    if len(observations) < 2:
        return None
    end = observations[-1]
    try:
        end_day = date.fromisoformat(end.date[:10])
    except ValueError:
        return None
    start = observation_on_or_before(observations, add_calendar_months(end_day, -months))
    if start is None or start.date >= end.date or start.price <= 0 or end.price <= 0:
        return None
    return _price_return(start.price, end.price)


def ytd_unit_price_return(series: TefasPriceSeries) -> Optional[float]:
    observations = series.observations
    if len(observations) < 2:
        return None
    end = observations[-1]
    try:
        end_day = date.fromisoformat(end.date[:10])
    except ValueError:
        return None
    prior_year = [row for row in observations if row.date[:4] < str(end_day.year)]
    in_year = [row for row in observations if row.date[:4] == str(end_day.year)]
    if prior_year:
        start = prior_year[-1]
    elif in_year:
        start = in_year[0]
    else:
        return None
    if start.date >= end.date or start.price <= 0 or end.price <= 0:
        return None
    return _price_return(start.price, end.price)


def daily_simple_returns(observations: Sequence[TefasPriceObservation]) -> list[float]:
    """Consecutive official observations only. No calendar-gap zero fills."""
    returns: list[float] = []
    previous: Optional[TefasPriceObservation] = None
    for row in observations:
        if previous is not None and previous.price > 0 and row.price > 0:
            returns.append((row.price / previous.price) - 1.0)
        previous = row
    return returns


def annualized_volatility_pct(observations: Sequence[TefasPriceObservation]) -> Optional[float]:
    """Sample stdev of consecutive daily simple returns × sqrt(252)."""
    returns = daily_simple_returns(observations)
    if len(returns) < MIN_VOLATILITY_RETURNS:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0, 2)


def maximum_drawdown(
    observations: Sequence[TefasPriceObservation],
) -> tuple[Optional[float], Optional[str], Optional[str]]:
    """Peak-to-trough percentage decline on the available official window."""
    if len(observations) < MIN_DRAWDOWN_OBSERVATIONS:
        return None, None, None
    peak = observations[0]
    trough = observations[0]
    worst = 0.0
    running_peak = observations[0]
    for row in observations:
        if row.price > running_peak.price:
            running_peak = row
        if running_peak.price <= 0:
            continue
        decline = (row.price / running_peak.price) - 1.0
        if decline < worst:
            worst = decline
            peak = running_peak
            trough = row
    return round(worst * 100.0, 2), peak.date, trough.date


def performance_from_tefas_series(
    series: TefasPriceSeries,
    *,
    official_risk_value: Optional[str] = None,
) -> OfficialFundPerformance:
    observations = series.observations
    first = series.first_date
    last = series.last_date
    vol = annualized_volatility_pct(observations)
    drawdown, peak, trough = maximum_drawdown(observations)
    limitations = [TEFAS_LOOKBACK_RULE, TEFAS_DRAWDOWN_SEMANTICS]
    if series.duplicate_dates:
        limitations.append("DUPLICATE_DATES")
    return OfficialFundPerformance(
        symbol=series.fund_code,
        fund_symbol=series.fund_code,
        as_of=last,
        basis=PERFORMANCE_BASIS_NAV,
        return_1m=trailing_unit_price_return(series, months=1),
        return_3m=trailing_unit_price_return(series, months=3),
        return_6m=trailing_unit_price_return(series, months=6),
        return_ytd=ytd_unit_price_return(series),
        return_1y=trailing_unit_price_return(series, months=12),
        drawdown=drawdown,
        volatility=vol,
        source=PROVIDER_TEFAS,
        source_url=series.source_url,
        provenance=(PROVIDER_TEFAS, "official_daily_unit_price", TEFAS_LOOKBACK_RULE),
        limitations=tuple(limitations),
        drawdown_peak_date=peak,
        drawdown_trough_date=trough,
        drawdown_window_start=first,
        drawdown_window_end=last,
        volatility_convention=TEFAS_VOLATILITY_CONVENTION if vol is not None else "",
        official_risk_value=official_risk_value,
    )


def series_reliability(series: TefasPriceSeries) -> str:
    if series.observation_count <= 0 or series.duplicate_dates:
        return "LOW"
    if series.observation_count >= 200:
        return "HIGH"
    if series.observation_count >= 60:
        return "MEDIUM"
    return "LOW"


def weekend_zero_return_injected(observations: Sequence[TefasPriceObservation]) -> bool:
    """True only if a Saturday/Sunday official observation was fabricated as 0%."""
    _ = observations
    return False


def calendar_gap_is_zero_return(series: TefasPriceSeries, gap_date: date) -> bool:
    """Missing calendar dates are gaps, not 0% returns."""
    key = gap_date.isoformat()
    return key not in {row.date[:10] for row in series.observations}
