from __future__ import annotations

from typing import Any, List, Mapping, Optional, Tuple

from services.company_intelligence_contract import (
    IntelligenceObservation,
    IntelligenceProvenance,
    ValuationMetric,
    ValuationSection,
)
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_utils import safe_float
from services.company_intelligence_valuation_alignment import (
    alignment_allows_hybrid_valuation,
    assess_sec_market_hybrid_alignment,
    safe_positive_ratio,
)

SEC_PROVIDER_NAME = "sec"
FMP_PROVIDER_NAME = "fmp"
SEC_HYBRID_VALUATION_FAMILY = "sec_annual_market_hybrid"


def sec_hybrid_valuation_inputs_available(sec_financials: Mapping[str, Any]) -> bool:
    if not sec_financials:
        return False
    return sec_financials.get("financial_period_end") not in (None, "")


def _hybrid_metric(
    *,
    code: str,
    label: str,
    value: Optional[float],
    alignment,
    components: Tuple[Tuple[str, Any], ...],
    extra_limitations: Tuple[str, ...] = (),
) -> Optional[ValuationMetric]:
    if value is None:
        return None
    limitations = alignment.limitations + extra_limitations
    return ValuationMetric(
        code=code,
        label=label,
        current_value=value,
        historical_median=None,
        premium_to_median_pct=None,
        position="INSUFFICIENT_DATA",
        meaningful=True,
        limitations=limitations,
        source_provider=f"{SEC_PROVIDER_NAME}+{FMP_PROVIDER_NAME}",
        data_family=SEC_HYBRID_VALUATION_FAMILY,
        fundamental_period_end=alignment.fundamental_period_end,
        market_data_as_of=alignment.market_data_as_of,
        alignment_status=alignment.status,
        confidence=alignment.confidence,
        components=components,
    )


def build_sec_hybrid_valuation(
    bundle: CompanyProviderBundle,
) -> Optional[ValuationSection]:
    sec_financials = bundle.sec_financials or {}
    if not sec_hybrid_valuation_inputs_available(sec_financials):
        return None

    profile = bundle.profile or {}
    market_cap = safe_float(profile.get("marketCap") or profile.get("mktCap"))
    alignment = assess_sec_market_hybrid_alignment(
        sec_financials,
        market_cap=market_cap,
        retrieved_at=bundle.retrieved_at,
    )
    if not alignment_allows_hybrid_valuation(alignment):
        return None

    revenue = safe_float(sec_financials.get("revenue"))
    free_cash_flow = safe_float(sec_financials.get("free_cash_flow"))
    operating_income = safe_float(sec_financials.get("operating_income"))
    total_debt = sec_financials.get("total_debt")
    cash = sec_financials.get("cash")

    metrics: List[ValuationMetric] = []

    ps = safe_positive_ratio(market_cap, revenue)
    if ps is not None:
        metric = _hybrid_metric(
            code="price_to_sales",
            label="Fiyat/Satış (yıllık hibrit)",
            value=ps,
            alignment=alignment,
            components=(
                ("market_cap", market_cap),
                ("revenue", revenue),
                ("formula", "market_cap / revenue"),
            ),
        )
        if metric is not None:
            metrics.append(metric)

    pfcf = safe_positive_ratio(market_cap, free_cash_flow)
    if pfcf is not None:
        metric = _hybrid_metric(
            code="price_to_fcf",
            label="Fiyat/FCF (yıllık hibrit)",
            value=pfcf,
            alignment=alignment,
            components=(
                ("market_cap", market_cap),
                ("free_cash_flow", free_cash_flow),
                ("formula", "market_cap / free_cash_flow"),
            ),
        )
        if metric is not None:
            metrics.append(metric)

    if alignment.ev_components_period_aligned:
        debt_value = safe_float(total_debt)
        cash_value = safe_float(cash)
        if debt_value is not None and cash_value is not None and operating_income is not None:
            if operating_income > 0:
                enterprise_value = market_cap + debt_value - cash_value
                ev_ebit = safe_positive_ratio(enterprise_value, operating_income)
                if ev_ebit is not None:
                    metric = _hybrid_metric(
                        code="ev_to_ebit",
                        label="EV/EBIT (yıllık hibrit)",
                        value=ev_ebit,
                        alignment=alignment,
                        components=(
                            ("market_cap", market_cap),
                            ("total_debt", debt_value),
                            ("cash", cash_value),
                            ("enterprise_value", enterprise_value),
                            ("operating_income", operating_income),
                            ("formula", "(market_cap + total_debt - cash) / operating_income"),
                        ),
                    )
                    if metric is not None:
                        metrics.append(metric)
    elif total_debt is not None or cash is not None:
        pass  # EV metrics omitted when balance sheet period mismatches income period

    if not metrics:
        return None

    observations = [
        IntelligenceObservation(
            code="VALUATION_HYBRID_ANNUAL_MARKET",
            status="FACT",
            statement=(
                "Değerleme oranları SEC yıllık finansallar ile güncel piyasa değerinin "
                "hibrit birleşiminden türetildi; tarihsel medyan karşılaştırması yok."
            ),
            metric="valuation_hybrid",
            source=f"{SEC_PROVIDER_NAME}+{FMP_PROVIDER_NAME}",
            confidence=alignment.confidence,
            period=alignment.fundamental_period_end,
            limitations=alignment.limitations,
        )
    ]

    return ValuationSection(
        metrics=tuple(metrics),
        observations=tuple(observations),
        provenance=IntelligenceProvenance(
            provider=f"{SEC_PROVIDER_NAME}+{FMP_PROVIDER_NAME}",
            data_family=SEC_HYBRID_VALUATION_FAMILY,
            source_period=alignment.fundamental_period_end,
            retrieved_at=bundle.retrieved_at,
        ),
    )
