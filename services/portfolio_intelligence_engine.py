from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
    PriceQuote,
)
from services.wealth_price_service import is_cash_asset, normalize_currency


def compute_cost_basis(quantity: float, average_cost: float) -> float:
    return quantity * average_cost


def compute_market_value(quantity: float, price: float) -> float:
    return quantity * price


def compute_unrealized_pl(market_value: float, cost_basis: float) -> float:
    return market_value - cost_basis


def position_in_base_currency(asset_currency: str, base_currency: str) -> bool:
    return normalize_currency(asset_currency) == normalize_currency(base_currency)


def position_converted_to_base(row: PositionValuationRow, base_currency: str) -> bool:
    """True when native currency is already comparable in portfolio base valuation."""
    if position_in_base_currency(row.valuation_currency, base_currency):
        return True
    return bool(
        getattr(row, "fx_converted", False)
        and row.included_in_base_totals
        and row.price_available
        and row.market_value is not None
    )


def mixed_currency_warning_from_rows(
    rows: List[PositionValuationRow],
    base_currency: str,
) -> bool:
    """True when any holding is not fully converted into base-currency valuation.

    Unpriced TRY/TL on a USD portfolio counts as unresolved mixed currency.
    Missing price/FX stays None on the row and is never treated as zero.
    """
    return any(not position_converted_to_base(row, base_currency) for row in rows)


def value_position(
    *,
    position: Dict[str, Any],
    asset: Dict[str, Any],
    account: Dict[str, Any],
    base_currency: str,
    quote: PriceQuote,
) -> PositionValuationRow:
    quantity = float(position.get("quantity") or 0.0)
    average_cost = float(position.get("average_cost") or 0.0)
    symbol = str(asset.get("symbol") or "")
    asset_class = str(asset.get("asset_class") or "")
    valuation_currency = normalize_currency(asset.get("currency"))
    cost_basis = compute_cost_basis(quantity, average_cost)
    cash = is_cash_asset(symbol, asset_class)
    in_base = position_in_base_currency(valuation_currency, base_currency)

    price_available = quote.available and quote.price is not None
    market_value: Optional[float] = None
    unrealized_pl: Optional[float] = None
    if price_available:
        market_value = compute_market_value(quantity, float(quote.price))
        unrealized_pl = compute_unrealized_pl(market_value, cost_basis)

    return PositionValuationRow(
        position_id=str(position.get("id") or ""),
        account_id=str(position.get("account_id") or ""),
        asset_id=str(position.get("asset_id") or ""),
        symbol=symbol,
        asset_class=asset_class,
        account_name=str(account.get("name") or ""),
        quantity=quantity,
        average_cost=average_cost,
        valuation_currency=valuation_currency,
        price=quote.price if price_available else None,
        price_available=price_available,
        market_value=market_value,
        cost_basis=cost_basis,
        unrealized_pl=unrealized_pl,
        weight_pct=None,
        is_cash=cash,
        included_in_base_totals=in_base,
    )


def _allocation_slices(
    rows: List[PositionValuationRow],
    *,
    key_fn,
    label_fn,
    total_market_value: float,
) -> List[AllocationSlice]:
    buckets: Dict[str, Tuple[str, float]] = {}
    for row in rows:
        key = key_fn(row)
        label = label_fn(row)
        current = buckets.get(key, (label, 0.0))
        buckets[key] = (label, current[1] + float(row.market_value or 0.0))

    slices: List[AllocationSlice] = []
    for key, (label, market_value) in sorted(
        buckets.items(),
        key=lambda item: item[1][1],
        reverse=True,
    ):
        weight = (
            (market_value / total_market_value) * 100.0
            if total_market_value > 0
            else 0.0
        )
        slices.append(
            AllocationSlice(
                key=key,
                label=label,
                market_value=market_value,
                weight_pct=weight,
            )
        )
    return slices


