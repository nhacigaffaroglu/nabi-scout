from __future__ import annotations

from typing import List, Optional, Tuple

from services.company_intelligence_constants import (
    MIN_HISTORICAL_VALUATION_SAMPLE,
    PROVIDER_NAME,
    VALUATION_ABOVE_RANGE_PERCENTILE,
    VALUATION_BELOW_RANGE_PERCENTILE,
    VALUATION_NEAR_MEDIAN_BAND_PCT,
)
from services.company_intelligence_contract import (
    IntelligenceObservation,
    IntelligenceProvenance,
    ValuationMetric,
    ValuationSection,
)
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_utils import median_value, pct_change, safe_float

_FMP_VALUATION_RATIO_KEYS = (
    "priceToEarningsRatioTTM",
    "priceToSalesRatioTTM",
    "priceToBookRatioTTM",
    "dividendYieldTTM",
)
_FMP_KEY_METRIC_VALUATION_KEYS = (
    "enterpriseValueOverEBITDATTM",
    "freeCashFlowYieldTTM",
    "earningsYieldTTM",
)


def fmp_bundle_has_usable_valuation_ratios(bundle: CompanyProviderBundle) -> bool:
    ratios = bundle.ratios_ttm or {}
    metrics = bundle.key_metrics_ttm or {}
    for key in _FMP_VALUATION_RATIO_KEYS:
        if safe_float(ratios.get(key)) is not None:
            return True
    for key in _FMP_KEY_METRIC_VALUATION_KEYS:
        if safe_float(metrics.get(key)) is not None:
            return True
    return False


def valuation_section_has_meaningful_metrics(
    section: Optional[ValuationSection],
) -> bool:
    if section is None:
        return False
    return any(
        metric.meaningful and metric.current_value is not None
        for metric in section.metrics
    )


def _valuation_position(
    current: Optional[float],
    median: Optional[float],
    percentile: Optional[float],
) -> str:
    if current is None or median is None:
        return "INSUFFICIENT_DATA"
    if percentile is not None:
        if percentile <= VALUATION_BELOW_RANGE_PERCENTILE:
            return "BELOW_HISTORICAL_RANGE"
        if percentile >= VALUATION_ABOVE_RANGE_PERCENTILE:
            return "ABOVE_HISTORICAL_RANGE"
    premium = pct_change(current, median)
    if premium is None:
        return "INSUFFICIENT_DATA"
    if abs(premium) <= VALUATION_NEAR_MEDIAN_BAND_PCT:
        return "NEAR_HISTORICAL_MEDIAN"
    if premium < 0:
        return "BELOW_HISTORICAL_MEDIAN"
    return "ABOVE_HISTORICAL_MEDIAN"


def _clean_history_values(
    history_rows: List[dict],
    history_key: str,
    *,
    positive_only: bool = False,
) -> List[float]:
    values: List[float] = []
    for row in history_rows:
        value = safe_float(row.get(history_key))
        if value is None:
            continue
        if positive_only and value <= 0:
            continue
        values.append(value)
    return values


def _historical_metric(
    *,
    code: str,
    label: str,
    current: Optional[float],
    history_rows: List[dict],
    history_key: str,
    meaningful: bool = True,
    positive_only: bool = False,
) -> ValuationMetric:
    history_values = _clean_history_values(
        history_rows,
        history_key,
        positive_only=positive_only,
    )
    median = median_value(history_values) if len(history_values) >= MIN_HISTORICAL_VALUATION_SAMPLE else None
    premium = pct_change(current, median) if current is not None and median is not None else None
    from services.company_intelligence_utils import percentile_rank

    percentile = (
        percentile_rank(current, history_values)
        if len(history_values) >= MIN_HISTORICAL_VALUATION_SAMPLE
        else None
    )
    limitations: Tuple[str, ...] = ()
    if len(history_values) < MIN_HISTORICAL_VALUATION_SAMPLE:
        limitations = (
            f"Yeterli tarihsel gözlem yok (min {MIN_HISTORICAL_VALUATION_SAMPLE}).",
        )
    return ValuationMetric(
        code=code,
        label=label,
        current_value=current,
        historical_median=median,
        premium_to_median_pct=premium,
        position=_valuation_position(current, median, percentile),
        meaningful=meaningful,
        limitations=limitations,
    )


