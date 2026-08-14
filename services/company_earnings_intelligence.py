from __future__ import annotations

from typing import List, Optional, Tuple

from services.company_intelligence_constants import (
    ACCELERATION_DELTA_PP,
    MATERIAL_YOY_CHANGE_PCT,
    MARGIN_CHANGE_PP,
    PROVIDER_NAME,
)
from services.company_intelligence_contract import (
    EarningsExpectations,
    EarningsSection,
    IntelligenceObservation,
    IntelligenceProvenance,
)
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_utils import (
    find_matching_statement_row,
    find_yoy_pair,
    fiscal_period_key,
    pct_change,
    safe_float,
)
from services.company_financial_trend_engine import _margin, _period_label


def _build_expectations(bundle: CompanyProviderBundle) -> EarningsExpectations:
    if not bundle.earnings_surprises:
        limitation = "Beklenti/sürpriz verisi sağlayıcıdan alınamadı."
        if any(failure.startswith("earnings_surprises:plan_restricted") for failure in bundle.failures):
            limitation = "Beklenti/sürpriz verisi mevcut abonelik planında kullanılamıyor."
        return EarningsExpectations(
            expectations_available=False,
            limitations=(limitation,),
        )
    latest = bundle.earnings_surprises[0]
    revenue_actual = safe_float(latest.get("actualRevenue") or latest.get("revenue"))
    revenue_estimate = safe_float(latest.get("estimatedRevenue") or latest.get("revenueEstimated"))
    eps_actual = safe_float(latest.get("actualEarningResult") or latest.get("actualEps") or latest.get("eps"))
    eps_estimate = safe_float(
        latest.get("estimatedEarning") or latest.get("estimatedEps") or latest.get("epsEstimated")
    )
    return EarningsExpectations(
        expectations_available=True,
        revenue_actual=revenue_actual,
        revenue_estimate=revenue_estimate,
        revenue_surprise_pct=pct_change(revenue_actual, revenue_estimate),
        eps_actual=eps_actual,
        eps_estimate=eps_estimate,
        eps_surprise_pct=pct_change(eps_actual, eps_estimate),
        limitations=(),
    )


def _prior_yoy_revenue_change(rows: List[dict]) -> Optional[float]:
    if len(rows) < 3:
        return None
    current, previous = find_yoy_pair(rows[1:])
    if current is None or previous is None:
        return None
    return pct_change(
        safe_float(current.get("revenue")),
        safe_float(previous.get("revenue")),
    )


