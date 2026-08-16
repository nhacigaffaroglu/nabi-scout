from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from services.portfolio_intelligence_enrichment_contract import (
    PortfolioIntelligenceDashboardView,
    PortfolioAttentionItem,
)
from services.portfolio_intelligence_enrichment_service import (
    build_portfolio_intelligence_dashboard,
)
from services.portfolio_intelligence_contract import PortfolioIntelligenceView

FORBIDDEN_CONTEXT_KEYS = frozenset({
    "api_key",
    "secret",
    "password",
    "token",
    "authorization",
    "provider_payload",
    "raw_llm",
    "raw_provider",
})


@dataclass(frozen=True)
class PortfolioResearchContext:
    schema_version: str
    portfolio_id: str
    portfolio_name: str
    base_currency: str
    summary: Dict[str, Any]
    accounts: Tuple[Dict[str, Any], ...]
    positions: Tuple[Dict[str, Any], ...]
    consolidated_positions: Tuple[Dict[str, Any], ...]
    sector_allocation: Tuple[Dict[str, Any], ...]
    participation_allocation: Tuple[Dict[str, Any], ...]
    research_coverage_allocation: Tuple[Dict[str, Any], ...]
    account_allocation: Tuple[Dict[str, Any], ...]
    currency_allocation: Tuple[Dict[str, Any], ...]
    concentration: Dict[str, Any]
    attention_items: Tuple[Dict[str, Any], ...]
    data_quality: Dict[str, Any]
    performance: Optional[Dict[str, Any]] = None
    income: Optional[Dict[str, Any]] = None
    cash_flow: Optional[Dict[str, Any]] = None
    change_events: Tuple[Dict[str, Any], ...] = ()
    goal_projections: Tuple[Dict[str, Any], ...] = ()
    opportunity_candidates: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _slice_to_dict(slice_row) -> Dict[str, Any]:
    return {
        "key": slice_row.key,
        "label": slice_row.label,
        "market_value": slice_row.market_value,
        "weight_pct": slice_row.weight_pct,
    }


def _attention_to_dict(item: PortfolioAttentionItem) -> Dict[str, Any]:
    return {
        "code": item.code,
        "severity": item.severity,
        "title": item.title,
        "detail": item.detail,
    }


