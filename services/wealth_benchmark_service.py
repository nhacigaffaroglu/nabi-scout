from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from services.fmp_client import FMPError
from services.fund_analysis_contract import PriceSeries
from services.fund_performance_service import normalize_price_points
from services.wealth_timeline_contract import BenchmarkComparisonView, NormalizedSeriesPoint

DEFAULT_BENCHMARK_SYMBOL = "SPY"
ALIGNMENT_LOOKBACK_DAYS = 14
# Deterministic US equity EOD cutoff approximation (4pm ET standard time).
US_EQUITY_EOD_CUTOFF_UTC_HOUR = 21


def _parse_snapshot_datetime(captured_at: str) -> Optional[datetime]:
    normalized = str(captured_at or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def alignment_cutoff_date(captured_at: datetime) -> date:
    """Last calendar date whose US EOD close is knowable at snapshot time."""
    utc = captured_at.astimezone(timezone.utc)
    if utc.hour >= US_EQUITY_EOD_CUTOFF_UTC_HOUR:
        return utc.date()
    return utc.date() - timedelta(days=1)


def align_price_on_or_before(series: PriceSeries, target: date) -> Optional[float]:
    """Deterministic alignment: last EOD close on or before target date."""
    selected: Optional[float] = None
    for point in series.points:
        if point.date <= target:
            selected = point.close
        else:
            break
    return selected


def align_price_for_snapshot(series: PriceSeries, captured_at: str) -> Optional[float]:
    parsed = _parse_snapshot_datetime(captured_at)
    if parsed is None:
        return None
    cutoff = alignment_cutoff_date(parsed)
    return align_price_on_or_before(series, cutoff)


class WealthBenchmarkService:
    """Read-only benchmark boundary for Wealth performance comparison."""

    def __init__(self, fmp_client=None) -> None:
        self._fmp = fmp_client
        self._range_cache: Dict[Tuple[str, str, str], PriceSeries] = {}
        self._fetch_count = 0

    @property
    def fetch_count(self) -> int:
        return self._fetch_count

    def fetch_historical_range(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> PriceSeries:
        from_iso = from_date.isoformat()
        to_iso = to_date.isoformat()
        cache_key = (symbol, from_iso, to_iso)
        cached = self._range_cache.get(cache_key)
        if cached is not None:
            return cached

        if self._fmp is None:
            empty = PriceSeries(
                symbol=symbol,
                points=tuple(),
                source="none",
                last_observation_date=None,
                warnings=("benchmark_provider_unavailable",),
            )
            self._range_cache[cache_key] = empty
            return empty

        try:
            rows = self._fmp.historical_price_eod_light(symbol, from_iso, to_iso)
            self._fetch_count += 1
        except FMPError as exc:
            empty = PriceSeries(
                symbol=symbol,
                points=tuple(),
                source="fmp",
                last_observation_date=None,
                warnings=(str(exc),),
            )
            self._range_cache[cache_key] = empty
            return empty

        series = normalize_price_points(symbol, rows, source="fmp")
        self._range_cache[cache_key] = series
        return series

    def build_spy_comparison(
        self,
        *,
        snapshot_dates: List[str],
        portfolio_index_series: List[Tuple[str, Optional[float]]],
        portfolio_return_pct: Optional[float],
        performance_comparable: bool,
        base_currency: str,
    ) -> BenchmarkComparisonView:
        warnings: List[str] = []
        symbol = DEFAULT_BENCHMARK_SYMBOL

        if base_currency.strip().upper() != "USD":
            return BenchmarkComparisonView(
                benchmark_symbol=symbol,
                portfolio_normalized=[],
                portfolio_return_pct=portfolio_return_pct,
                benchmark_return_pct=None,
                relative_return_pct=None,
                performance_comparable=False,
                warnings=["Benchmark comparison requires USD base currency."],
                provider_fetch_count=self._fetch_count,
            )

        if not performance_comparable:
            return BenchmarkComparisonView(
                benchmark_symbol=symbol,
                portfolio_normalized=[],
                portfolio_return_pct=portfolio_return_pct,
                benchmark_return_pct=None,
                relative_return_pct=None,
                performance_comparable=False,
                warnings=["Portfolio performance is not comparable."],
                provider_fetch_count=self._fetch_count,
            )

        parsed_dates = [_parse_snapshot_datetime(value) for value in snapshot_dates]
        if any(value is None for value in parsed_dates):
            return BenchmarkComparisonView(
                benchmark_symbol=symbol,
                portfolio_normalized=[],
                portfolio_return_pct=portfolio_return_pct,
                benchmark_return_pct=None,
                relative_return_pct=None,
                performance_comparable=False,
                warnings=["Invalid snapshot timestamp in comparison range."],
                provider_fetch_count=self._fetch_count,
            )

        cutoff_dates = [
            alignment_cutoff_date(value)
            for value in parsed_dates
            if value is not None
        ]
        fetch_from = min(cutoff_dates) - timedelta(days=ALIGNMENT_LOOKBACK_DAYS)
        fetch_to = max(cutoff_dates)
        price_series = self.fetch_historical_range(symbol, fetch_from, fetch_to)

        if not price_series.points:
            warning = (
                price_series.warnings[0]
                if price_series.warnings
                else "Benchmark historical prices unavailable."
            )
            return BenchmarkComparisonView(
                benchmark_symbol=symbol,
                portfolio_normalized=[],
                portfolio_return_pct=portfolio_return_pct,
                benchmark_return_pct=None,
                relative_return_pct=None,
                performance_comparable=False,
                warnings=[warning],
                provider_fetch_count=self._fetch_count,
            )

        aligned_prices: List[Optional[float]] = []
        for captured_at in snapshot_dates:
            aligned_prices.append(align_price_for_snapshot(price_series, captured_at))

        if any(price is None for price in aligned_prices):
            return BenchmarkComparisonView(
                benchmark_symbol=symbol,
                portfolio_normalized=[],
                portfolio_return_pct=portfolio_return_pct,
                benchmark_return_pct=None,
                relative_return_pct=None,
                performance_comparable=False,
                warnings=["Missing benchmark price for one or more snapshot dates."],
                provider_fetch_count=self._fetch_count,
            )

        first_price = aligned_prices[0]
        if first_price is None or first_price <= 0:
            return BenchmarkComparisonView(
                benchmark_symbol=symbol,
                portfolio_normalized=[],
                portfolio_return_pct=portfolio_return_pct,
                benchmark_return_pct=None,
                relative_return_pct=None,
                performance_comparable=False,
                warnings=["Benchmark base price is missing or invalid."],
                provider_fetch_count=self._fetch_count,
            )

        portfolio_by_date = {label: index for label, index in portfolio_index_series}
        normalized_points: List[NormalizedSeriesPoint] = []
        for captured_at, benchmark_price in zip(snapshot_dates, aligned_prices):
            assert benchmark_price is not None
            normalized_points.append(
                NormalizedSeriesPoint(
                    label_date=captured_at,
                    portfolio_index=portfolio_by_date.get(captured_at),
                    benchmark_index=100.0 * benchmark_price / first_price,
                )
            )

        last_benchmark = aligned_prices[-1]
        assert last_benchmark is not None
        benchmark_return_pct = ((last_benchmark / first_price) - 1.0) * 100.0

        relative_return_pct: Optional[float] = None
        if portfolio_return_pct is not None:
            relative_return_pct = portfolio_return_pct - benchmark_return_pct

        return BenchmarkComparisonView(
            benchmark_symbol=symbol,
            portfolio_normalized=normalized_points,
            portfolio_return_pct=portfolio_return_pct,
            benchmark_return_pct=benchmark_return_pct,
            relative_return_pct=relative_return_pct,
            performance_comparable=True,
            warnings=warnings,
            provider_fetch_count=self._fetch_count,
        )
