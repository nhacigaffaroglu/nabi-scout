"""User-controlled purification and zakat math. No religious rulings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from services.portfolio_account_helpers import format_account_display
from services.portfolio_intelligence_contract import (
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_contract import TXN_TYPE_DIVIDEND
from services.wealth_income_service import _active_txn_rows
from services.wealth_snapshot_serializer import valuation_is_complete

STATUS_READY = "READY"
STATUS_MISSING_INPUT = "MISSING_INPUT"
STATUS_LIMITED = "LIMITED"

CASH_UNAVAILABLE = "Nakit verisi yok"
PARTIAL_VALUATION_LIMITATION = "Değerleme kısmi — gösterilen tutar alt sınırdır."
MISSING_PURIFICATION_RATIO = "Arındırma oranı girilmedi"
MISSING_ZAKAT_ELIGIBILITY = "Zekât dahil oranı girilmedi"
MISSING_MARKET_VALUE = "Güncel değer yok"
MISSING_BASIS = "Arındırma matrahı seçilmedi"

BRIEF_READY = "Arındırma/Zekât tahmini hazır."
BRIEF_MISSING = "Arındırma/Zekât verisi eksik."


class PurificationBasis(str, Enum):
    DIVIDEND_INCOME = "dividend_income"
    MARKET_VALUE = "market_value"


@dataclass(frozen=True)
class ProductAssumption:
    position_id: str
    purification_ratio_pct: Optional[float] = None
    zakat_eligible_pct: Optional[float] = None


@dataclass(frozen=True)
class PurificationZakatScenario:
    basis: Optional[PurificationBasis]
    zakat_rate_pct: Optional[float]
    include_all_eligible_at_100: bool = False
    assumptions: Tuple[ProductAssumption, ...] = ()


@dataclass(frozen=True)
class PurificationZakatRow:
    position_id: str
    symbol: str
    institution: str
    account_id: str
    is_cash: bool
    market_value: Optional[float]
    basis_value: Optional[float]
    purification_ratio_pct: Optional[float]
    purification_amount: Optional[float]
    zakat_eligible_pct: Optional[float]
    zakat_base: Optional[float]
    zakat_amount: Optional[float]
    status: str
    missing_notes: Tuple[str, ...]
    user_entered: bool


@dataclass(frozen=True)
class PurificationZakatResult:
    basis: Optional[PurificationBasis]
    zakat_rate_pct: Optional[float]
    include_all_eligible_at_100: bool
    valuation_complete: bool
    cash_available: bool
    estimated_purification: Optional[float]
    estimated_zakat: Optional[float]
    missing_input_count: int
    rows: Tuple[PurificationZakatRow, ...]
    limitations: Tuple[str, ...]
    brief_line: Optional[str]
    user_assumption_count: int


def _account_map(accounts: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(row.get("id") or ""): row for row in accounts if row.get("id")}


def _asset_map(assets: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(row.get("id") or ""): row for row in assets if row.get("id")}


def _institution_label(
    account_id: str,
    account_name: str,
    accounts_by_id: Mapping[str, Dict[str, Any]],
) -> str:
    account = accounts_by_id.get(str(account_id) or "")
    if account:
        institution = str(account.get("institution") or "").strip()
        if institution:
            return institution
        return format_account_display(account)
    return str(account_name or account_id or "—").strip() or "—"


def _iter_holdings(view: PortfolioIntelligenceView) -> Iterable[PositionValuationRow]:
    seen: set[str] = set()
    for row in (
        *view.priced_positions,
        *view.unpriced_positions,
        *view.foreign_currency_positions,
    ):
        marker = row.position_id or f"{row.account_id}:{row.symbol}:{id(row)}"
        if marker in seen:
            continue
        seen.add(marker)
        yield row


def _dividend_income_by_holding(
    transactions: Sequence[Dict[str, Any]],
    *,
    account_ids: set[str],
    assets_by_id: Mapping[str, Dict[str, Any]],
    base_currency: str,
) -> Dict[Tuple[str, str], float]:
    """Canonical dividend income only. Deposits and other flows are excluded."""
    from datetime import datetime, timezone

    as_of = datetime.now(timezone.utc)
    normalized = str(base_currency or "USD").strip().upper()
    totals: Dict[Tuple[str, str], float] = {}
    for row in _active_txn_rows(transactions, as_of=as_of):
        account_id = str(row.get("account_id") or "")
        if account_ids and account_id not in account_ids:
            continue
        if str(row.get("currency") or normalized).strip().upper() != normalized:
            continue
        if str(row.get("txn_type") or "").strip().lower() != TXN_TYPE_DIVIDEND:
            continue
        asset = assets_by_id.get(str(row.get("asset_id") or ""), {})
        symbol = str(asset.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        key = (account_id, symbol)
        totals[key] = totals.get(key, 0.0) + float(row.get("amount") or 0.0)
    return totals


def _assumption_map(
    assumptions: Sequence[ProductAssumption],
) -> Dict[str, ProductAssumption]:
    return {row.position_id: row for row in assumptions}


def _optional_pct(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def calculate_purification_zakat(
    view: PortfolioIntelligenceView,
    *,
    scenario: PurificationZakatScenario,
    accounts: Sequence[Dict[str, Any]] = (),
    assets: Sequence[Dict[str, Any]] = (),
    transactions: Sequence[Dict[str, Any]] = (),
) -> PurificationZakatResult:
    """Apply explicit user assumptions to canonical holdings and dividend income."""
    accounts_by_id = _account_map(accounts)
    assets_by_id = _asset_map(assets)
    assumptions = _assumption_map(scenario.assumptions)
    complete = valuation_is_complete(view)
    base = str(view.base_currency or "USD").strip().upper()
    priced_ids = {id(row) for row in view.priced_positions}
    account_ids = {
        str(row.account_id or "")
        for row in _iter_holdings(view)
        if row.account_id
    }
    dividends = _dividend_income_by_holding(
        transactions,
        account_ids=account_ids,
        assets_by_id=assets_by_id,
        base_currency=base,
    )
    cash_available = any(row.is_cash for row in view.priced_positions)

    rows: list[PurificationZakatRow] = []
    purification_total = 0.0
    purification_any = False
    zakat_total = 0.0
    zakat_any = False
    missing = 0
    user_assumption_count = 0

    for holding in _iter_holdings(view):
        assumption = assumptions.get(holding.position_id)
        ratio = _optional_pct(assumption.purification_ratio_pct if assumption else None)
        entered_eligible = _optional_pct(
            assumption.zakat_eligible_pct if assumption else None
        )
        if ratio is not None or entered_eligible is not None:
            user_assumption_count += 1
        eligible = entered_eligible
        if eligible is None and scenario.include_all_eligible_at_100:
            eligible = 100.0

        priced = id(holding) in priced_ids
        market_value = (
            float(holding.market_value)
            if priced and holding.market_value is not None
            else None
        )
        notes: list[str] = []
        if not complete:
            notes.append(PARTIAL_VALUATION_LIMITATION)
        if holding.is_cash and not cash_available:
            notes.append(CASH_UNAVAILABLE)

        basis_value: Optional[float] = None
        if scenario.basis is None:
            notes.append(MISSING_BASIS)
        elif scenario.basis is PurificationBasis.MARKET_VALUE:
            basis_value = market_value
            if basis_value is None:
                notes.append(MISSING_MARKET_VALUE)
        else:
            basis_value = dividends.get(
                (str(holding.account_id or ""), str(holding.symbol or "").upper()),
                0.0,
            )

        purification_amount: Optional[float] = None
        if ratio is None:
            notes.append(MISSING_PURIFICATION_RATIO)
        elif basis_value is not None:
            purification_amount = basis_value * (ratio / 100.0)
            purification_total += purification_amount
            purification_any = True

        zakat_base: Optional[float] = None
        zakat_amount: Optional[float] = None
        if eligible is None:
            notes.append(MISSING_ZAKAT_ELIGIBILITY)
        elif market_value is None:
            notes.append(MISSING_MARKET_VALUE)
        else:
            zakat_base = market_value * (eligible / 100.0)
            if scenario.zakat_rate_pct is None:
                notes.append("Zekât oranı girilmedi")
            else:
                zakat_amount = zakat_base * (float(scenario.zakat_rate_pct) / 100.0)
                zakat_total += zakat_amount
                zakat_any = True

        missing_notes = tuple(
            note
            for note in notes
            if note
            in {MISSING_PURIFICATION_RATIO, MISSING_ZAKAT_ELIGIBILITY, MISSING_BASIS}
        )
        if missing_notes:
            missing += 1
            status = STATUS_MISSING_INPUT
        elif not complete or market_value is None:
            status = STATUS_LIMITED
        else:
            status = STATUS_READY

        rows.append(
            PurificationZakatRow(
                position_id=str(holding.position_id or ""),
                symbol=str(holding.symbol or ""),
                institution=_institution_label(
                    holding.account_id, holding.account_name, accounts_by_id
                ),
                account_id=str(holding.account_id or ""),
                is_cash=bool(holding.is_cash),
                market_value=market_value,
                basis_value=basis_value,
                purification_ratio_pct=ratio,
                purification_amount=purification_amount,
                zakat_eligible_pct=eligible,
                zakat_base=zakat_base,
                zakat_amount=zakat_amount,
                status=status,
                missing_notes=tuple(dict.fromkeys(notes)),
                user_entered=assumption is not None,
            )
        )

    limitations: list[str] = []
    if not complete:
        limitations.append(PARTIAL_VALUATION_LIMITATION)
    if not cash_available:
        limitations.append(CASH_UNAVAILABLE)
    if scenario.basis is None:
        limitations.append(MISSING_BASIS)

    started = user_assumption_count > 0 or scenario.include_all_eligible_at_100
    brief_line = None
    if started:
        brief_line = BRIEF_READY if missing == 0 and complete else BRIEF_MISSING

    return PurificationZakatResult(
        basis=scenario.basis,
        zakat_rate_pct=scenario.zakat_rate_pct,
        include_all_eligible_at_100=scenario.include_all_eligible_at_100,
        valuation_complete=complete,
        cash_available=cash_available,
        estimated_purification=purification_total if purification_any else None,
        estimated_zakat=zakat_total if zakat_any else None,
        missing_input_count=missing,
        rows=tuple(rows),
        limitations=tuple(dict.fromkeys(limitations)),
        brief_line=brief_line,
        user_assumption_count=user_assumption_count,
    )
