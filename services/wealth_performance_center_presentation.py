"""Performance Center presentation. No new return engine or Dietz math."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.wealth_contribution_intelligence import PerformanceEvidenceQuality
from services.wealth_external_cash_flow import ContributionReconciliation
from services.wealth_history_service import (
    WealthHistoryState,
    WealthHistoryView,
    build_wealth_history,
)
from services.wealth_timeline_contract import PortfolioSnapshotView

SECTION_TITLE = "Performans Merkezi"
DETAILS_EXPANDER = "Geçmiş ve teknik detaylar"
INSUFFICIENT_COPY = "Bu dönem için yeterli karşılaştırılabilir geçmiş yok."
PARTIAL_PAIR_COPY = (
    "Seçilen dönemdeki görüntüler kısmi veya karşılaştırılabilir değil; "
    "getiri üretilmedi."
)
BEST_LABEL = "En iyi 5"
WEAKEST_LABEL = "En zayıf 5"
STATUS_COMPARABLE = "Karşılaştırılabilir"
STATUS_MISSING = "Uç eksik"
STATUS_NO_PRICE = "Fiyat yok"
STATUS_QTY_CHANGED = "Miktar değişti"
STATUS_PARTIAL = "Kısmi değerleme"
STATUS_INCOMPARABLE = "Karşılaştırılamaz"


class PerformancePeriod(str, Enum):
    DAILY = "Günlük"
    WEEKLY = "Haftalık"
    MONTHLY = "Aylık"
    YEARLY = "Yıllık"
    ALL = "Tümü"


PERIOD_OPTIONS = (
    PerformancePeriod.DAILY,
    PerformancePeriod.WEEKLY,
    PerformancePeriod.MONTHLY,
    PerformancePeriod.YEARLY,
    PerformancePeriod.ALL,
)


@dataclass(frozen=True)
class ProductPeriodRow:
    symbol: str
    asset_class: str
    start_price: Optional[Decimal]
    end_price: Optional[Decimal]
    period_return: Optional[Decimal]
    comparable: bool
    status: str


@dataclass(frozen=True)
class AssetClassPeriodRow:
    asset_class: str
    comparable_count: int
    average_price_return: Optional[Decimal]


@dataclass(frozen=True)
class PerformanceCenterView:
    period: PerformancePeriod
    sufficient: bool
    insufficient_reason: str
    history: Optional[WealthHistoryView]
    start_snapshot_at: Optional[str]
    end_snapshot_at: Optional[str]
    products: Tuple[ProductPeriodRow, ...]
    best: Tuple[ProductPeriodRow, ...]
    weakest: Tuple[ProductPeriodRow, ...]
    asset_classes: Tuple[AssetClassPeriodRow, ...]
    pair_comparable: bool


def _parse_ts(value: Any) -> Optional[datetime]:
    text = str(value or "").replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _chronological(snapshots: Sequence[PortfolioSnapshotView]) -> List[PortfolioSnapshotView]:
    return sorted(
        snapshots,
        key=lambda row: _parse_ts(row.captured_at) or datetime.min.replace(tzinfo=timezone.utc),
    )


def _shift_month(moment: datetime, *, months: int) -> datetime:
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def _window_bound(end: datetime, period: PerformancePeriod) -> Optional[datetime]:
    if period == PerformancePeriod.ALL:
        return None
    if period == PerformancePeriod.DAILY:
        return end.replace(microsecond=0) - timedelta(days=1)
    if period == PerformancePeriod.WEEKLY:
        return end.replace(microsecond=0) - timedelta(days=7)
    if period == PerformancePeriod.MONTHLY:
        return _shift_month(end, months=-1)
    if period == PerformancePeriod.YEARLY:
        return _shift_month(end, months=-12)
    return None


def select_period_snapshots(
    snapshots: Sequence[PortfolioSnapshotView],
    period: PerformancePeriod,
) -> Tuple[Optional[PortfolioSnapshotView], Optional[PortfolioSnapshotView]]:
    """Latest end snapshot and latest start snapshot on/before the window bound."""
    ordered = _chronological(snapshots)
    if len(ordered) < 2:
        return None, None
    end = ordered[-1]
    end_at = _parse_ts(end.captured_at)
    if end_at is None:
        return None, None
    if period == PerformancePeriod.ALL:
        start = ordered[0]
        if start.id == end.id:
            return None, None
        return start, end
    bound = _window_bound(end_at, period)
    if bound is None:
        return None, None
    start = None
    for row in ordered:
        captured = _parse_ts(row.captured_at)
        if captured is None or captured.date() > bound.date():
            continue
        if row.id == end.id:
            continue
        start = row
    if start is None:
        return None, None
    return start, end


def _window_snapshots(
    snapshots: Sequence[PortfolioSnapshotView],
    start: PortfolioSnapshotView,
    end: PortfolioSnapshotView,
) -> List[PortfolioSnapshotView]:
    start_at = _parse_ts(start.captured_at)
    end_at = _parse_ts(end.captured_at)
    window: List[PortfolioSnapshotView] = []
    for row in _chronological(snapshots):
        captured = _parse_ts(row.captured_at)
        if captured is None or start_at is None or end_at is None:
            continue
        if start_at <= captured <= end_at:
            window.append(row)
    return window


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _positions_by_symbol(snap: PortfolioSnapshotView) -> Dict[str, Dict[str, Any]]:
    payload = dict(snap.valuation_payload or {})
    rows = payload.get("priced_positions") or []
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for raw in rows:
        symbol = str(raw.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        by_symbol[symbol] = dict(raw)
    return by_symbol


def _product_rows(
    start: PortfolioSnapshotView,
    end: PortfolioSnapshotView,
    *,
    pair_comparable: bool,
) -> Tuple[ProductPeriodRow, ...]:
    start_pos = _positions_by_symbol(start)
    end_pos = _positions_by_symbol(end)
    symbols = sorted(set(start_pos) | set(end_pos))
    rows: List[ProductPeriodRow] = []
    for symbol in symbols:
        left = start_pos.get(symbol)
        right = end_pos.get(symbol)
        asset_class = str(
            (right or left or {}).get("asset_class") or ""
        ).strip() or "—"
        if (left or {}).get("is_cash") or (right or {}).get("is_cash"):
            continue
        start_price = _dec((left or {}).get("price"))
        end_price = _dec((right or {}).get("price"))
        start_qty = _dec((left or {}).get("quantity"))
        end_qty = _dec((right or {}).get("quantity"))
        if not pair_comparable:
            status = STATUS_PARTIAL if not pair_comparable else STATUS_INCOMPARABLE
            if left is None or right is None:
                status = STATUS_MISSING
            rows.append(
                ProductPeriodRow(
                    symbol=symbol,
                    asset_class=asset_class,
                    start_price=start_price,
                    end_price=end_price,
                    period_return=None,
                    comparable=False,
                    status=status,
                )
            )
            continue
        if left is None or right is None:
            rows.append(
                ProductPeriodRow(
                    symbol=symbol,
                    asset_class=asset_class,
                    start_price=start_price,
                    end_price=end_price,
                    period_return=None,
                    comparable=False,
                    status=STATUS_MISSING,
                )
            )
            continue
        if (
            start_price is None
            or end_price is None
            or start_price <= 0
            or end_price <= 0
        ):
            rows.append(
                ProductPeriodRow(
                    symbol=symbol,
                    asset_class=asset_class,
                    start_price=start_price,
                    end_price=end_price,
                    period_return=None,
                    comparable=False,
                    status=STATUS_NO_PRICE,
                )
            )
            continue
        if start_qty is None or end_qty is None or start_qty != end_qty:
            rows.append(
                ProductPeriodRow(
                    symbol=symbol,
                    asset_class=asset_class,
                    start_price=start_price,
                    end_price=end_price,
                    period_return=None,
                    comparable=False,
                    status=STATUS_QTY_CHANGED,
                )
            )
            continue
        period_return = end_price / start_price - Decimal("1")
        rows.append(
            ProductPeriodRow(
                symbol=symbol,
                asset_class=asset_class,
                start_price=start_price,
                end_price=end_price,
                period_return=period_return,
                comparable=True,
                status=STATUS_COMPARABLE,
            )
        )
    return tuple(rows)


def _rank(products: Sequence[ProductPeriodRow]) -> Tuple[ProductPeriodRow, ...]:
    comparable = [row for row in products if row.comparable and row.period_return is not None]
    return tuple(sorted(comparable, key=lambda row: row.period_return, reverse=True))


def _asset_class_rows(ranked: Sequence[ProductPeriodRow]) -> Tuple[AssetClassPeriodRow, ...]:
    grouped: Dict[str, List[Decimal]] = {}
    for row in ranked:
        if row.period_return is None:
            continue
        grouped.setdefault(row.asset_class, []).append(row.period_return)
    out: List[AssetClassPeriodRow] = []
    for name in sorted(grouped):
        values = grouped[name]
        average = sum(values, Decimal("0")) / Decimal(len(values))
        out.append(
            AssetClassPeriodRow(
                asset_class=name,
                comparable_count=len(values),
                average_price_return=average,
            )
        )
    return tuple(out)


def build_performance_center(
    snapshots: Sequence[PortfolioSnapshotView],
    *,
    period: PerformancePeriod = PerformancePeriod.ALL,
    transactions: Iterable[Dict[str, Any]] = (),
    account_ids: Sequence[str] = (),
    contribution_reconciliations: Sequence[ContributionReconciliation] | None = None,
    portfolio_id: Optional[str] = None,
    transaction_history_complete: bool = True,
) -> PerformanceCenterView:
    start, end = select_period_snapshots(snapshots, period)
    if start is None or end is None:
        return PerformanceCenterView(
            period=period,
            sufficient=False,
            insufficient_reason=INSUFFICIENT_COPY,
            history=None,
            start_snapshot_at=None,
            end_snapshot_at=None,
            products=(),
            best=(),
            weakest=(),
            asset_classes=(),
            pair_comparable=False,
        )
    window = _window_snapshots(snapshots, start, end)
    history = build_wealth_history(
        window,
        transactions=transactions,
        account_ids=account_ids,
        transaction_history_complete=transaction_history_complete,
        contribution_reconciliations=contribution_reconciliations,
        portfolio_id=portfolio_id,
    )
    pair_comparable = (
        history.history_state == WealthHistoryState.COMPARABLE
        and history.valuation_complete_start
        and history.valuation_complete_end
        and history.evidence_quality != PerformanceEvidenceQuality.UNAVAILABLE
    )
    if history.history_state != WealthHistoryState.COMPARABLE:
        pair_comparable = False
    products = _product_rows(start, end, pair_comparable=pair_comparable)
    ranked = _rank(products)
    weakest = tuple(reversed(ranked[-5:])) if ranked else ()
    sufficient = True
    reason = ""
    if history.history_state != WealthHistoryState.COMPARABLE:
        sufficient = False
        reason = INSUFFICIENT_COPY
        if history.limitations:
            reason = PARTIAL_PAIR_COPY
    return PerformanceCenterView(
        period=period,
        sufficient=sufficient,
        insufficient_reason=reason,
        history=history,
        start_snapshot_at=start.captured_at,
        end_snapshot_at=end.captured_at,
        products=products,
        best=ranked[:5],
        weakest=weakest,
        asset_classes=_asset_class_rows(ranked),
        pair_comparable=pair_comparable,
    )
