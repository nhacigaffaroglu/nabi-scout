from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from services.fund_analysis_contract import (
    LABEL_DRAWDOWN_DEEP,
    LABEL_DRAWDOWN_LIMITED,
    LABEL_DRAWDOWN_MODERATE,
    LABEL_VOLATILITY_HIGH,
    LABEL_VOLATILITY_LOW,
    LABEL_VOLATILITY_MODERATE,
    STALE_OBSERVATION_WARNING,
    FundPerformanceMetrics,
    FundRiskMetrics,
    PricePoint,
    PriceSeries,
)

LOOKBACK_1M_SESSIONS = 21
MIN_1M_CLOSES = 15
MIN_YTD_CLOSES_IN_YEAR = 5
LOOKBACK_1Y_SESSIONS = 252
MIN_1Y_CLOSES = 60
FULL_CONFIDENCE_1Y_CLOSES = 200
MIN_VOLATILITY_RETURNS = 30
MIN_DRAWDOWN_OBSERVATIONS = 30
STALE_CALENDAR_DAYS = 7

TRADING_DAYS_PER_YEAR = 252

FIXED_INCOME_ASSET_PATTERN = re.compile(
    r"\b(bond|fixed[\s-]?income|sukuk|debt|credit|treasury|note)\b",
    re.IGNORECASE,
)


def normalize_price_points(
    symbol: str,
    raw_points: Iterable[Any],
    *,
    source: str = "unknown",
) -> PriceSeries:
    warnings: List[str] = []
    parsed: List[PricePoint] = []

    for raw in raw_points or []:
        if not isinstance(raw, dict):
            continue
        parsed_date = _parse_date(
            raw.get("date")
            or raw.get("timestamp")
            or raw.get("time")
        )
        close = _parse_positive_float(
            raw.get("close")
            or raw.get("price")
            or raw.get("adjClose")
        )
        if parsed_date is None or close is None:
            continue
        volume = _parse_optional_float(raw.get("volume"))
        parsed.append(PricePoint(date=parsed_date, close=close, volume=volume))

    parsed.sort(key=lambda point: point.date)
    deduped = _dedupe_by_date(parsed)
    last_observation = deduped[-1].date if deduped else None

    return PriceSeries(
        symbol=symbol,
        points=tuple(deduped),
        source=source,
        last_observation_date=last_observation,
        warnings=tuple(warnings),
    )


def compute_fund_performance_metrics(
    series: PriceSeries,
    *,
    as_of: Optional[date] = None,
) -> FundPerformanceMetrics:
    as_of = as_of or date.today()
    warnings = list(series.warnings)
    points = series.points

    if not points:
        return FundPerformanceMetrics(
            observation_count=0,
            is_stale=False,
            warnings=tuple(warnings),
        )

    is_stale = _is_stale_last_observation(points[-1].date, as_of)
    if is_stale:
        warnings.append(STALE_OBSERVATION_WARNING)

    return FundPerformanceMetrics(
        return_1m_pct=_price_return_lookback(points, LOOKBACK_1M_SESSIONS, MIN_1M_CLOSES),
        return_ytd_pct=_price_return_ytd(points, as_of),
        return_1y_pct=_price_return_lookback(points, LOOKBACK_1Y_SESSIONS, MIN_1Y_CLOSES),
        observation_count=len(points),
        is_stale=is_stale,
        return_1y_full_confidence=(
            len(points) >= FULL_CONFIDENCE_1Y_CLOSES
            if _price_return_lookback(points, LOOKBACK_1Y_SESSIONS, MIN_1Y_CLOSES) is not None
            else None
        ),
        warnings=tuple(warnings),
    )


