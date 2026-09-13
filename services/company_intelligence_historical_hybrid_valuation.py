from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.company_intelligence_constants import (
    MIN_HISTORICAL_VALUATION_SAMPLE,
    VALUATION_ABOVE_RANGE_PERCENTILE,
    VALUATION_BELOW_RANGE_PERCENTILE,
    VALUATION_NEAR_MEDIAN_BAND_PCT,
)
from services.company_intelligence_contract import ValuationMetric
from services.company_intelligence_utils import (
    median_value,
    pct_change,
    percentile_rank,
    safe_float,
)

MAX_FISCAL_PRICE_LAG_DAYS = 7
MAX_HISTORICAL_HYBRID_YEARS = 5
HISTORICAL_HYBRID_METHOD = "fiscal_end_price_x_annual_weighted_average_shares"


def _parse_iso_date(value: Any) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _positive(value: Any) -> Optional[float]:
    number = safe_float(value)
    if number is None or number <= 0:
        return None
    return number


def align_price_on_or_before(
    historical_prices: Sequence[Mapping[str, Any]],
    period_end: str,
    *,
    max_lag_days: int = MAX_FISCAL_PRICE_LAG_DAYS,
) -> Tuple[Optional[float], Optional[str], Optional[int]]:
    target = _parse_iso_date(period_end)
    if target is None:
        return None, None, None

    best: Optional[Tuple[date, float]] = None
    for row in historical_prices:
        row_date = _parse_iso_date(row.get("date"))
        price = _positive(row.get("price"))
        if price is None:
            price = _positive(row.get("close"))
        if row_date is None or price is None or row_date > target:
            continue
        lag = (target - row_date).days
        if lag > max_lag_days:
            continue
        if best is None or row_date > best[0]:
            best = (row_date, price)

    if best is None:
        return None, None, None
    lag_days = (target - best[0]).days
    return best[1], best[0].isoformat(), lag_days


def _position(
    current: Optional[float],
    median: Optional[float],
    percentile: Optional[float],
) -> str:
    if current is None or median is None:
        return "INSUFFICIENT_DATA"
    premium = pct_change(current, median)
    if premium is None:
        return "INSUFFICIENT_DATA"
    # Median proximity wins before percentile bands so tied samples do not
    # misclassify an exactly-median current value as below-range.
    if abs(premium) <= VALUATION_NEAR_MEDIAN_BAND_PCT:
        return "NEAR_HISTORICAL_MEDIAN"
    if percentile is not None:
        if percentile <= VALUATION_BELOW_RANGE_PERCENTILE:
            return "BELOW_HISTORICAL_RANGE"
        if percentile >= VALUATION_ABOVE_RANGE_PERCENTILE:
            return "ABOVE_HISTORICAL_RANGE"
    if premium < 0:
        return "BELOW_HISTORICAL_MEDIAN"
    return "ABOVE_HISTORICAL_MEDIAN"


def build_historical_hybrid_samples(
    annual_history: Sequence[Mapping[str, Any]],
    historical_prices: Sequence[Mapping[str, Any]],
) -> dict[str, list[float]]:
    samples: dict[str, list[float]] = {
        "price_to_sales": [],
        "price_to_fcf": [],
    }
    for row in list(annual_history)[:MAX_HISTORICAL_HYBRID_YEARS]:
        period_end = str(row.get("period_end") or "").strip()
        shares = _positive(row.get("weighted_average_shares"))
        if not period_end or shares is None:
            continue
        price, _, _ = align_price_on_or_before(historical_prices, period_end)
        if price is None:
            continue
        market_equity = price * shares

        revenue = _positive(row.get("revenue"))
        if revenue is not None:
            samples["price_to_sales"].append(market_equity / revenue)

        free_cash_flow = _positive(row.get("free_cash_flow"))
        if free_cash_flow is not None:
            samples["price_to_fcf"].append(market_equity / free_cash_flow)

    return samples


def enrich_sec_hybrid_metrics(
    metrics: Sequence[ValuationMetric],
    *,
    annual_history: Sequence[Mapping[str, Any]],
    historical_prices: Sequence[Mapping[str, Any]],
) -> tuple[ValuationMetric, ...]:
    if not annual_history or not historical_prices:
        return tuple(metrics)

    samples = build_historical_hybrid_samples(annual_history, historical_prices)
    enriched: list[ValuationMetric] = []
    historical_limitation = (
        "Tarihsel medyan SEC yıllık finansalları ile mali yıl sonuna en fazla "
        f"{MAX_FISCAL_PRICE_LAG_DAYS} gün geriden hizalanan FMP fiyatlarının hibrit "
        "birleşiminden türetildi; pay adedi SEC yıllık ağırlıklı ortalama pay adedidir."
    )
    corporate_action_limitation = (
        "Eski dönem fiyat/pay eşleşmesi sağlayıcının kurumsal aksiyon düzeltmelerine bağlıdır."
    )

    for metric in metrics:
        if metric.code not in samples:
            if metric.code == "ev_to_ebit":
                limitations = tuple(dict.fromkeys(metric.limitations + (
                    "Tarihsel EV/EBIT medyanı dönemsel borç ve nakit bileşenleri "
                    "ayrıca hizalanmadan hesaplanmaz.",
                )))
                enriched.append(replace(metric, limitations=limitations))
            else:
                enriched.append(metric)
            continue

        history_values = samples[metric.code]
        components = metric.components + (
            ("historical_sample_count", len(history_values)),
            ("historical_method", HISTORICAL_HYBRID_METHOD),
        )
        if len(history_values) < MIN_HISTORICAL_VALUATION_SAMPLE:
            limitations = tuple(dict.fromkeys(metric.limitations + (
                f"Yeterli hizalı tarihsel yıllık hibrit gözlem yok "
                f"(min {MIN_HISTORICAL_VALUATION_SAMPLE}).",
            )))
            enriched.append(replace(metric, limitations=limitations, components=components))
            continue

        median = median_value(history_values)
        percentile = percentile_rank(metric.current_value, history_values)
        premium = pct_change(metric.current_value, median)
        limitations = tuple(dict.fromkeys(metric.limitations + (
            historical_limitation,
            corporate_action_limitation,
        )))
        enriched.append(replace(
            metric,
            historical_median=median,
            premium_to_median_pct=premium,
            position=_position(metric.current_value, median, percentile),
            limitations=limitations,
            components=components,
        ))

    return tuple(enriched)