def build_portfolio_research_context(
    dashboard: PortfolioIntelligenceDashboardView,
    *,
    v13: Optional[Any] = None,
) -> PortfolioResearchContext:
    base = dashboard.base
    positions: List[Dict[str, Any]] = []
    account_ids = set()
    for row in dashboard.enriched_positions:
        positions.append(
            {
                "symbol": row.valuation.symbol,
                "company_name": row.company_name,
                "account_id": row.account_id,
                "account_label": row.account_label,
                "institution": row.institution,
                "quantity": row.valuation.quantity,
                "average_cost": row.valuation.average_cost,
                "cost_basis": row.valuation.cost_basis,
                "price": row.valuation.price,
                "price_available": row.valuation.price_available,
                "market_value": row.valuation.market_value,
                "unrealized_pl": row.valuation.unrealized_pl,
                "weight_pct": row.valuation.weight_pct,
                "account_weight_pct": row.account_weight_pct,
                "sector": row.sector,
                "industry": row.industry,
                "country": row.country,
                "currency": row.valuation.valuation_currency,
                "participation_status": row.participation_status,
                "research_coverage": row.research_coverage,
                "research_allowed_inferred": row.research_allowed_inferred,
                "research_status": row.research_status,
                "has_candidate": row.has_candidate,
                "has_participation_snapshot": row.has_participation_snapshot,
            }
        )
        account_ids.add(row.account_id)

    consolidated_positions = [
        {
            "symbol": item.symbol,
            "company_name": item.company_name,
            "total_quantity": item.total_quantity,
            "total_cost_basis": item.total_cost_basis,
            "total_market_value": item.total_market_value,
            "total_unrealized_pl": item.total_unrealized_pl,
            "portfolio_weight_pct": item.portfolio_weight_pct,
            "participation_status": item.participation_status,
            "account_breakdown": [
                {
                    "account_id": part.account_id,
                    "account_label": part.account_label,
                    "quantity": part.quantity,
                    "market_value": part.market_value,
                    "average_cost": part.average_cost,
                }
                for part in item.account_breakdown
            ],
        }
        for item in dashboard.consolidated_symbols
    ]

    accounts = [
        {
            "account_id": slice_row.key,
            "label": slice_row.label,
            "weight_pct": slice_row.weight_pct,
            "market_value": slice_row.market_value,
        }
        for slice_row in dashboard.account_allocation
    ]

    schema_version = "portfolio_research_context_v2"
    performance_payload = None
    income_payload = None
    cash_flow_payload = None
    change_payload: Tuple[Dict[str, Any], ...] = ()
    goals_payload: Tuple[Dict[str, Any], ...] = ()
    opportunity_payload: Tuple[Dict[str, Any], ...] = ()

    if v13 is not None:
        schema_version = "portfolio_research_context_v3"
        perf = v13.performance
        performance_payload = {
            "current_value": perf.current_value,
            "invested_capital": perf.invested_capital,
            "net_contributions": perf.net_contributions,
            "investment_gain": perf.investment_gain,
            "dividend_income": perf.dividend_income,
            "fee_total": perf.fee_total,
            "return_pct": perf.return_pct,
            "linked_return_pct": perf.linked_return_pct,
            "performance_available": perf.performance_available,
            "limitations": list(perf.limitations),
        }
        income_payload = {
            "total_dividends": v13.income.total_dividends,
            "dividends_ytd": v13.income.dividends_ytd,
            "trailing_twelve_months": v13.income.trailing_twelve_months,
            "income_yield_pct": v13.income.income_yield_pct,
        }
        cash_flow_payload = {
            "total_deposits": v13.cash_flow.total_deposits,
            "total_withdrawals": v13.cash_flow.total_withdrawals,
            "net_external_flow": v13.cash_flow.net_external_flow,
        }
        change_payload = tuple(
            {
                "code": event.code,
                "severity": event.severity,
                "title": event.title,
                "detail": event.detail,
                "metric_value": event.metric_value,
                "previous_value": event.previous_value,
                "affected_symbols": list(event.affected_symbols),
            }
            for event in v13.change_events
        )
        goals_payload = tuple(
            {
                "goal_title": goal.goal_title,
                "target_value": goal.target_value,
                "target_date": goal.target_date,
                "scenarios": [
                    {
                        "label": scenario.label,
                        "projected_value": scenario.projected_value,
                        "funding_gap": scenario.funding_gap,
                        "assumptions_note": scenario.assumptions_note,
                    }
                    for scenario in goal.scenarios
                ],
            }
            for goal in v13.goal_projections
        )
        opportunity_payload = tuple(
            {
                "symbol": row.symbol,
                "opportunity_label": row.opportunity_label,
                "explanation": row.explanation,
                "participation_status": row.participation_status,
            }
            for row in v13.opportunities
        )

    return PortfolioResearchContext(
        schema_version=schema_version,
        portfolio_id=base.portfolio_id,
        portfolio_name=base.portfolio_name,
        base_currency=base.base_currency,
        summary={
            "total_market_value": base.priced_total_market_value,
            "total_cost_basis": base.priced_total_cost_basis,
            "unrealized_pl": base.priced_total_unrealized_pl,
            "return_pct": dashboard.return_pct,
            "position_count": base.total_position_count,
            "priced_position_count": base.priced_position_count,
            "account_count": len(accounts),
            "research_coverage_weight_pct": dashboard.research_coverage_weight_pct,
            "unresearched_weight_pct": dashboard.unresearched_weight_pct,
            "participation_eligible_weight_pct": dashboard.participation_eligible_weight_pct,
            "participation_non_eligible_weight_pct": (
                dashboard.participation_non_eligible_weight_pct
            ),
            "participation_review_weight_pct": dashboard.participation_review_weight_pct,
            "participation_unknown_weight_pct": dashboard.participation_unknown_weight_pct,
        },
        accounts=tuple(accounts),
        positions=tuple(positions),
        consolidated_positions=tuple(consolidated_positions),
        sector_allocation=tuple(_slice_to_dict(s) for s in dashboard.sector_allocation),
        participation_allocation=tuple(
            _slice_to_dict(s) for s in dashboard.participation_allocation
        ),
        research_coverage_allocation=tuple(
            _slice_to_dict(s) for s in dashboard.research_coverage_allocation
        ),
        account_allocation=tuple(_slice_to_dict(s) for s in dashboard.account_allocation),
        currency_allocation=tuple(_slice_to_dict(s) for s in dashboard.currency_allocation),
        concentration={
            "largest_position_weight_pct": base.health.largest_position_weight_pct,
            "top3_concentration_pct": base.health.top3_concentration_pct,
            "top5_concentration_pct": dashboard.top5_concentration_pct,
        },
        attention_items=tuple(_attention_to_dict(i) for i in dashboard.attention_items),
        data_quality={
            "priced_market_value_coverage_pct": (
                dashboard.coverage.priced_market_value_coverage_pct
            ),
            "participation_status_coverage_pct": (
                dashboard.coverage.participation_status_coverage_pct
            ),
            "sector_coverage_pct": dashboard.coverage.sector_coverage_pct,
            "price_data_complete": dashboard.coverage.price_data_complete,
            "limitations": list(dashboard.coverage.limitations),
            "fx_supported": base.fx_supported,
            "mixed_currency_warning": base.mixed_currency_warning,
            "snapshot_count": v13.data_quality.snapshot_count if v13 else None,
            "performance_available": (
                v13.data_quality.performance_available if v13 else None
            ),
        },
        performance=performance_payload,
        income=income_payload,
        cash_flow=cash_flow_payload,
        change_events=change_payload,
        goal_projections=goals_payload,
        opportunity_candidates=opportunity_payload,
    )


def assert_portfolio_research_context_safe(payload: Dict[str, Any]) -> None:
    """Raise ValueError if forbidden secret-like keys appear anywhere in payload."""

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                if any(token in lowered for token in FORBIDDEN_CONTEXT_KEYS):
                    raise ValueError(f"Forbidden key in portfolio context: {path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(payload, "root")


def build_context_from_view(
    base: PortfolioIntelligenceView,
) -> PortfolioResearchContext:
    dashboard = build_portfolio_intelligence_dashboard(base)
    context = build_portfolio_research_context(dashboard)
    assert_portfolio_research_context_safe(context.to_dict())
    return context
