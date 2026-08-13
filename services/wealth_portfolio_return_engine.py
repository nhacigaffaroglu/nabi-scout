from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Set, Tuple

from services.wealth_performance_engine import (
    _parse_ts,
    build_performance_period,
    collect_timed_external_flows,
    modified_dietz_denominator,
)
from services.wealth_timeline_contract import (
    PortfolioLinkedPerformance,
    PortfolioPerformancePeriod,
    PortfolioSnapshotView,
)


def compute_subperiod_return_decimal(
    *,
    start_value: float,
    end_value: float,
    net_external_flow: float,
    timed_flows: Optional[List] = None,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
) -> Optional[float]:
    """Chainable subperiod return using timestamp-weighted Modified Dietz.

    investment_gain = end - start - net_external_flow
    denominator = start + Σ(weight_i * flow_i), weight_i = (T2 - t_i) / (T2 - T1)
    """
    investment_gain = end_value - start_value - net_external_flow
    if abs(net_external_flow) < 1e-9:
        if start_value <= 1e-9:
            return None
        return investment_gain / start_value

    if timed_flows is not None and period_start is not None and period_end is not None:
        denominator = modified_dietz_denominator(
            start_value=start_value,
            timed_flows=timed_flows,
            period_start=period_start,
            period_end=period_end,
        )
    else:
        denominator = start_value + 0.5 * net_external_flow

    if denominator is None or denominator <= 1e-9:
        return None
    return investment_gain / denominator


def compute_subperiod_return_for_period(
    period: PortfolioPerformancePeriod,
    *,
    transactions: Iterable[dict],
    account_ids: Set[str],
) -> Optional[float]:
    period_start = _parse_ts(period.period_start_at)
    period_end = _parse_ts(period.period_end_at)
    timed_flows = collect_timed_external_flows(
        transactions,
        account_ids=account_ids,
        base_currency=period.base_currency,
        period_start=period_start,
        period_end=period_end,
    )
    return compute_subperiod_return_decimal(
        start_value=period.start_priced_value,
        end_value=period.end_priced_value,
        net_external_flow=period.net_external_flow,
        timed_flows=timed_flows,
        period_start=period_start,
        period_end=period_end,
    )


def chain_linked_return_pct(subperiod_returns: Iterable[float]) -> Optional[float]:
    product = 1.0
    count = 0
    for subperiod_return in subperiod_returns:
        product *= 1.0 + subperiod_return
        count += 1
    if count == 0:
        return None
    return (product - 1.0) * 100.0


def build_linked_performance(
    *,
    snapshots_chronological: List[PortfolioSnapshotView],
    transactions: Iterable[dict],
    account_ids: Set[str],
    transaction_history_complete: bool,
) -> Optional[PortfolioLinkedPerformance]:
    if len(snapshots_chronological) < 2:
        return None

    txn_list = list(transactions)
    subperiods: List[PortfolioPerformancePeriod] = []
    subperiod_returns: List[float] = []
    warnings: List[str] = []
    performance_comparable = True

    for index in range(len(snapshots_chronological) - 1):
        start = snapshots_chronological[index]
        end = snapshots_chronological[index + 1]
        period = build_performance_period(
            start=start,
            end=end,
            transactions=txn_list,
            account_ids=account_ids,
            transaction_history_complete=transaction_history_complete,
        )
        subperiods.append(period)
        if not period.performance_comparable:
            performance_comparable = False
            warnings.extend(period.warnings)
            continue

        subperiod_return = compute_subperiod_return_for_period(
            period,
            transactions=txn_list,
            account_ids=account_ids,
        )
        if subperiod_return is None:
            performance_comparable = False
            warnings.append(
                f"Subperiod {period.period_start_at} → {period.period_end_at} "
                "return denominator is not positive."
            )
            continue
        subperiod_returns.append(subperiod_return)

    linked_return_pct: Optional[float] = None
    if (
        performance_comparable
        and subperiod_returns
        and len(subperiod_returns) == len(subperiods)
    ):
        linked_return_pct = chain_linked_return_pct(subperiod_returns)

    first = snapshots_chronological[0]
    last = snapshots_chronological[-1]

    return PortfolioLinkedPerformance(
        period_start_at=first.captured_at,
        period_end_at=last.captured_at,
        base_currency=first.base_currency,
        subperiod_count=len(subperiods),
        linked_return_pct=linked_return_pct,
        performance_comparable=performance_comparable and linked_return_pct is not None,
        warnings=sorted(set(warnings)),
        subperiods=subperiods,
    )


def build_portfolio_index_series(
    *,
    snapshots_chronological: List[PortfolioSnapshotView],
    linked: PortfolioLinkedPerformance,
    transactions: Iterable[dict],
    account_ids: Set[str],
) -> List[Tuple[str, Optional[float]]]:
    """Normalized portfolio index (100 at first snapshot) from chain-linked returns."""
    if not snapshots_chronological:
        return []

    series: List[Tuple[str, Optional[float]]] = [
        (snapshots_chronological[0].captured_at, 100.0),
    ]
    if not linked.performance_comparable:
        for snap in snapshots_chronological[1:]:
            series.append((snap.captured_at, None))
        return series

    txn_list = list(transactions)
    index_value = 100.0
    for period in linked.subperiods:
        subperiod_return = compute_subperiod_return_for_period(
            period,
            transactions=txn_list,
            account_ids=account_ids,
        )
        if subperiod_return is None:
            series.append((period.period_end_at, None))
            continue
        index_value *= 1.0 + subperiod_return
        series.append((period.period_end_at, index_value))

    return series
