from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from services.wealth_contract import (
    TXN_TYPE_BUY,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_FEE,
    TXN_TYPE_SELL,
    TXN_TYPE_WITHDRAW,
)
from services.wealth_timeline_contract import PortfolioPerformancePeriod, PortfolioSnapshotView


def _parse_ts(value: str) -> datetime:
    normalized = str(value or "").replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _normalize_currency(code: str | None) -> str:
    return str(code or "USD").strip().upper()


def snapshot_view_from_row(row: Dict[str, Any]) -> PortfolioSnapshotView:
    return PortfolioSnapshotView(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        portfolio_id=str(row["portfolio_id"]),
        captured_at=str(row["captured_at"]),
        base_currency=_normalize_currency(row.get("base_currency")),
        priced_market_value=float(row.get("priced_market_value") or 0.0),
        total_cost_basis=float(row.get("total_cost_basis") or 0.0),
        unrealized_pl=float(row.get("unrealized_pl") or 0.0),
        cash_value=float(row.get("cash_value") or 0.0),
        invested_value=float(row.get("invested_value") or 0.0),
        liabilities_total=(
            float(row["liabilities_total"])
            if row.get("liabilities_total") is not None
            else None
        ),
        net_wealth_partial=(
            float(row["net_wealth_partial"])
            if row.get("net_wealth_partial") is not None
            else None
        ),
        priced_position_coverage_pct=float(row.get("priced_position_coverage_pct") or 0.0),
        unpriced_position_count=int(row.get("unpriced_position_count") or 0),
        mixed_currency_warning=bool(row.get("mixed_currency_warning")),
        valuation_payload=dict(row.get("valuation_payload") or {}),
        created_at=str(row.get("created_at") or ""),
    )


def _txn_in_period(
    executed_at: datetime,
    *,
    period_start: datetime,
    period_end: datetime,
) -> bool:
    """Period cash-flow window: T1 < executed_at <= T2."""
    return period_start < executed_at <= period_end


def _reversed_original_ids_as_of(
    transactions: Iterable[Dict[str, Any]],
    as_of: datetime,
) -> Set[str]:
    """Original txn ids reversed on or before as_of (as-of end snapshot)."""
    reversed_ids: Set[str] = set()
    for row in transactions:
        reversal_of = row.get("reversal_of_id")
        if not reversal_of:
            continue
        executed_at = _parse_ts(str(row.get("executed_at") or ""))
        if executed_at <= as_of:
            reversed_ids.add(str(reversal_of))
    return reversed_ids


def _apply_flow_amount(
    txn_type: str,
    amount: float,
    *,
    inflows: float,
    outflows: float,
    dividend_income: float,
    fee_cost: float,
    sign: int,
) -> Tuple[float, float, float, float]:
    if txn_type in {TXN_TYPE_BUY, TXN_TYPE_SELL}:
        return inflows, outflows, dividend_income, fee_cost

    if txn_type == TXN_TYPE_DEPOSIT:
        if sign > 0:
            inflows += amount
        else:
            outflows += amount
    elif txn_type == TXN_TYPE_WITHDRAW:
        if sign > 0:
            outflows += amount
        else:
            inflows += amount
    elif txn_type == TXN_TYPE_DIVIDEND:
        dividend_income += amount * sign
    elif txn_type == TXN_TYPE_FEE:
        fee_cost += amount * sign

    return inflows, outflows, dividend_income, fee_cost


