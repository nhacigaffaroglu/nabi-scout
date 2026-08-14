from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from services.company_intelligence_constants import (
    MATERIAL_YOY_CHANGE_PCT,
    MARGIN_CHANGE_PP,
    PROVIDER_NAME,
)
from services.company_intelligence_contract import (
    FinancialTrendsSection,
    IntelligenceObservation,
    IntelligenceProvenance,
    MetricTrendPoint,
)
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_utils import direction_from_change, pct_change, safe_float


def _period_label(row: Dict[str, Any]) -> Optional[str]:
    return row.get("period") or row.get("date") or row.get("calendarYear")


def _find_yoy_pair(rows: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if len(rows) < 2:
        return None, None
    latest = rows[0]
    latest_period = _period_label(latest)
    if not latest_period:
        return latest, rows[1] if len(rows) > 1 else None
    for row in rows[1:]:
        if _period_label(row) and _period_label(row) != latest_period:
            return latest, row
    return latest, rows[1] if len(rows) > 1 else None


def _margin(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return (numerator / denominator) * 100.0


def _trend_point(
    metric: str,
    latest_value: Optional[float],
    previous_value: Optional[float],
    *,
    period: Optional[str],
    higher_is_better: bool = True,
    limitations: Tuple[str, ...] = (),
) -> MetricTrendPoint:
    absolute_change = None
    if latest_value is not None and previous_value is not None:
        absolute_change = latest_value - previous_value
    change_pct = pct_change(latest_value, previous_value)
    return MetricTrendPoint(
        metric=metric,
        latest_value=latest_value,
        previous_value=previous_value,
        absolute_change=absolute_change,
        pct_change=change_pct,
        direction=direction_from_change(change_pct, higher_is_better=higher_is_better),
        period=period,
        limitations=limitations,
    )


def build_financial_trends(bundle: CompanyProviderBundle) -> FinancialTrendsSection:
    income_latest, income_prev = _find_yoy_pair(bundle.income_quarterly)
    balance_latest = bundle.balance_quarterly[0] if bundle.balance_quarterly else {}
    balance_prev = bundle.balance_quarterly[1] if len(bundle.balance_quarterly) > 1 else {}
    cash_latest = bundle.cashflow_quarterly[0] if bundle.cashflow_quarterly else {}
    cash_prev = bundle.cashflow_quarterly[1] if len(bundle.cashflow_quarterly) > 1 else {}

    period = _period_label(income_latest or {})
    revenue_latest = safe_float((income_latest or {}).get("revenue"))
    revenue_prev = safe_float((income_prev or {}).get("revenue"))
    eps_latest = safe_float((income_latest or {}).get("epsdiluted") or (income_latest or {}).get("eps"))
    eps_prev = safe_float((income_prev or {}).get("epsdiluted") or (income_prev or {}).get("eps"))
    op_latest = safe_float((income_latest or {}).get("operatingIncome"))
    op_prev = safe_float((income_prev or {}).get("operatingIncome"))
    ni_latest = safe_float((income_latest or {}).get("netIncome"))
    ni_prev = safe_float((income_prev or {}).get("netIncome"))

    gross_latest = _margin(
        safe_float((income_latest or {}).get("grossProfit")),
        revenue_latest,
    )
    gross_prev = _margin(
        safe_float((income_prev or {}).get("grossProfit")),
        revenue_prev,
    )
    op_margin_latest = _margin(op_latest, revenue_latest)
    op_margin_prev = _margin(op_prev, revenue_prev)
    net_margin_latest = _margin(ni_latest, revenue_latest)
    net_margin_prev = _margin(ni_prev, revenue_prev)

    ocf_latest = safe_float((cash_latest or {}).get("operatingCashFlow"))
    ocf_prev = safe_float((cash_prev or {}).get("operatingCashFlow"))
    capex_latest = safe_float((cash_latest or {}).get("capitalExpenditure"))
    capex_prev = safe_float((cash_prev or {}).get("capitalExpenditure"))
    if capex_latest is not None:
        capex_latest = abs(capex_latest)
    if capex_prev is not None:
        capex_prev = abs(capex_prev)
    fcf_latest = safe_float((cash_latest or {}).get("freeCashFlow"))
    fcf_prev = safe_float((cash_prev or {}).get("freeCashFlow"))
    if fcf_latest is None and ocf_latest is not None and capex_latest is not None:
        fcf_latest = ocf_latest - capex_latest
    if fcf_prev is None and ocf_prev is not None and capex_prev is not None:
        fcf_prev = ocf_prev - capex_prev

    cash_balance_latest = safe_float((balance_latest or {}).get("cashAndCashEquivalents"))
    cash_balance_prev = safe_float((balance_prev or {}).get("cashAndCashEquivalents"))
    debt_latest = safe_float((balance_latest or {}).get("totalDebt"))
    debt_prev = safe_float((balance_prev or {}).get("totalDebt"))

    trends = (
        _trend_point("revenue", revenue_latest, revenue_prev, period=period),
        _trend_point("eps", eps_latest, eps_prev, period=period),
        _trend_point("operating_income", op_latest, op_prev, period=period),
        _trend_point("net_income", ni_latest, ni_prev, period=period),
        _trend_point("gross_margin", gross_latest, gross_prev, period=period),
        _trend_point("operating_margin", op_margin_latest, op_margin_prev, period=period),
        _trend_point("net_margin", net_margin_latest, net_margin_prev, period=period),
        _trend_point("operating_cash_flow", ocf_latest, ocf_prev, period=period),
        _trend_point("free_cash_flow", fcf_latest, fcf_prev, period=period),
        _trend_point("capex", capex_latest, capex_prev, period=period, higher_is_better=False),
        _trend_point("cash", cash_balance_latest, cash_balance_prev, period=period),
        _trend_point("total_debt", debt_latest, debt_prev, period=period, higher_is_better=False),
    )

    observations: List[IntelligenceObservation] = []
    revenue_change = pct_change(revenue_latest, revenue_prev)
    if revenue_change is not None and abs(revenue_change) >= MATERIAL_YOY_CHANGE_PCT:
        observations.append(
            IntelligenceObservation(
                code="REVENUE_YOY_CHANGE",
                status="FACT",
                statement="Gelir yıldan yıla anlamlı değişim gösteriyor.",
                metric="revenue",
                value=revenue_latest,
                comparison_value=revenue_prev,
                direction=direction_from_change(revenue_change, higher_is_better=True),
                evidence=(("revenue_yoy_pct", revenue_change),),
                source=PROVIDER_NAME,
                confidence="HIGH",
                period=period,
            )
        )

    if gross_latest is not None and gross_prev is not None:
        margin_delta = gross_latest - gross_prev
        if abs(margin_delta) >= MARGIN_CHANGE_PP:
            code = (
                "GROSS_MARGIN_EXPANSION"
                if margin_delta > 0
                else "GROSS_MARGIN_COMPRESSION"
            )
            observations.append(
                IntelligenceObservation(
                    code=code,
                    status="FACT",
                    statement="Brüt marj yıldan yıla değişim gösteriyor.",
                    metric="gross_margin",
                    value=gross_latest,
                    comparison_value=gross_prev,
                    direction=direction_from_change(margin_delta, higher_is_better=True),
                    evidence=(("margin_delta_pp", margin_delta),),
                    source=PROVIDER_NAME,
                    confidence="HIGH",
                    period=period,
                )
            )

    if debt_latest is not None and debt_prev is not None and debt_latest > debt_prev:
        observations.append(
            IntelligenceObservation(
                code="DEBT_INCREASE",
                status="FACT",
                statement="Toplam borç önceki döneme göre yükseldi.",
                metric="total_debt",
                value=debt_latest,
                comparison_value=debt_prev,
                direction="DETERIORATING",
                evidence=(("debt_change", debt_latest - debt_prev),),
                source=PROVIDER_NAME,
                confidence="MEDIUM",
                period=period,
                limitations=("Borç artışı tek başına kalite bozulması anlamına gelmez.",),
            )
        )

    return FinancialTrendsSection(
        trends=tuple(trends),
        observations=tuple(observations),
        provenance=IntelligenceProvenance(
            provider=PROVIDER_NAME,
            data_family="financial_statements_quarterly",
            source_period=period,
            retrieved_at=bundle.retrieved_at,
        ),
    )