def build_valuation_intelligence(bundle: CompanyProviderBundle) -> ValuationSection:
    quote = bundle.quote or {}
    ratios_ttm = bundle.ratios_ttm or {}
    key_metrics_ttm = bundle.key_metrics_ttm or {}

    pe = safe_float(ratios_ttm.get("priceToEarningsRatioTTM"))
    if pe is not None and pe < 0:
        pe = None
    forward_pe = safe_float(ratios_ttm.get("priceToEarningsRatioTTM"))
    ps = safe_float(ratios_ttm.get("priceToSalesRatioTTM"))
    pb = safe_float(ratios_ttm.get("priceToBookRatioTTM"))
    ev_ebitda = safe_float(key_metrics_ttm.get("enterpriseValueOverEBITDATTM"))
    fcf_yield = safe_float(key_metrics_ttm.get("freeCashFlowYieldTTM"))
    earnings_yield = safe_float(key_metrics_ttm.get("earningsYieldTTM"))
    dividend_yield = safe_float(ratios_ttm.get("dividendYieldTTM"))

    metrics = (
        _historical_metric(
            code="pe_ratio",
            label="F/K (TTM)",
            current=pe,
            history_rows=bundle.ratios_history,
            history_key="priceToEarningsRatio",
            meaningful=pe is not None,
            positive_only=True,
        ),
        _historical_metric(
            code="price_to_sales",
            label="Fiyat/Satış",
            current=ps,
            history_rows=bundle.ratios_history,
            history_key="priceToSalesRatio",
            meaningful=ps is not None,
        ),
        _historical_metric(
            code="ev_to_ebitda",
            label="EV/EBITDA",
            current=ev_ebitda,
            history_rows=bundle.key_metrics_history,
            history_key="enterpriseValueOverEBITDA",
            meaningful=ev_ebitda is not None,
        ),
        ValuationMetric(
            code="fcf_yield",
            label="FCF Verimi",
            current_value=fcf_yield,
            historical_median=median_value(
                [safe_float(row.get("freeCashFlowYield")) for row in bundle.key_metrics_history]
            ),
            premium_to_median_pct=None,
            position="INSUFFICIENT_DATA",
            meaningful=fcf_yield is not None,
        ),
        ValuationMetric(
            code="earnings_yield",
            label="Kazanç Verimi",
            current_value=earnings_yield,
            historical_median=None,
            premium_to_median_pct=None,
            position="INSUFFICIENT_DATA",
            meaningful=earnings_yield is not None,
        ),
        ValuationMetric(
            code="dividend_yield",
            label="Temettü Verimi",
            current_value=dividend_yield,
            historical_median=None,
            premium_to_median_pct=None,
            position="INSUFFICIENT_DATA",
            meaningful=dividend_yield is not None,
        ),
    )

    observations: List[IntelligenceObservation] = []
    pe_metric = metrics[0]
    if pe_metric.current_value is not None and pe_metric.position not in {"INSUFFICIENT_DATA"}:
        observations.append(
            IntelligenceObservation(
                code="VALUATION_HISTORICAL_CONTEXT",
                status="FACT",
                statement="F/K çarpanı tarihsel bağlamda değerlendirildi.",
                metric="pe_ratio",
                value=pe_metric.current_value,
                comparison_value=pe_metric.historical_median,
                evidence=(
                    ("position", pe_metric.position),
                    ("premium_to_median_pct", pe_metric.premium_to_median_pct),
                ),
                source=PROVIDER_NAME,
                confidence="MEDIUM",
                limitations=("Değerleme yüksek/düşük yorumu yatırım tavsiyesi değildir.",),
            )
        )

    return ValuationSection(
        metrics=tuple(metrics),
        observations=tuple(observations),
        provenance=IntelligenceProvenance(
            provider=PROVIDER_NAME,
            data_family="valuation_ratios",
            retrieved_at=bundle.retrieved_at,
        ),
    )