def aggregate_cash_flows(
    transactions: Iterable[Dict[str, Any]],
    *,
    account_ids: Set[str],
    base_currency: str,
    period_start: datetime,
    period_end: datetime,
) -> Tuple[float, float, float, float, List[str]]:
    """As-of period_end external cash-flow aggregation.

    Invariant: include cash effects with T1 < executed_at <= T2.
    Reversal pairs use end-of-period knowledge only; a reversal after T2
    does not cancel an in-period deposit for this period.
    """
    normalized_base = _normalize_currency(base_currency)
    txn_list = list(transactions)
    by_id = {str(row["id"]): row for row in txn_list if row.get("id")}
    reversed_as_of_end = _reversed_original_ids_as_of(txn_list, period_end)

    def _has_in_period_reversal(original_id: str) -> bool:
        for candidate in txn_list:
            if str(candidate.get("reversal_of_id") or "") != original_id:
                continue
            rev_at = _parse_ts(str(candidate.get("executed_at") or ""))
            if _txn_in_period(rev_at, period_start=period_start, period_end=period_end):
                return True
        return False

    inflows = 0.0
    outflows = 0.0
    dividend_income = 0.0
    fee_cost = 0.0
    warnings: List[str] = []

    for row in txn_list:
        account_id = str(row.get("account_id") or "")
        if account_id not in account_ids:
            continue

        executed_at = _parse_ts(str(row.get("executed_at") or ""))
        reversal_of = row.get("reversal_of_id")

        if reversal_of:
            if not _txn_in_period(
                executed_at,
                period_start=period_start,
                period_end=period_end,
            ):
                continue
            original = by_id.get(str(reversal_of))
            if original is None:
                continue
            txn_type = str(original.get("txn_type") or "").strip().lower()
            amount = float(original.get("amount") or 0.0)
            txn_currency = _normalize_currency(original.get("currency"))
            if txn_currency != normalized_base:
                warnings.append(
                    f"Skipped reversal of {txn_type} in {txn_currency}; only "
                    f"{normalized_base} external flows are counted."
                )
                continue
            inflows, outflows, dividend_income, fee_cost = _apply_flow_amount(
                txn_type,
                amount,
                inflows=inflows,
                outflows=outflows,
                dividend_income=dividend_income,
                fee_cost=fee_cost,
                sign=-1,
            )
            continue

        if not _txn_in_period(
            executed_at,
            period_start=period_start,
            period_end=period_end,
        ):
            continue

        row_id = str(row.get("id") or "")
        if row_id in reversed_as_of_end and not _has_in_period_reversal(row_id):
            continue

        txn_type = str(row.get("txn_type") or "").strip().lower()
        amount = float(row.get("amount") or 0.0)
        txn_currency = _normalize_currency(row.get("currency"))

        if txn_type in {TXN_TYPE_BUY, TXN_TYPE_SELL}:
            continue

        if txn_currency != normalized_base:
            warnings.append(
                f"Skipped {txn_type} in {txn_currency}; only {normalized_base} "
                "external flows are counted."
            )
            continue

        inflows, outflows, dividend_income, fee_cost = _apply_flow_amount(
            txn_type,
            amount,
            inflows=inflows,
            outflows=outflows,
            dividend_income=dividend_income,
            fee_cost=fee_cost,
            sign=1,
        )

    return inflows, outflows, dividend_income, fee_cost, warnings


@dataclass(frozen=True)
class TimedCashFlow:
    executed_at: datetime
    signed_amount: float


def _signed_external_flow_amount(txn_type: str, amount: float, *, sign: int) -> Optional[float]:
    if txn_type == TXN_TYPE_DEPOSIT:
        return amount * sign
    if txn_type == TXN_TYPE_WITHDRAW:
        return -amount * sign
    return None


def collect_timed_external_flows(
    transactions: Iterable[Dict[str, Any]],
    *,
    account_ids: Set[str],
    base_currency: str,
    period_start: datetime,
    period_end: datetime,
) -> List[TimedCashFlow]:
    """Signed external flows in period: deposit positive, withdraw negative."""
    normalized_base = _normalize_currency(base_currency)
    txn_list = list(transactions)
    by_id = {str(row["id"]): row for row in txn_list if row.get("id")}
    reversed_as_of_end = _reversed_original_ids_as_of(txn_list, period_end)

    def _has_in_period_reversal(original_id: str) -> bool:
        for candidate in txn_list:
            if str(candidate.get("reversal_of_id") or "") != original_id:
                continue
            rev_at = _parse_ts(str(candidate.get("executed_at") or ""))
            if _txn_in_period(rev_at, period_start=period_start, period_end=period_end):
                return True
        return False

    flows: List[TimedCashFlow] = []

    for row in txn_list:
        account_id = str(row.get("account_id") or "")
        if account_id not in account_ids:
            continue

        executed_at = _parse_ts(str(row.get("executed_at") or ""))
        reversal_of = row.get("reversal_of_id")

        if reversal_of:
            if not _txn_in_period(
                executed_at,
                period_start=period_start,
                period_end=period_end,
            ):
                continue
            original = by_id.get(str(reversal_of))
            if original is None:
                continue
            txn_type = str(original.get("txn_type") or "").strip().lower()
            amount = float(original.get("amount") or 0.0)
            txn_currency = _normalize_currency(original.get("currency"))
            if txn_currency != normalized_base:
                continue
            signed = _signed_external_flow_amount(txn_type, amount, sign=-1)
            if signed is None:
                continue
            flows.append(TimedCashFlow(executed_at=executed_at, signed_amount=signed))
            continue

        if not _txn_in_period(
            executed_at,
            period_start=period_start,
            period_end=period_end,
        ):
            continue

        row_id = str(row.get("id") or "")
        if row_id in reversed_as_of_end and not _has_in_period_reversal(row_id):
            continue

        txn_type = str(row.get("txn_type") or "").strip().lower()
        amount = float(row.get("amount") or 0.0)
        txn_currency = _normalize_currency(row.get("currency"))

        if txn_type in {TXN_TYPE_BUY, TXN_TYPE_SELL}:
            continue
        if txn_currency != normalized_base:
            continue

        signed = _signed_external_flow_amount(txn_type, amount, sign=1)
        if signed is None:
            continue
        flows.append(TimedCashFlow(executed_at=executed_at, signed_amount=signed))

    flows.sort(key=lambda flow: flow.executed_at)
    return flows


