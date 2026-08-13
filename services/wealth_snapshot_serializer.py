from __future__ import annotations

from typing import Any, Dict, List

from services.portfolio_intelligence_contract import PortfolioIntelligenceView


def _allocation_payload(slices) -> List[Dict[str, Any]]:
    return [
        {
            "key": row.key,
            "label": row.label,
            "market_value": row.market_value,
            "weight_pct": row.weight_pct,
        }
        for row in slices
    ]


def _position_payload(view: PortfolioIntelligenceView) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in view.priced_positions:
        rows.append(
            {
                "position_id": row.position_id,
                "symbol": row.symbol,
                "asset_class": row.asset_class,
                "account_name": row.account_name,
                "quantity": row.quantity,
                "average_cost": row.average_cost,
                "valuation_currency": row.valuation_currency,
                "price": row.price,
                "market_value": row.market_value,
                "cost_basis": row.cost_basis,
                "unrealized_pl": row.unrealized_pl,
                "weight_pct": row.weight_pct,
                "is_cash": row.is_cash,
            }
        )
    return rows


def cash_value_from_view(view: PortfolioIntelligenceView) -> float:
    return sum(
        float(row.market_value or 0.0)
        for row in view.priced_positions
        if row.is_cash and row.market_value is not None
    )


def invested_value_from_view(view: PortfolioIntelligenceView) -> float:
    return float(view.priced_total_market_value) - cash_value_from_view(view)


def build_valuation_payload(view: PortfolioIntelligenceView) -> Dict[str, Any]:
    """Audit summary from PortfolioIntelligenceView — no provider or NABI data."""
    return {
        "portfolio_id": view.portfolio_id,
        "portfolio_name": view.portfolio_name,
        "base_currency": view.base_currency,
        "priced_total_market_value": view.priced_total_market_value,
        "priced_total_cost_basis": view.priced_total_cost_basis,
        "priced_total_unrealized_pl": view.priced_total_unrealized_pl,
        "total_position_count": view.total_position_count,
        "priced_position_count": view.priced_position_count,
        "unpriced_position_count": view.unpriced_position_count,
        "foreign_currency_position_count": view.foreign_currency_position_count,
        "mixed_currency_warning": view.mixed_currency_warning,
        "fx_supported": view.fx_supported,
        "priced_position_coverage_pct": view.health.priced_position_coverage_pct,
        "priced_positions": _position_payload(view),
        "asset_class_allocation": _allocation_payload(view.asset_class_allocation),
        "account_allocation": _allocation_payload(view.account_allocation),
        "unpriced_symbols": [row.symbol for row in view.unpriced_positions],
        "foreign_currency_symbols": [row.symbol for row in view.foreign_currency_positions],
    }


def snapshot_row_from_intelligence_view(
    *,
    user_id: str,
    portfolio_id: str,
    captured_at: str,
    view: PortfolioIntelligenceView,
    liabilities_total: float | None,
) -> Dict[str, Any]:
    cash_value = cash_value_from_view(view)
    invested_value = invested_value_from_view(view)
    net_wealth_partial = None
    if liabilities_total is not None:
        net_wealth_partial = float(view.priced_total_market_value) - float(liabilities_total)

    return {
        "user_id": user_id,
        "portfolio_id": portfolio_id,
        "captured_at": captured_at,
        "base_currency": view.base_currency,
        "priced_market_value": view.priced_total_market_value,
        "total_cost_basis": view.priced_total_cost_basis,
        "unrealized_pl": view.priced_total_unrealized_pl,
        "cash_value": cash_value,
        "invested_value": invested_value,
        "liabilities_total": liabilities_total,
        "net_wealth_partial": net_wealth_partial,
        "priced_position_coverage_pct": view.health.priced_position_coverage_pct,
        "unpriced_position_count": view.unpriced_position_count,
        "mixed_currency_warning": view.mixed_currency_warning,
        "valuation_payload": build_valuation_payload(view),
    }
