"""Read-only direct + weighted look-through overlap.

Does not write positions, change Hybrid OFF, or invent identifiers.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping, Sequence

from services.fund_product_contract import OverlapRow, PortfolioFundOverlapView
from services.official_fund_holdings_client import OfficialHoldingsFile
from services.wealth_asset_classification import KNOWN_ETF_SYMBOLS


def build_fund_portfolio_overlap(
    positions: Sequence[Mapping[str, object]],
    holdings_by_fund: Mapping[str, OfficialHoldingsFile],
    *,
    top_n: int = 8,
) -> PortfolioFundOverlapView:
    direct: dict[str, float] = defaultdict(float)
    fund_weights: dict[str, float] = defaultdict(float)
    for pos in positions:
        symbol = str(pos.get("symbol") or "").strip().upper()
        weight = float(pos.get("weight_pct") or 0.0)
        if not symbol or weight <= 0:
            continue
        if symbol in KNOWN_ETF_SYMBOLS or str(pos.get("asset_class") or "").lower() in {"etf", "fund"}:
            fund_weights[symbol] += weight
        else:
            direct[symbol] += weight

    indirect: dict[str, float] = defaultdict(float)
    sources: dict[str, set[str]] = defaultdict(set)
    for fund, weight in fund_weights.items():
        file = holdings_by_fund.get(fund)
        if file is None:
            continue
        for row in file.holdings:
            ident = str(row.holding_identifier or "").strip().upper()
            if not ident:
                continue
            contrib = weight * (float(row.weight_pct) / 100.0)
            if contrib <= 0:
                continue
            indirect[ident] += contrib
            sources[ident].add(fund)

    symbols = set(direct) | set(indirect)
    rows = []
    for symbol in symbols:
        d_w = float(direct.get(symbol) or 0.0)
        i_w = float(indirect.get(symbol) or 0.0)
        rows.append(
            OverlapRow(
                underlying_symbol=symbol,
                direct_weight_pct=round(d_w, 4),
                lookthrough_weight_pct=round(i_w, 4),
                combined_weight_pct=round(d_w + i_w, 4),
                source_funds=tuple(sorted(sources.get(symbol) or ())),
            )
        )
    rows.sort(key=lambda item: item.combined_weight_pct, reverse=True)
    both = [row for row in rows if row.direct_weight_pct > 0 and row.lookthrough_weight_pct > 0]
    return PortfolioFundOverlapView(
        direct_symbols=tuple(sorted(direct)),
        indirect_symbols=tuple(sorted(indirect)),
        rows=tuple(rows),
        largest_combined=tuple((both or rows)[:top_n]),
        limitation="",
    )