def compute_fund_risk_metrics(
    series: PriceSeries,
    *,
    asset_class: Optional[str] = None,
) -> FundRiskMetrics:
    points = series.points
    if len(points) < MIN_DRAWDOWN_OBSERVATIONS:
        return FundRiskMetrics()

    closes = [point.close for point in points]
    volatility = _annualized_volatility(closes)
    drawdown = _max_drawdown(closes)

    suppress_equity_labels = _is_fixed_income_like(asset_class)
    volatility_label = None
    drawdown_label = None

    if volatility is not None and not suppress_equity_labels:
        volatility_label = _volatility_label(volatility)
    if drawdown is not None and not suppress_equity_labels:
        drawdown_label = _drawdown_label(drawdown)

    return FundRiskMetrics(
        annualized_volatility_pct=volatility,
        max_drawdown_pct=drawdown,
        volatility_label=volatility_label,
        drawdown_label=drawdown_label,
    )


def _parse_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_positive_float(value: Any) -> Optional[float]:
    number = _parse_optional_float(value)
    if number is None or number <= 0:
        return None
    return number


def _parse_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_by_date(points: Sequence[PricePoint]) -> List[PricePoint]:
    by_date: dict[date, PricePoint] = {}
    for point in points:
        by_date[point.date] = point
    return [by_date[key] for key in sorted(by_date)]


def _price_return(start: float, end: float) -> float:
    return round(((end / start) - 1.0) * 100.0, 2)


def _price_return_lookback(
    points: Sequence[PricePoint],
    sessions_back: int,
    minimum_closes: int,
) -> Optional[float]:
    if len(points) < minimum_closes:
        return None
    end_idx = len(points) - 1
    start_idx = max(0, end_idx - sessions_back)
    if end_idx - start_idx + 1 < minimum_closes:
        return None
    return _price_return(points[start_idx].close, points[end_idx].close)


def _price_return_ytd(
    points: Sequence[PricePoint],
    as_of: date,
) -> Optional[float]:
    current_year = as_of.year
    in_year = [point for point in points if point.date.year == current_year]
    if len(in_year) < MIN_YTD_CLOSES_IN_YEAR:
        return None

    prior_year_points = [point for point in points if point.date.year < current_year]
    if prior_year_points:
        start_close = prior_year_points[-1].close
    else:
        start_close = in_year[0].close

    end_close = in_year[-1].close
    return _price_return(start_close, end_close)


def _daily_log_returns(closes: Sequence[float]) -> List[float]:
    returns: List[float] = []
    for index in range(1, len(closes)):
        previous = closes[index - 1]
        current = closes[index]
        if previous <= 0 or current <= 0:
            continue
        returns.append(math.log(current / previous))
    return returns


def _annualized_volatility(closes: Sequence[float]) -> Optional[float]:
    log_returns = _daily_log_returns(closes)
    if len(log_returns) < MIN_VOLATILITY_RETURNS:
        return None
    std_dev = _sample_std_dev(log_returns)
    if std_dev is None:
        return None
    return round(std_dev * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0, 2)


def _sample_std_dev(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _max_drawdown(closes: Sequence[float]) -> Optional[float]:
    if len(closes) < MIN_DRAWDOWN_OBSERVATIONS:
        return None
    running_peak = closes[0]
    minimum_drawdown = 0.0
    for close in closes:
        if close > running_peak:
            running_peak = close
        if running_peak <= 0:
            continue
        drawdown = (close / running_peak) - 1.0
        if drawdown < minimum_drawdown:
            minimum_drawdown = drawdown
    return round(minimum_drawdown * 100.0, 2)


def _is_stale_last_observation(last_observation: date, as_of: date) -> bool:
    return (as_of - last_observation).days > STALE_CALENDAR_DAYS


def _is_fixed_income_like(asset_class: Optional[str]) -> bool:
    text = str(asset_class or "").strip()
    if not text:
        return False
    return bool(FIXED_INCOME_ASSET_PATTERN.search(text))


def _volatility_label(volatility_pct: float) -> str:
    if volatility_pct < 12.0:
        return LABEL_VOLATILITY_LOW
    if volatility_pct < 20.0:
        return LABEL_VOLATILITY_MODERATE
    return LABEL_VOLATILITY_HIGH


def _drawdown_label(drawdown_pct: float) -> str:
    if drawdown_pct > -10.0:
        return LABEL_DRAWDOWN_LIMITED
    if drawdown_pct > -25.0:
        return LABEL_DRAWDOWN_MODERATE
    return LABEL_DRAWDOWN_DEEP
