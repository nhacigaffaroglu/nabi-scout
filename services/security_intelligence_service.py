"""Canonical Security Intelligence entry point.

Consumers: Scanner, Company Report, Adviser, Wealth Brain, Dashboard,
Signal Intelligence, New Money diagnostics.

Does not write portfolios, candidates, Participation, or Hybrid state.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from services.security_intelligence_contract import (
    SecurityFacts,
    SecurityIntelligenceSnapshot,
    SecurityIntelligenceView,
    SecurityParticipationContext,
)
from services.security_intelligence_engine import evaluate_security_intelligence


def _num(raw: Any) -> Optional[float]:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def facts_from_candidate(
    raw: Optional[Mapping[str, Any]],
    *,
    symbol: str,
    instrument_type: str = "",
    economic_layer: Optional[str] = None,
    stale: bool = False,
) -> SecurityFacts:
    row = dict(raw or {})
    ticker = str(row.get("symbol") or symbol or "").strip().upper()
    mapped = {
        "price": _num(row.get("current_price") or row.get("price")),
        "market_cap": _num(row.get("market_cap")),
        "revenue": _num(row.get("revenue")),
        "free_cash_flow": _num(row.get("free_cash_flow")),
        "gross_margin": _num(row.get("gross_margin")),
        "operating_margin": _num(row.get("operating_margin")),
        "net_margin": _num(row.get("net_margin")),
        "fcf_margin": _num(row.get("free_cash_flow_margin") or row.get("fcf_margin")),
        "roe": _num(row.get("roe")),
        "roa": _num(row.get("roa")),
        "roic": _num(row.get("roic")),
        "revenue_growth_yoy": _num(row.get("revenue_growth") or row.get("revenue_growth_1y")),
        "revenue_cagr_3y": _num(row.get("revenue_cagr_3y")),
        "eps_growth_yoy": _num(row.get("eps_growth") or row.get("eps_growth_1y")),
        "eps_cagr_3y": _num(row.get("eps_cagr_3y")),
        "fcf_cagr_3y": _num(row.get("fcf_cagr_3y")),
        "pe": _num(row.get("pe_ratio") or row.get("pe")),
        "price_to_sales": _num(row.get("price_to_sales")),
        "price_to_book": _num(row.get("price_to_book")),
        "debt_to_equity": _num(row.get("debt_to_equity")),
        "net_debt": _num(row.get("net_debt")),
        "net_debt_to_fcf": _num(row.get("net_debt_to_fcf")),
        "current_ratio": _num(row.get("current_ratio")),
        "interest_coverage": _num(row.get("interest_coverage")),
        "share_change_3y": _num(row.get("share_change_3y")),
        "payout_ratio": _num(row.get("payout_ratio")),
        "average_volume": _num(row.get("average_volume")),
        "return_3m": _num(row.get("return_3m")),
        "return_1y": _num(row.get("return_12m") or row.get("return_1y")),
    }
    missing = tuple(name for name, value in mapped.items() if value is None)
    return SecurityFacts(
        symbol=ticker,
        name=str(row.get("company_name") or ""),
        instrument_type=instrument_type or str(row.get("security_type") or ""),
        economic_layer=economic_layer,
        exchange=str(row.get("exchange_name") or ""),
        currency=str(row.get("currency") or row.get("financial_currency") or ""),
        stale=stale or str(row.get("freshness_status") or "").upper() == "STALE",
        source=str(row.get("data_source") or "investment_candidates"),
        as_of=str(row.get("financial_period_end") or row.get("source_updated_at") or "") or None,
        missing_fields=missing,
        **mapped,
    )


def participation_from_sources(
    *,
    queue_or_snapshot: Optional[Mapping[str, Any]] = None,
    candidate: Optional[Mapping[str, Any]] = None,
    research_allowed: Optional[bool] = None,
) -> SecurityParticipationContext:
    row = dict(queue_or_snapshot or {})
    cand = dict(candidate or {})
    status = str(row.get("participation_status") or cand.get("participation_status") or "")
    allowed = research_allowed
    if allowed is None and "research_allowed" in row:
        raw = row.get("research_allowed")
        allowed = None if raw is None else bool(raw)
    return SecurityParticipationContext(
        status=status,
        research_allowed=allowed,
        methodology=str(row.get("methodology_id") or ""),
        as_of=str(row.get("as_of") or row.get("assessed_at") or "") or None,
    )


class SecurityIntelligenceService:
    """Single evaluate() entry. No provider calls. No writes."""

    def evaluate(
        self,
        facts: SecurityFacts,
        participation: Optional[SecurityParticipationContext] = None,
        *,
        previous: Optional[SecurityIntelligenceSnapshot] = None,
    ) -> SecurityIntelligenceView:
        return evaluate_security_intelligence(
            facts,
            participation,
            previous=previous,
        )