def compute_health_metrics(
    priced_base_rows: List[PositionValuationRow],
    *,
    all_rows: List[PositionValuationRow],
) -> PortfolioHealthMetrics:
    total_mv = sum(float(row.market_value or 0.0) for row in priced_base_rows)
    weights = sorted(
        [
            (float(row.market_value or 0.0) / total_mv) * 100.0
            for row in priced_base_rows
            if total_mv > 0 and row.market_value is not None
        ],
        reverse=True,
    )
    cash_mv = sum(
        float(row.market_value or 0.0)
        for row in priced_base_rows
        if row.is_cash and row.market_value is not None
    )
    cash_pct = (cash_mv / total_mv) * 100.0 if total_mv > 0 else 0.0
    invested_pct = 100.0 - cash_pct if total_mv > 0 else 0.0

    asset_class_slices = _allocation_slices(
        priced_base_rows,
        key_fn=lambda row: row.asset_class or "other",
        label_fn=lambda row: row.asset_class or "other",
        total_market_value=total_mv,
    )
    largest_asset_class = (
        asset_class_slices[0].weight_pct if asset_class_slices else 0.0
    )

    total_position_count = len(all_rows)
    priced_any_count = sum(1 for row in all_rows if row.price_available)
    coverage = (
        (priced_any_count / total_position_count) * 100.0
        if total_position_count > 0
        else 0.0
    )

    return PortfolioHealthMetrics(
        largest_position_weight_pct=weights[0] if weights else 0.0,
        top3_concentration_pct=sum(weights[:3]),
        largest_asset_class_concentration_pct=largest_asset_class,
        cash_pct=cash_pct,
        invested_pct=invested_pct,
        priced_position_coverage_pct=coverage,
    )


def rollup_portfolio_intelligence(
    *,
    portfolio_id: str,
    portfolio_name: str,
    base_currency: str,
    rows: List[PositionValuationRow],
    price_provider: str,
    unique_price_symbols_fetched: int,
    valuation_errors: List[str],
) -> PortfolioIntelligenceView:
    normalized_base = normalize_currency(base_currency)

    foreign_rows = [row for row in rows if not row.included_in_base_totals]
    base_rows = [row for row in rows if row.included_in_base_totals]

    unpriced_base = [row for row in base_rows if not row.price_available]
    unpriced_all = [row for row in rows if not row.price_available]
    priced_base = [row for row in base_rows if row.price_available]

    total_mv = sum(float(row.market_value or 0.0) for row in priced_base)
    total_cost = sum(float(row.cost_basis) for row in priced_base)
    total_pl = sum(float(row.unrealized_pl or 0.0) for row in priced_base)

    weighted_rows: List[PositionValuationRow] = []
    for row in priced_base:
        weight = (
            (float(row.market_value or 0.0) / total_mv) * 100.0
            if total_mv > 0 and row.market_value is not None
            else None
        )
        weighted_rows.append(replace(row, weight_pct=weight))

    asset_class_allocation = _allocation_slices(
        weighted_rows,
        key_fn=lambda row: row.asset_class or "other",
        label_fn=lambda row: row.asset_class or "other",
        total_market_value=total_mv,
    )
    account_allocation = _allocation_slices(
        weighted_rows,
        key_fn=lambda row: row.account_id,
        label_fn=lambda row: row.account_name or row.account_id,
        total_market_value=total_mv,
    )

    health = compute_health_metrics(weighted_rows, all_rows=rows)

    return PortfolioIntelligenceView(
        portfolio_id=portfolio_id,
        portfolio_name=portfolio_name,
        base_currency=normalized_base,
        priced_total_market_value=total_mv,
        priced_total_cost_basis=total_cost,
        priced_total_unrealized_pl=total_pl,
        priced_position_count=len(priced_base),
        unpriced_position_count=len(unpriced_all),
        foreign_currency_position_count=len(foreign_rows),
        total_position_count=len(rows),
        mixed_currency_warning=mixed_currency_warning_from_rows(rows, normalized_base),
        fx_supported=False,
        priced_positions=sorted(
            weighted_rows,
            key=lambda row: float(row.market_value or 0.0),
            reverse=True,
        ),
        unpriced_positions=unpriced_base,
        foreign_currency_positions=foreign_rows,
        asset_class_allocation=asset_class_allocation,
        account_allocation=account_allocation,
        health=health,
        valuation_errors=list(valuation_errors),
        price_provider=price_provider,
        unique_price_symbols_fetched=unique_price_symbols_fetched,
    )
