from __future__ import annotations

from typing import Iterable, List

from services.portfolio_intelligence_contract import (
    PortfolioIntelligenceView,
    PositionValuationRow,
)


def iter_all_position_rows(
    view: PortfolioIntelligenceView,
) -> List[PositionValuationRow]:
    """Flatten priced, unpriced, and foreign-currency rows."""
    return (
        list(view.priced_positions)
        + list(view.unpriced_positions)
        + list(view.foreign_currency_positions)
    )


def iter_invested_position_rows(
    view: PortfolioIntelligenceView,
) -> Iterable[PositionValuationRow]:
    for row in iter_all_position_rows(view):
        if not row.is_cash:
            yield row
