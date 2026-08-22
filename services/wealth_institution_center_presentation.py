"""Kurum Merkezi presentation. Groups canonical valuation by account identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.portfolio_account_helpers import format_account_display
from services.portfolio_intelligence_contract import (
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_snapshot_serializer import valuation_is_complete

SECTION_TITLE = "Kurum Merkezi"
CASH_UNAVAILABLE = "Nakit verisi yok"
MULTI_INSTITUTION_TITLE = "Birden fazla kurumda tutulan varlıklar"
CONCENTRATION_TITLE = "Kurum yoğunlaşması"
HOLDINGS_EXPANDER = "Varlık detayı"
INCOMPLETE_LIMITATION = "Değerleme kısmi — gösterilen tutar alt sınırdır."
BRIEF_TEMPLATE = "Kurum dağılımı: en büyük kurum {name}, portföyün %{share:.1f}'si"


@dataclass(frozen=True)
class InstitutionHolding:
    symbol: str
    quantity: float
    market_value: Optional[float]
    portfolio_weight_pct: Optional[float]
    asset_type: str
    account_id: str
    account_name: str


@dataclass(frozen=True)
class InstitutionCard:
    account_id: str
    name: str
    currency: str
    securities_market_value: float
    cash_value: Optional[float]
    cash_available: bool
    total_value: float
    portfolio_share_pct: float
    holdings_count: int
    symbols: Tuple[str, ...]
    holdings: Tuple[InstitutionHolding, ...]
    account_ids: Tuple[str, ...]


@dataclass(frozen=True)
class InstitutionConcentration:
    top_name: Optional[str]
    top_share_pct: Optional[float]


@dataclass(frozen=True)
class MultiInstitutionHolding:
    symbol: str
    institutions: Tuple[str, ...]
    quantities_by_account: Tuple[Tuple[str, float], ...]
    total_quantity: float


@dataclass(frozen=True)
class InstitutionCenterTotals:
    securities_market_value: float
    cash_value: Optional[float]
    cash_available: bool
    total_value: float
    base_currency: str


@dataclass(frozen=True)
class InstitutionCenterView:
    institutions: Tuple[InstitutionCard, ...]
    totals: InstitutionCenterTotals
    concentration: InstitutionConcentration
    multi_institution_holdings: Tuple[MultiInstitutionHolding, ...]
    valuation_complete: bool
    limitation: Optional[str]
    brief_line: Optional[str]


def _account_map(accounts: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(row.get("id") or ""): row for row in accounts if row.get("id")}


def _institution_identity(
    account_id: str,
    account_name: str,
    accounts_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[str, str, str]:
    """Return (group_key, display_name, currency)."""
    account = accounts_by_id.get(str(account_id) or "")
    if account:
        institution = str(account.get("institution") or "").strip()
        currency = str(account.get("currency") or "").strip().upper()
        if institution:
            return institution.casefold(), institution, currency
        display = format_account_display(account)
        return str(account.get("id") or account_id), display, currency
    display = str(account_name or account_id or "—").strip() or "—"
    return str(account_id or display), display, ""


def _iter_view_rows(view: PortfolioIntelligenceView) -> Iterable[PositionValuationRow]:
    yield from view.priced_positions
    yield from view.unpriced_positions
    yield from view.foreign_currency_positions


def _share_pct(part: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return (part / total) * 100.0


def _brief_line(
    *,
    reliable: bool,
    top_name: Optional[str],
    top_share_pct: Optional[float],
) -> Optional[str]:
    if not reliable or not top_name or top_share_pct is None:
        return None
    return BRIEF_TEMPLATE.format(name=top_name, share=top_share_pct)


def present_institution_center(
    view: PortfolioIntelligenceView,
    accounts: Sequence[Dict[str, Any]] = (),
) -> InstitutionCenterView:
    """Group canonical priced valuation by institution, else account identity."""
    accounts_by_id = _account_map(accounts)
    complete = valuation_is_complete(view)
    portfolio_total = float(view.priced_total_market_value or 0.0)
    base = str(view.base_currency or "").strip().upper() or "USD"
    priced_ids = {id(row) for row in view.priced_positions}

    groups: Dict[str, Dict[str, Any]] = {}
    seen_positions: set[str] = set()
    for row in _iter_view_rows(view):
        marker = row.position_id or f"{row.account_id}:{row.symbol}:{id(row)}"
        if marker in seen_positions:
            continue
        seen_positions.add(marker)
        key, name, currency = _institution_identity(
            row.account_id, row.account_name, accounts_by_id
        )
        bucket = groups.get(key)
        if bucket is None:
            bucket = {
                "key": key,
                "name": name,
                "currency": currency or base,
                "account_ids": [],
                "account_names": {},
                "priced": [],
                "all_rows": [],
                "has_cash_row": False,
            }
            groups[key] = bucket
        account_id = str(row.account_id or "")
        if account_id and account_id not in bucket["account_ids"]:
            bucket["account_ids"].append(account_id)
        if account_id:
            bucket["account_names"][account_id] = row.account_name or name
        bucket["all_rows"].append(row)
        if id(row) in priced_ids:
            bucket["priced"].append(row)
            if row.is_cash:
                bucket["has_cash_row"] = True

    cards: List[InstitutionCard] = []
    for bucket in groups.values():
        priced: List[PositionValuationRow] = bucket["priced"]
        securities = sum(
            float(row.market_value or 0.0) for row in priced if not row.is_cash
        )
        cash_available = bool(bucket["has_cash_row"])
        cash_value = (
            sum(float(row.market_value or 0.0) for row in priced if row.is_cash)
            if cash_available
            else None
        )
        total_value = securities + (cash_value or 0.0)
        holdings = tuple(
            InstitutionHolding(
                symbol=str(row.symbol or ""),
                quantity=float(row.quantity or 0.0),
                market_value=(
                    float(row.market_value)
                    if id(row) in priced_ids and row.market_value is not None
                    else None
                ),
                portfolio_weight_pct=(
                    float(row.weight_pct) if row.weight_pct is not None else None
                ),
                asset_type=str(row.asset_class or ""),
                account_id=str(row.account_id or ""),
                account_name=str(row.account_name or bucket["name"]),
            )
            for row in bucket["all_rows"]
        )
        symbols = tuple(
            dict.fromkeys(str(row.symbol or "") for row in bucket["all_rows"] if row.symbol)
        )
        account_ids = tuple(bucket["account_ids"])
        cards.append(
            InstitutionCard(
                account_id=account_ids[0] if account_ids else "",
                name=str(bucket["name"]),
                currency=str(bucket["currency"] or base),
                securities_market_value=securities,
                cash_value=cash_value,
                cash_available=cash_available,
                total_value=total_value,
                portfolio_share_pct=_share_pct(total_value, portfolio_total),
                holdings_count=len(bucket["all_rows"]),
                symbols=symbols,
                holdings=holdings,
                account_ids=account_ids,
            )
        )

    cards.sort(key=lambda row: row.total_value, reverse=True)

    portfolio_cash_available = any(row.is_cash for row in view.priced_positions)
    portfolio_cash = (
        sum(float(row.market_value or 0.0) for row in view.priced_positions if row.is_cash)
        if portfolio_cash_available
        else None
    )
    securities_total = sum(card.securities_market_value for card in cards)
    top = cards[0] if cards and cards[0].total_value > 0 else None
    concentration = InstitutionConcentration(
        top_name=top.name if top else None,
        top_share_pct=top.portfolio_share_pct if top else None,
    )
    reliable = complete and top is not None
    return InstitutionCenterView(
        institutions=tuple(cards),
        totals=InstitutionCenterTotals(
            securities_market_value=securities_total,
            cash_value=portfolio_cash,
            cash_available=portfolio_cash_available,
            total_value=portfolio_total,
            base_currency=base,
        ),
        concentration=concentration,
        multi_institution_holdings=_multi_institution_holdings(groups),
        valuation_complete=complete,
        limitation=None if complete else INCOMPLETE_LIMITATION,
        brief_line=_brief_line(
            reliable=reliable,
            top_name=concentration.top_name,
            top_share_pct=concentration.top_share_pct,
        ),
    )


def _multi_institution_holdings(
    groups: Dict[str, Dict[str, Any]],
) -> Tuple[MultiInstitutionHolding, ...]:
    by_symbol: Dict[str, List[Tuple[str, str, float]]] = {}
    for bucket in groups.values():
        institution_name = str(bucket["name"])
        for row in bucket["all_rows"]:
            symbol = str(row.symbol or "").strip()
            if not symbol:
                continue
            account_label = str(row.account_name or institution_name)
            by_symbol.setdefault(symbol, []).append(
                (institution_name, account_label, float(row.quantity or 0.0))
            )

    rows: List[MultiInstitutionHolding] = []
    for symbol, items in by_symbol.items():
        institutions = tuple(dict.fromkeys(name for name, _, _ in items))
        if len(institutions) < 2:
            continue
        qty_by_account = tuple(
            (account_label, qty) for _, account_label, qty in items
        )
        rows.append(
            MultiInstitutionHolding(
                symbol=symbol,
                institutions=institutions,
                quantities_by_account=qty_by_account,
                total_quantity=sum(qty for _, qty in qty_by_account),
            )
        )
    rows.sort(key=lambda row: row.symbol)
    return tuple(rows)
