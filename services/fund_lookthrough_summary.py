"""Weighted look-through analytics from official holdings.

Sector and country stay UNKNOWN unless official classification is supplied.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from services.fund_product_contract import (
    CASH_TICKERS,
    FundLookthroughSummary,
    LookthroughHolding,
)
from services.official_fund_holdings_client import OfficialHolding, OfficialHoldingsFile


def _is_cash(row: OfficialHolding) -> bool:
    ident = str(row.holding_identifier or "").strip().upper()
    name = str(row.security_name or "").strip().upper()
    return ident in CASH_TICKERS or name in {"CASH & OTHER", "CASH AND OTHER", "CASH"}


def build_fund_lookthrough_summary(
    file: OfficialHoldingsFile,
    *,
    known_nabi_symbols: Optional[Iterable[str]] = None,
    official_sectors: Optional[dict[str, str]] = None,
    official_countries: Optional[dict[str, str]] = None,
) -> FundLookthroughSummary:
    known = {str(item).strip().upper() for item in (known_nabi_symbols or ())}
    sectors = official_sectors or {}
    countries = official_countries or {}
    rows = sorted(file.holdings, key=lambda item: float(item.weight_pct), reverse=True)
    holdings: list[LookthroughHolding] = []
    cash_w = 0.0
    unknown_w = 0.0
    overlap: list[str] = []
    for row in rows:
        ident = str(row.holding_identifier or "").strip().upper()
        cash = _is_cash(row)
        resolved = bool(ident) and not cash
        if cash:
            cash_w += float(row.weight_pct)
        if not ident:
            unknown_w += float(row.weight_pct)
            resolved = False
        if ident in known:
            overlap.append(ident)
        holdings.append(
            LookthroughHolding(
                holding_identifier=ident or "UNKNOWN",
                security_name=row.security_name,
                weight_pct=float(row.weight_pct),
                resolved=resolved,
                cash_or_other=cash,
            )
        )
    top = holdings[0] if holdings else None
    top10 = sum(item.weight_pct for item in holdings[:10])
    sector_alloc: list[tuple[str, float]] = []
    country_alloc: list[tuple[str, float]] = []
    if sectors:
        buckets: dict[str, float] = {}
        for row in rows:
            label = sectors.get(str(row.holding_identifier or "").upper()) or "UNKNOWN"
            buckets[label] = buckets.get(label, 0.0) + float(row.weight_pct)
        sector_alloc = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    if countries:
        buckets = {}
        for row in rows:
            label = countries.get(str(row.holding_identifier or "").upper()) or "UNKNOWN"
            buckets[label] = buckets.get(label, 0.0) + float(row.weight_pct)
        country_alloc = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    limitation = ""
    if not sectors:
        limitation = "SECTOR_UNKNOWN"
    if not countries:
        limitation = f"{limitation}+COUNTRY_UNKNOWN" if limitation else "COUNTRY_UNKNOWN"
    return FundLookthroughSummary(
        fund_symbol=file.fund_symbol,
        as_of=file.as_of.isoformat(),
        holdings_count=len(holdings),
        top_holding=top,
        top_holding_weight_pct=top.weight_pct if top else None,
        top10_weight_pct=round(top10, 4),
        single_name_concentration_pct=top.weight_pct if top else None,
        cash_other_weight_pct=round(cash_w, 4),
        unknown_weight_pct=round(unknown_w, 4),
        sector_allocation=tuple(sector_alloc),
        country_allocation=tuple(country_alloc),
        known_nabi_overlap=tuple(sorted(set(overlap))),
        limitation=limitation,
    )


def weight_sum(rows: Sequence[OfficialHolding]) -> float:
    return round(sum(float(item.weight_pct) for item in rows), 4)
