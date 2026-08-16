from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from services.monitor_contract import PortfolioImpactView


def build_portfolio_impact(
    *,
    symbol: Optional[str],
    held_symbols: Mapping[str, Dict[str, Any]],
    enriched_by_symbol: Mapping[str, Dict[str, Any]],
) -> PortfolioImpactView:
    sym = str(symbol or "").strip().upper()
    if not sym or sym not in held_symbols:
        return PortfolioImpactView(
            held=False,
            total_quantity=None,
            portfolio_weight=None,
            account_count=0,
            account_breakdown=(),
            concentration_rank=None,
            participation_status=None,
            research_coverage=None,
            limitations=("Sembol portföyde tutulmuyor.",),
        )

    held = held_symbols[sym]
    enriched = enriched_by_symbol.get(sym, {})
    breakdown = tuple(held.get("account_breakdown") or ())
    weight = enriched.get("portfolio_weight_pct")
    if weight is None:
        weight = held.get("portfolio_weight_pct")
    limitations: List[str] = []
    if weight is None:
        limitations.append("Portföy ağırlığı fiyat eksikliği nedeniyle hesaplanamadı.")

    return PortfolioImpactView(
        held=True,
        total_quantity=held.get("total_quantity"),
        portfolio_weight=float(weight) if weight is not None else None,
        account_count=len(breakdown) or int(held.get("account_count") or 0),
        account_breakdown=breakdown,
        concentration_rank=enriched.get("concentration_rank"),
        participation_status=enriched.get("participation_status"),
        research_coverage=enriched.get("research_coverage"),
        limitations=tuple(limitations),
    )


def build_held_symbol_index(
    consolidated_symbols: Sequence[Any],
) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for item in consolidated_symbols:
        symbol = str(getattr(item, "symbol", "") or "").upper()
        if not symbol:
            continue
        breakdown = []
        for part in getattr(item, "account_breakdown", ()) or ():
            breakdown.append(
                {
                    "account_id": getattr(part, "account_id", None),
                    "account_label": getattr(part, "account_label", None),
                    "quantity": getattr(part, "quantity", None),
                    "market_value": getattr(part, "market_value", None),
                }
            )
        index[symbol] = {
            "total_quantity": getattr(item, "total_quantity", None),
            "portfolio_weight_pct": getattr(item, "portfolio_weight_pct", None),
            "account_breakdown": breakdown,
            "account_count": len(breakdown),
            "participation_status": getattr(item, "participation_status", None),
        }
    return index


def build_enriched_index(enriched_positions: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
    rows = sorted(
        enriched_positions,
        key=lambda row: float(getattr(getattr(row, "valuation", None), "weight_pct", 0) or 0),
        reverse=True,
    )
    index: Dict[str, Dict[str, Any]] = {}
    for rank, row in enumerate(rows, start=1):
        valuation = getattr(row, "valuation", None)
        symbol = str(getattr(valuation, "symbol", "") or "").upper()
        if not symbol:
            continue
        index[symbol] = {
            "portfolio_weight_pct": getattr(valuation, "weight_pct", None),
            "participation_status": getattr(row, "participation_status", None),
            "research_coverage": getattr(row, "research_coverage", None),
            "concentration_rank": rank,
        }
    return index