def modified_dietz_denominator(
    *,
    start_value: float,
    timed_flows: Iterable[TimedCashFlow],
    period_start: datetime,
    period_end: datetime,
) -> Optional[float]:
    duration_seconds = (period_end - period_start).total_seconds()
    if duration_seconds <= 0:
        return None

    denominator = start_value
    for flow in timed_flows:
        remaining_seconds = (period_end - flow.executed_at).total_seconds()
        if remaining_seconds < 0:
            continue
        weight = remaining_seconds / duration_seconds
        denominator += weight * flow.signed_amount
    return denominator


def build_performance_period(
    *,
    start: PortfolioSnapshotView,
    end: PortfolioSnapshotView,
    transactions: Iterable[Dict[str, Any]],
    account_ids: Set[str],
    transaction_history_complete: bool = True,
) -> PortfolioPerformancePeriod:
    warnings: List[str] = []
    start_at = _parse_ts(start.captured_at)
    end_at = _parse_ts(end.captured_at)

    if start_at >= end_at:
        warnings.append("Dönem başlangıcı bitişten önce olmalıdır.")
    if _normalize_currency(start.base_currency) != _normalize_currency(end.base_currency):
        warnings.append("Görüntü baz para birimleri farklı.")
    if start.mixed_currency_warning or end.mixed_currency_warning:
        warnings.append("Karışık para birimli görüntüler tam karşılaştırılamaz.")
    if start.unpriced_position_count > 0 or end.unpriced_position_count > 0:
        warnings.append("Başlangıç veya bitişte fiyatsız pozisyon var.")
    if start.priced_position_coverage_pct < 100.0 or end.priced_position_coverage_pct < 100.0:
        warnings.append("Başlangıç veya bitişte fiyatlı pozisyon kapsamı eksik.")
    if not transaction_history_complete:
        warnings.append(
            "İşlem geçmişi eksik olabilir; dış akış toplamlarına güvenilmiyor."
        )

    inflows, outflows, dividend_income, fee_cost, flow_warnings = aggregate_cash_flows(
        transactions,
        account_ids=account_ids,
        base_currency=start.base_currency,
        period_start=start_at,
        period_end=end_at,
    )
    warnings.extend(flow_warnings)

    net_external_flow = inflows - outflows
    start_value = start.priced_market_value
    end_value = end.priced_market_value
    portfolio_value_change = end_value - start_value
    investment_gain = end_value - start_value - net_external_flow

    performance_comparable = not warnings and start_at < end_at

    simple_period_return_pct: Optional[float] = None
    if (
        performance_comparable
        and start_value > 0
        and abs(net_external_flow) < 1e-9
    ):
        simple_period_return_pct = (investment_gain / start_value) * 100.0

    return PortfolioPerformancePeriod(
        period_start_at=start.captured_at,
        period_end_at=end.captured_at,
        base_currency=_normalize_currency(start.base_currency),
        start_priced_value=start_value,
        end_priced_value=end_value,
        portfolio_value_change=portfolio_value_change,
        external_inflows=inflows,
        external_outflows=outflows,
        net_external_flow=net_external_flow,
        investment_gain=investment_gain,
        dividend_income=dividend_income,
        fee_cost=fee_cost,
        start_coverage_pct=start.priced_position_coverage_pct,
        end_coverage_pct=end.priced_position_coverage_pct,
        start_unpriced_count=start.unpriced_position_count,
        end_unpriced_count=end.unpriced_position_count,
        performance_comparable=performance_comparable,
        simple_period_return_pct=simple_period_return_pct,
        warnings=warnings,
    )
