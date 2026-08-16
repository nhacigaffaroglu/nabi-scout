from __future__ import annotations

from typing import Dict, List, Tuple

from services.portfolio_intelligence_enrichment_contract import (
    ConsolidatedSymbolRow,
    EnrichedPositionRow,
    SymbolAccountBreakdown,
)


def build_consolidated_symbol_rows(
    rows: List[EnrichedPositionRow],
    *,
    total_market_value: float,
) -> Tuple[ConsolidatedSymbolRow, ...]:
    buckets: Dict[str, List[EnrichedPositionRow]] = {}
    for row in rows:
        if row.valuation.is_cash:
            continue
        key = str(row.valuation.symbol or "").strip().upper()
        if not key or key == "CASH":
            continue
        buckets.setdefault(key, []).append(row)

    consolidated: List[ConsolidatedSymbolRow] = []
    for symbol, group in sorted(buckets.items()):
        total_qty = sum(item.valuation.quantity for item in group)
        total_cost = sum(item.valuation.cost_basis for item in group)
        priced_mv = [
            float(item.valuation.market_value or 0.0)
            for item in group
            if item.valuation.price_available and item.valuation.market_value is not None
        ]
        total_mv = sum(priced_mv) if priced_mv else None
        total_pl = None
        if total_mv is not None:
            total_pl = total_mv - total_cost
        weight = (
            (total_mv / total_market_value) * 100.0
            if total_mv is not None and total_market_value > 0
            else None
        )
        lead = group[0]
        breakdown = tuple(
            SymbolAccountBreakdown(
                account_id=item.account_id,
                account_label=item.account_label,
                quantity=item.valuation.quantity,
                market_value=item.valuation.market_value,
                average_cost=item.valuation.average_cost,
            )
            for item in group
        )
        consolidated.append(
            ConsolidatedSymbolRow(
                symbol=symbol,
                company_name=lead.company_name,
                total_quantity=total_qty,
                total_cost_basis=total_cost,
                total_market_value=total_mv,
                total_unrealized_pl=total_pl,
                portfolio_weight_pct=weight,
                participation_status=lead.participation_status,
                research_coverage_label=lead.research_coverage_label,
                account_breakdown=breakdown,
            )
        )
    consolidated.sort(
        key=lambda row: float(row.total_market_value or 0.0),
        reverse=True,
    )
    return tuple(consolidated)
