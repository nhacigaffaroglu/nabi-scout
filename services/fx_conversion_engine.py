from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from services.fx_rate_service import FxRateService
from services.portfolio_intelligence_contract import (
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_price_service import normalize_currency


@dataclass(frozen=True)
class FxAdjustedTotals:
    base_currency: str
    converted_market_value: float
    unconverted_market_value: float
    excluded_unpriced_count: int
    conversion_coverage_pct: Optional[float]
    stale_rate_count: int
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def apply_fx_to_position_rows(
    rows: List[PositionValuationRow],
    *,
    base_currency: str,
    fx_service: FxRateService,
) -> Tuple[List[PositionValuationRow], FxAdjustedTotals]:
    base = normalize_currency(base_currency)
    adjusted: List[PositionValuationRow] = []
    converted_total = 0.0
    unconverted_total = 0.0
    stale_count = 0
    limitations: List[str] = []

    for row in rows:
        if not row.price_available or row.market_value is None:
            adjusted.append(row)
            continue

        native_currency = normalize_currency(row.valuation_currency)
        native_mv = float(row.market_value)

        if native_currency == base:
            converted_total += native_mv
            adjusted.append(row)
            continue

        fx = fx_service.convert_amount(
            amount=native_mv,
            from_currency=native_currency,
            to_currency=base,
        )
        if fx.converted and fx.converted_amount is not None:
            if fx.stale:
                stale_count += 1
            converted_total += fx.converted_amount
            adjusted.append(
                PositionValuationRow(
                    position_id=row.position_id,
                    account_id=row.account_id,
                    asset_id=row.asset_id,
                    symbol=row.symbol,
                    asset_class=row.asset_class,
                    account_name=row.account_name,
                    quantity=row.quantity,
                    average_cost=row.average_cost,
                    valuation_currency=native_currency,
                    price=row.price,
                    price_available=True,
                    market_value=fx.converted_amount,
                    cost_basis=row.cost_basis,
                    unrealized_pl=row.unrealized_pl,
                    weight_pct=row.weight_pct,
                    is_cash=row.is_cash,
                    included_in_base_totals=True,
                    nabi=row.nabi,
                    native_market_value=native_mv,
                    fx_converted=True,
                    fx_rate_used=fx.rate_used,
                    fx_rate_date=fx.rate_date,
                    fx_stale=fx.stale,
                    fx_unavailable=False,
                )
            )
        else:
            unconverted_total += native_mv
            if fx.limitation:
                limitations.append(f"{row.symbol}: {fx.limitation}")
            adjusted.append(
                PositionValuationRow(
                    position_id=row.position_id,
                    account_id=row.account_id,
                    asset_id=row.asset_id,
                    symbol=row.symbol,
                    asset_class=row.asset_class,
                    account_name=row.account_name,
                    quantity=row.quantity,
                    average_cost=row.average_cost,
                    valuation_currency=native_currency,
                    price=row.price,
                    price_available=True,
                    market_value=native_mv,
                    cost_basis=row.cost_basis,
                    unrealized_pl=row.unrealized_pl,
                    weight_pct=row.weight_pct,
                    is_cash=row.is_cash,
                    included_in_base_totals=False,
                    nabi=row.nabi,
                    native_market_value=native_mv,
                    fx_converted=False,
                    fx_unavailable=True,
                )
            )

    priced_total = converted_total + unconverted_total
    coverage = (converted_total / priced_total * 100.0) if priced_total > 0 else None
    totals = FxAdjustedTotals(
        base_currency=base,
        converted_market_value=converted_total,
        unconverted_market_value=unconverted_total,
        excluded_unpriced_count=sum(1 for row in rows if not row.price_available),
        conversion_coverage_pct=coverage,
        stale_rate_count=stale_count,
        limitations=tuple(dict.fromkeys(limitations)),
    )
    return adjusted, totals


def apply_fx_to_portfolio_view(
    view: PortfolioIntelligenceView,
    fx_service: FxRateService,
) -> Tuple[PortfolioIntelligenceView, FxAdjustedTotals]:
    from services.portfolio_intelligence_engine import rollup_portfolio_intelligence

    all_rows = (
        list(view.priced_positions)
        + list(view.unpriced_positions)
        + list(view.foreign_currency_positions)
    )
    seen_ids = {row.position_id for row in all_rows}
    for row in all_rows:
        if row.position_id in seen_ids:
            continue
        seen_ids.add(row.position_id)

    source_rows: List[PositionValuationRow] = []
    for row in view.priced_positions + view.unpriced_positions + view.foreign_currency_positions:
        if row.position_id not in {r.position_id for r in source_rows}:
            source_rows.append(row)

    adjusted_rows, totals = apply_fx_to_position_rows(
        source_rows,
        base_currency=view.base_currency,
        fx_service=fx_service,
    )
    rerolled = rollup_portfolio_intelligence(
        portfolio_id=view.portfolio_id,
        portfolio_name=view.portfolio_name,
        base_currency=view.base_currency,
        rows=adjusted_rows,
        price_provider=view.price_provider,
        unique_price_symbols_fetched=view.unique_price_symbols_fetched,
        valuation_errors=list(view.valuation_errors) + list(totals.limitations),
    )
    rerolled = PortfolioIntelligenceView(
        portfolio_id=rerolled.portfolio_id,
        portfolio_name=rerolled.portfolio_name,
        base_currency=rerolled.base_currency,
        priced_total_market_value=rerolled.priced_total_market_value,
        priced_total_cost_basis=rerolled.priced_total_cost_basis,
        priced_total_unrealized_pl=rerolled.priced_total_unrealized_pl,
        priced_position_count=rerolled.priced_position_count,
        unpriced_position_count=rerolled.unpriced_position_count,
        foreign_currency_position_count=sum(
            1 for row in adjusted_rows if row.fx_unavailable and row.price_available
        ),
        total_position_count=rerolled.total_position_count,
        mixed_currency_warning=totals.unconverted_market_value > 0,
        fx_supported=totals.conversion_coverage_pct is not None,
        priced_positions=rerolled.priced_positions,
        unpriced_positions=rerolled.unpriced_positions,
        foreign_currency_positions=[
            row for row in adjusted_rows if row.fx_unavailable and row.price_available
        ],
        asset_class_allocation=rerolled.asset_class_allocation,
        account_allocation=rerolled.account_allocation,
        health=rerolled.health,
        valuation_errors=rerolled.valuation_errors,
        price_provider=rerolled.price_provider,
        unique_price_symbols_fetched=rerolled.unique_price_symbols_fetched,
    )
    return rerolled, totals
