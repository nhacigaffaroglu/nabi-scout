from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from services.wealth_contract import (
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_FEE,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_WITHDRAW,
)
from services.wealth_performance_engine import _parse_ts, _reversed_original_ids_as_of


@dataclass(frozen=True)
class IncomeBySymbolRow:
    symbol: str
    total_income: float
    payment_count: int


@dataclass(frozen=True)
class IncomeByAccountRow:
    account_id: str
    account_label: str
    total_income: float


@dataclass(frozen=True)
class IncomeTimelinePoint:
    period_label: str
    amount: float


@dataclass(frozen=True)
class PortfolioIncomeSummary:
    base_currency: str
    total_dividends: float
    dividends_ytd: float
    trailing_twelve_months: float
    fee_total: float
    net_income: float
    income_yield_pct: Optional[float]
    portfolio_market_value: Optional[float]
    by_symbol: Tuple[IncomeBySymbolRow, ...]
    by_account: Tuple[IncomeByAccountRow, ...]
    timeline: Tuple[IncomeTimelinePoint, ...]
    limitations: Tuple[str, ...]


@dataclass(frozen=True)
class CashFlowSummary:
    base_currency: str
    total_deposits: float
    total_withdrawals: float
    total_dividends: float
    total_fees: float
    net_external_flow: float
    limitations: Tuple[str, ...]


def _active_txn_rows(
    transactions: Iterable[Dict[str, Any]],
    *,
    as_of: datetime,
) -> List[Dict[str, Any]]:
    txn_list = list(transactions)
    reversed_ids = _reversed_original_ids_as_of(txn_list, as_of)
    active: List[Dict[str, Any]] = []
    for row in txn_list:
        if row.get("reversal_of_id"):
            continue
        row_id = str(row.get("id") or "")
        if row_id and row_id in reversed_ids:
            continue
        active.append(row)
    return active


def _in_period(value: str, start: datetime, end: datetime) -> bool:
    executed_at = _parse_ts(value)
    return start <= executed_at <= end


def summarize_lifetime_cash_flows(
    transactions: Iterable[Dict[str, Any]],
    *,
    account_ids: Set[str],
    base_currency: str,
) -> CashFlowSummary:
    as_of = datetime.now(timezone.utc)
    start = datetime(1970, 1, 1, tzinfo=timezone.utc)
    limitations: List[str] = []
    deposits = withdrawals = dividends = fees = 0.0
    normalized = str(base_currency or "USD").strip().upper()

    for row in _active_txn_rows(transactions, as_of=as_of):
        if str(row.get("account_id") or "") not in account_ids:
            continue
        if str(row.get("currency") or normalized).strip().upper() != normalized:
            continue
        txn_type = str(row.get("txn_type") or "").strip().lower()
        amount = float(row.get("amount") or 0.0)
        if txn_type == TXN_TYPE_DEPOSIT:
            deposits += amount
        elif txn_type == TXN_TYPE_WITHDRAW:
            withdrawals += amount
        elif txn_type == TXN_TYPE_DIVIDEND:
            dividends += amount
        elif txn_type == TXN_TYPE_FEE:
            fees += amount

    return CashFlowSummary(
        base_currency=normalized,
        total_deposits=deposits,
        total_withdrawals=withdrawals,
        total_dividends=dividends,
        total_fees=fees,
        net_external_flow=deposits - withdrawals,
        limitations=tuple(limitations),
    )


def summarize_portfolio_income(
    transactions: Iterable[Dict[str, Any]],
    *,
    account_ids: Set[str],
    accounts_by_id: Dict[str, Dict[str, Any]],
    assets_by_id: Dict[str, Dict[str, Any]],
    base_currency: str,
    portfolio_market_value: Optional[float],
) -> PortfolioIncomeSummary:
    as_of = datetime.now(timezone.utc)
    year_start = datetime(as_of.year, 1, 1, tzinfo=timezone.utc)
    ttm_start = as_of.replace(year=as_of.year - 1) if as_of.year > 1971 else datetime(1970, 1, 1, tzinfo=timezone.utc)
    normalized = str(base_currency or "USD").strip().upper()

    total = ytd = ttm = fees = 0.0
    by_symbol: Dict[str, Tuple[float, int]] = {}
    by_account: Dict[str, float] = {}
    monthly: Dict[str, float] = {}

    for row in _active_txn_rows(transactions, as_of=as_of):
        account_id = str(row.get("account_id") or "")
        if account_id not in account_ids:
            continue
        if str(row.get("currency") or normalized).strip().upper() != normalized:
            continue
        executed_at = str(row.get("executed_at") or "")
        txn_type = str(row.get("txn_type") or "").strip().lower()
        amount = float(row.get("amount") or 0.0)

        if txn_type == TXN_TYPE_FEE:
            fees += amount
            continue
        if txn_type != TXN_TYPE_DIVIDEND:
            continue

        total += amount
        if _in_period(executed_at, year_start, as_of):
            ytd += amount
        if _in_period(executed_at, ttm_start, as_of):
            ttm += amount

        asset = assets_by_id.get(str(row.get("asset_id") or ""), {})
        symbol = str(asset.get("symbol") or "UNKNOWN").upper()
        prev_amt, prev_cnt = by_symbol.get(symbol, (0.0, 0))
        by_symbol[symbol] = (prev_amt + amount, prev_cnt + 1)
        by_account[account_id] = by_account.get(account_id, 0.0) + amount

        month_key = executed_at[:7] if len(executed_at) >= 7 else "unknown"
        monthly[month_key] = monthly.get(month_key, 0.0) + amount

    income_yield = None
    limitations: List[str] = []
    if portfolio_market_value and portfolio_market_value > 0 and ttm > 0:
        income_yield = (ttm / portfolio_market_value) * 100.0
    elif portfolio_market_value is None or portfolio_market_value <= 0:
        limitations.append("Gelir verimi için fiyatlı portföy değeri gerekli.")

    symbol_rows = tuple(
        IncomeBySymbolRow(symbol=sym, total_income=amt, payment_count=cnt)
        for sym, (amt, cnt) in sorted(by_symbol.items(), key=lambda item: -item[1][0])
    )
    account_rows = tuple(
        IncomeByAccountRow(
            account_id=acc_id,
            account_label=str(
                (accounts_by_id.get(acc_id) or {}).get("institution")
                or (accounts_by_id.get(acc_id) or {}).get("name")
                or acc_id
            ),
            total_income=amt,
        )
        for acc_id, amt in sorted(by_account.items(), key=lambda item: -item[1])
    )
    timeline = tuple(
        IncomeTimelinePoint(period_label=label, amount=amt)
        for label, amt in sorted(monthly.items())
    )

    return PortfolioIncomeSummary(
        base_currency=normalized,
        total_dividends=total,
        dividends_ytd=ytd,
        trailing_twelve_months=ttm,
        fee_total=fees,
        net_income=total - fees,
        income_yield_pct=income_yield,
        portfolio_market_value=portfolio_market_value,
        by_symbol=symbol_rows,
        by_account=account_rows,
        timeline=timeline,
        limitations=tuple(limitations),
    )
