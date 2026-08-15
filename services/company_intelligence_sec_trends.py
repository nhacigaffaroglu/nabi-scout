from __future__ import annotations

from typing import Any, Mapping, Optional

from services.company_financial_trend_engine import _margin, _trend_point
from services.company_intelligence_contract import (
    FinancialTrendsSection,
    IntelligenceProvenance,
)
from services.company_intelligence_constants import MATERIAL_YOY_CHANGE_PCT, MARGIN_CHANGE_PP
from services.company_intelligence_utils import direction_from_change, pct_change, safe_float

SEC_PROVIDER_NAME = "sec"
SEC_ANNUAL_TRENDS_FAMILY = "financial_statements_annual"


def sec_annual_yoy_available(sec_financials: Mapping[str, Any]) -> bool:
    if not sec_financials:
        return False
    if int(sec_financials.get("annual_periods_found") or 0) < 2:
        return False
    return sec_financials.get("revenue_prior") is not None and sec_financials.get("revenue") is not None


def build_financial_trends_from_sec(
    sec_financials: Mapping[str, Any],
    *,
    symbol: str,
    retrieved_at: str,
) -> Optional[FinancialTrendsSection]:
    if not sec_annual_yoy_available(sec_financials):
        return None

    period = str(sec_financials.get("financial_period_end") or "")[:10] or None
    comparison_period = str(sec_financials.get("comparison_period_end") or "")[:10] or None
    limitations = ()
    if comparison_period:
        limitations = (
            f"Karşılaştırma yıllık SEC dönemi: {comparison_period}.",
            "FMP çeyreklik endpoint plan kapsamında değil; yıllık SEC verisi kullanıldı.",
        )

    revenue_latest = safe_float(sec_financials.get("revenue"))
    revenue_prev = safe_float(sec_financials.get("revenue_prior"))
    eps_latest = safe_float(sec_financials.get("eps"))
    eps_prev = safe_float(sec_financials.get("eps_prior"))
    op_latest = safe_float(sec_financials.get("operating_income"))
    op_prev = safe_float(sec_financials.get("operating_income_prior"))
    ni_latest = safe_float(sec_financials.get("net_income"))
    ni_prev = safe_float(sec_financials.get("net_income_prior"))

    gross_latest = safe_float(sec_financials.get("gross_margin"))
    gross_prev = None
    if sec_financials.get("gross_profit_prior") is not None and revenue_prev:
        gross_prev = _margin(
            safe_float(sec_financials.get("gross_profit_prior")),
            revenue_prev,
        )
    if gross_latest is None:
        gross_latest = _margin(
            safe_float(sec_financials.get("gross_profit")),
            revenue_latest,
        )

    op_margin_latest = safe_float(sec_financials.get("operating_margin"))
    op_margin_prev = _margin(op_prev, revenue_prev) if op_prev is not None else None
    net_margin_latest = safe_float(sec_financials.get("net_margin"))
    net_margin_prev = _margin(ni_prev, revenue_prev) if ni_prev is not None else None

    ocf_latest = safe_float(sec_financials.get("operating_cash_flow"))
    ocf_prev = safe_float(sec_financials.get("operating_cash_flow_prior"))
    capex_latest = safe_float(sec_financials.get("capital_expenditure"))
    capex_prev = safe_float(sec_financials.get("capital_expenditure_prior"))
    if capex_latest is not None:
        capex_latest = abs(capex_latest)
    if capex_prev is not None:
        capex_prev = abs(capex_prev)
    fcf_latest = safe_float(sec_financials.get("free_cash_flow"))
    fcf_prev = safe_float(sec_financials.get("free_cash_flow_prior"))

    cash_latest = safe_float(sec_financials.get("cash"))
    cash_prev = safe_float(sec_financials.get("cash_prior"))
    debt_latest = safe_float(sec_financials.get("total_debt"))
    debt_prev = safe_float(sec_financials.get("total_debt_prior"))

    trends = (
        _trend_point("revenue", revenue_latest, revenue_prev, period=period, limitations=limitations),
        _trend_point("eps", eps_latest, eps_prev, period=period, limitations=limitations),
        _trend_point("operating_income", op_latest, op_prev, period=period, limitations=limitations),
        _trend_point("net_income", ni_latest, ni_prev, period=period, limitations=limitations),
        _trend_point("gross_margin", gross_latest, gross_prev, period=period, limitations=limitations),
        _trend_point("operating_margin", op_margin_latest, op_margin_prev, period=period, limitations=limitations),
        _trend_point("net_margin", net_margin_latest, net_margin_prev, period=period, limitations=limitations),
        _trend_point("operating_cash_flow", ocf_latest, ocf_prev, period=period, limitations=limitations),
        _trend_point("free_cash_flow", fcf_latest, fcf_prev, period=period, limitations=limitations),
        _trend_point(
            "capex",
            capex_latest,
            capex_prev,
            period=period,
            higher_is_better=False,
            limitations=limitations,
        ),
        _trend_point("cash", cash_latest, cash_prev, period=period, limitations=limitations),
        _trend_point(
            "total_debt",
            debt_latest,
            debt_prev,
            period=period,
            higher_is_better=False,
            limitations=limitations,
        ),
    )

    observations = []
    revenue_change = pct_change(revenue_latest, revenue_prev)
    if revenue_change is not None and abs(revenue_change) >= MATERIAL_YOY_CHANGE_PCT:
        from services.company_intelligence_contract import IntelligenceObservation

        observations.append(
            IntelligenceObservation(
                code="REVENUE_YOY_CHANGE",
                status="FACT",
                statement="Gelir yıldan yıla anlamlı değişim gösteriyor (SEC yıllık).",
                metric="revenue",
                value=revenue_latest,
                comparison_value=revenue_prev,
                direction=direction_from_change(revenue_change, higher_is_better=True),
                evidence=(
                    ("revenue_yoy_pct", revenue_change),
                    ("comparison_type", "YoY"),
                    ("source_type", "sec_annual"),
                ),
                source=SEC_PROVIDER_NAME,
                confidence="HIGH",
                period=period,
                limitations=limitations,
            )
        )

    if gross_latest is not None and gross_prev is not None:
        margin_delta = gross_latest - gross_prev
        if abs(margin_delta) >= MARGIN_CHANGE_PP:
            from services.company_intelligence_contract import IntelligenceObservation

            code = (
                "GROSS_MARGIN_EXPANSION"
                if margin_delta > 0
                else "GROSS_MARGIN_COMPRESSION"
            )
            observations.append(
                IntelligenceObservation(
                    code=code,
                    status="FACT",
                    statement="Brüt marj yıldan yıla değişim gösteriyor (SEC yıllık).",
                    metric="gross_margin",
                    value=gross_latest,
                    comparison_value=gross_prev,
                    direction=direction_from_change(margin_delta, higher_is_better=True),
                    evidence=(("margin_delta_pp", margin_delta), ("comparison_type", "YoY")),
                    source=SEC_PROVIDER_NAME,
                    confidence="HIGH",
                    period=period,
                    limitations=limitations,
                )
            )

    return FinancialTrendsSection(
        trends=tuple(trends),
        observations=tuple(observations),
        provenance=IntelligenceProvenance(
            provider=SEC_PROVIDER_NAME,
            data_family=SEC_ANNUAL_TRENDS_FAMILY,
            source_period=period,
            retrieved_at=retrieved_at,
        ),
    )