def build_earnings_intelligence(bundle: CompanyProviderBundle) -> EarningsSection:
    income_latest, income_prev = find_yoy_pair(bundle.income_quarterly)
    cash_latest = find_matching_statement_row(bundle.cashflow_quarterly, income_latest)
    cash_prev = find_matching_statement_row(bundle.cashflow_quarterly, income_prev)
    period = _period_label(income_latest or {})

    revenue_latest = safe_float((income_latest or {}).get("revenue"))
    revenue_prev = safe_float((income_prev or {}).get("revenue"))
    eps_latest = safe_float((income_latest or {}).get("epsdiluted") or (income_latest or {}).get("eps"))
    eps_prev = safe_float((income_prev or {}).get("epsdiluted") or (income_prev or {}).get("eps"))

    gross_latest = _margin(
        safe_float((income_latest or {}).get("grossProfit")),
        revenue_latest,
    )
    gross_prev = _margin(
        safe_float((income_prev or {}).get("grossProfit")),
        revenue_prev,
    )
    op_margin_latest = _margin(
        safe_float((income_latest or {}).get("operatingIncome")),
        revenue_latest,
    )
    op_margin_prev = _margin(
        safe_float((income_prev or {}).get("operatingIncome")),
        revenue_prev,
    )

    fcf_latest = safe_float((cash_latest or {}).get("freeCashFlow"))
    fcf_prev = safe_float((cash_prev or {}).get("freeCashFlow"))
    capex_latest = safe_float((cash_latest or {}).get("capitalExpenditure"))
    capex_prev = safe_float((cash_prev or {}).get("capitalExpenditure"))
    if capex_latest is not None:
        capex_latest = abs(capex_latest)
    if capex_prev is not None:
        capex_prev = abs(capex_prev)
    if fcf_latest is None and cash_latest:
        ocf = safe_float(cash_latest.get("operatingCashFlow"))
        if ocf is not None and capex_latest is not None:
            fcf_latest = ocf - capex_latest
    if fcf_prev is None and cash_prev:
        ocf = safe_float(cash_prev.get("operatingCashFlow"))
        if ocf is not None and capex_prev is not None:
            fcf_prev = ocf - capex_prev

    observations: List[IntelligenceObservation] = []
    revenue_yoy = pct_change(revenue_latest, revenue_prev)
    eps_yoy = pct_change(eps_latest, eps_prev)

    if revenue_yoy is not None and abs(revenue_yoy) >= MATERIAL_YOY_CHANGE_PCT:
        prior_yoy = _prior_yoy_revenue_change(bundle.income_quarterly)
        code = "REVENUE_YOY_CHANGE"
        if prior_yoy is not None and revenue_yoy - prior_yoy >= ACCELERATION_DELTA_PP:
            code = "REVENUE_ACCELERATION"
        elif prior_yoy is not None and prior_yoy - revenue_yoy >= ACCELERATION_DELTA_PP:
            code = "REVENUE_DECELERATION"
        observations.append(
            IntelligenceObservation(
                code=code,
                status="FACT",
                statement="Gelir yıldan yıla karşılaştırılabilir dönemde değişim gösteriyor.",
                metric="revenue",
                value=revenue_latest,
                comparison_value=revenue_prev,
                evidence=(("revenue_yoy_pct", revenue_yoy), ("comparison_type", "YoY")),
                source=PROVIDER_NAME,
                confidence="HIGH",
                period=period,
            )
        )

    if eps_yoy is not None and abs(eps_yoy) >= MATERIAL_YOY_CHANGE_PCT:
        observations.append(
            IntelligenceObservation(
                code="EPS_YOY_CHANGE",
                status="FACT",
                statement="EPS yıldan yıla karşılaştırılabilir dönemde değişim gösteriyor.",
                metric="eps",
                value=eps_latest,
                comparison_value=eps_prev,
                evidence=(("eps_yoy_pct", eps_yoy), ("comparison_type", "YoY")),
                source=PROVIDER_NAME,
                confidence="HIGH",
                period=period,
            )
        )

    if gross_latest is not None and gross_prev is not None:
        delta = gross_latest - gross_prev
        if abs(delta) >= MARGIN_CHANGE_PP:
            observations.append(
                IntelligenceObservation(
                    code=(
                        "GROSS_MARGIN_EXPANSION"
                        if delta > 0
                        else "GROSS_MARGIN_COMPRESSION"
                    ),
                    status="FACT",
                    statement="Brüt marj yıldan yıla değişim gösteriyor.",
                    metric="gross_margin",
                    value=gross_latest,
                    comparison_value=gross_prev,
                    evidence=(("delta_pp", delta), ("comparison_type", "YoY")),
                    source=PROVIDER_NAME,
                    confidence="HIGH",
                    period=period,
                )
            )

    if op_margin_latest is not None and op_margin_prev is not None:
        delta = op_margin_latest - op_margin_prev
        if abs(delta) >= MARGIN_CHANGE_PP:
            observations.append(
                IntelligenceObservation(
                    code=(
                        "OPERATING_MARGIN_EXPANSION"
                        if delta > 0
                        else "OPERATING_MARGIN_COMPRESSION"
                    ),
                    status="FACT",
                    statement="Faaliyet marjı yıldan yıla değişim gösteriyor.",
                    metric="operating_margin",
                    value=op_margin_latest,
                    comparison_value=op_margin_prev,
                    evidence=(("delta_pp", delta), ("comparison_type", "YoY")),
                    source=PROVIDER_NAME,
                    confidence="HIGH",
                    period=period,
                )
            )

    if fcf_latest is not None and fcf_prev is not None and fcf_latest != fcf_prev:
        observations.append(
            IntelligenceObservation(
                code="FCF_CHANGE" if fcf_latest > fcf_prev else "FCF_DETERIORATION",
                status="FACT",
                statement="Serbest nakit akışı yıldan yıla değişim gösteriyor.",
                metric="free_cash_flow",
                value=fcf_latest,
                comparison_value=fcf_prev,
                evidence=(("comparison_type", "YoY"),),
                source=PROVIDER_NAME,
                confidence="MEDIUM",
                period=period,
            )
        )

    if capex_latest is not None and capex_prev is not None and capex_latest > capex_prev * 1.1:
        observations.append(
            IntelligenceObservation(
                code="CAPEX_ACCELERATION",
                status="FACT",
                statement="Sermaye harcaması önceki yıl dönemine göre arttı.",
                metric="capex",
                value=capex_latest,
                comparison_value=capex_prev,
                evidence=(("comparison_type", "YoY"),),
                source=PROVIDER_NAME,
                confidence="MEDIUM",
                period=period,
            )
        )

    if (
        income_latest is not None
        and income_prev is not None
        and fiscal_period_key(income_latest) is not None
        and not observations
    ):
        observations.append(
            IntelligenceObservation(
                code="REPORTED_EARNINGS_SNAPSHOT",
                status="FACT",
                statement=(
                    "Raporlanan gelir ve EPS karşılaştırılabilir önceki yıl dönemiyle "
                    "eşleştirildi; materyal değişim eşiği aşılmadı."
                ),
                metric="revenue",
                value=revenue_latest,
                comparison_value=revenue_prev,
                evidence=(
                    ("revenue_yoy_pct", revenue_yoy),
                    ("eps_yoy_pct", eps_yoy),
                    ("comparison_type", "YoY"),
                ),
                source=PROVIDER_NAME,
                confidence="MEDIUM",
                period=period,
            )
        )

    return EarningsSection(
        period=period,
        comparison_type="YoY",
        observations=tuple(observations),
        expectations=_build_expectations(bundle),
        provenance=IntelligenceProvenance(
            provider=PROVIDER_NAME,
            data_family="earnings_quarterly",
            source_period=period,
            retrieved_at=bundle.retrieved_at,
        ),
    )
