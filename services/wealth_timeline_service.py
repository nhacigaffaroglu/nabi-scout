from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from repositories.wealth_portfolio_snapshot_repository import (
    WealthPortfolioSnapshotRepository,
)
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_core_service import WealthCoreService
from services.wealth_performance_engine import (
    build_performance_period,
    snapshot_view_from_row,
)
from services.wealth_contract import WealthValidationError
from services.wealth_snapshot_serializer import snapshot_row_from_intelligence_view
from services.wealth_benchmark_service import WealthBenchmarkService
from services.wealth_portfolio_return_engine import (
    build_linked_performance,
    build_portfolio_index_series,
)
from services.wealth_timeline_contract import (
    BenchmarkComparisonView,
    PortfolioHistoryPoint,
    PortfolioLinkedPerformance,
    PortfolioPerformancePeriod,
    PortfolioSnapshotView,
    WealthPerformanceView,
    WealthTimelineView,
)

TXN_HISTORY_LIMIT = 5000


class WealthTimelineService:
    """Explicit snapshot persistence and performance comparison."""

    def __init__(self, wealth: WealthCoreService):
        self.wealth = wealth
        self.snapshots = WealthPortfolioSnapshotRepository(wealth.client)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _liabilities_total_for_portfolio(
        self,
        portfolio_id: str,
        base_currency: str,
    ) -> float:
        base = str(base_currency or "USD").strip().upper()
        total = 0.0
        for row in self.wealth.list_liabilities():
            if row.get("portfolio_id") != portfolio_id:
                continue
            if not row.get("is_active", True):
                continue
            if str(row.get("currency") or "").strip().upper() != base:
                continue
            total += float(row.get("principal") or 0.0)
        return total

    def _portfolio_account_ids(self, portfolio_id: str) -> Set[str]:
        return {
            str(row["id"])
            for row in self.wealth.list_accounts()
            if str(row.get("portfolio_id") or "") == portfolio_id
        }

    def save_snapshot_from_view(
        self,
        portfolio: Dict[str, Any],
        view: PortfolioIntelligenceView,
    ) -> PortfolioSnapshotView:
        portfolio_id = str(portfolio.get("id") or view.portfolio_id)
        if str(view.portfolio_id) != portfolio_id:
            raise WealthValidationError("Portföy kimliği görünüm ile uyuşmuyor.")

        owned = any(
            str(row.get("id") or "") == portfolio_id
            for row in self.wealth.portfolios.list_for_user(self.wealth.user_id)
        )
        if not owned:
            raise WealthValidationError("Portföy bu kullanıcıya ait değil.")

        liabilities_total = self._liabilities_total_for_portfolio(
            portfolio_id,
            view.base_currency,
        )
        captured_at = self._now_iso()
        snapshot_date = WealthPortfolioSnapshotRepository.utc_date_from_captured_at(
            captured_at
        )
        existing = self.snapshots.find_for_portfolio_on_date(
            self.wealth.user_id,
            portfolio_id,
            snapshot_date,
        )
        if existing is not None:
            return snapshot_view_from_row(existing)

        payload = snapshot_row_from_intelligence_view(
            user_id=self.wealth.user_id,
            portfolio_id=portfolio_id,
            captured_at=captured_at,
            view=view,
            liabilities_total=liabilities_total,
        )
        inserted = self.snapshots.insert(payload)
        return snapshot_view_from_row(inserted)

    def list_snapshots(self, portfolio_id: str, *, limit: int = 50) -> List[PortfolioSnapshotView]:
        rows = self.snapshots.list_for_portfolio(
            self.wealth.user_id,
            portfolio_id,
            limit=limit,
        )
        return [snapshot_view_from_row(row) for row in rows]

    def compare_snapshots(
        self,
        start: PortfolioSnapshotView,
        end: PortfolioSnapshotView,
    ) -> PortfolioPerformancePeriod:
        account_ids = self._portfolio_account_ids(start.portfolio_id)
        transactions = self.wealth.transactions.list_for_user(
            self.wealth.user_id,
            limit=TXN_HISTORY_LIMIT,
        )
        history_complete = len(transactions) < TXN_HISTORY_LIMIT
        return build_performance_period(
            start=start,
            end=end,
            transactions=transactions,
            account_ids=account_ids,
            transaction_history_complete=history_complete,
        )

    def build_timeline_view(
        self,
        portfolio: Dict[str, Any],
        *,
        snapshot_limit: int = 50,
    ) -> WealthTimelineView:
        portfolio_id = str(portfolio.get("id") or "")
        snapshots = self.list_snapshots(portfolio_id, limit=snapshot_limit)
        latest_period: Optional[PortfolioPerformancePeriod] = None
        if len(snapshots) >= 2:
            start = snapshots[1]
            end = snapshots[0]
            latest_period = self.compare_snapshots(start, end)

        return WealthTimelineView(
            portfolio_id=portfolio_id,
            portfolio_name=str(portfolio.get("name") or ""),
            base_currency=str(portfolio.get("base_currency") or "USD"),
            snapshots=snapshots,
            latest_period=latest_period,
        )

    @staticmethod
    def _history_point_from_snapshot(snapshot: PortfolioSnapshotView) -> PortfolioHistoryPoint:
        partial_reasons: List[str] = []
        if snapshot.unpriced_position_count > 0:
            partial_reasons.append("unpriced positions")
        if snapshot.mixed_currency_warning:
            partial_reasons.append("mixed currency")
        if snapshot.priced_position_coverage_pct < 100.0:
            partial_reasons.append(
                f"coverage {snapshot.priced_position_coverage_pct:.0f}%"
            )
        return PortfolioHistoryPoint(
            captured_at=snapshot.captured_at,
            priced_market_value=snapshot.priced_market_value,
            base_currency=snapshot.base_currency,
            is_partial=bool(partial_reasons),
            partial_reasons=partial_reasons,
        )

    def _transactions_for_portfolio(self, portfolio_id: str) -> tuple[List[Dict[str, Any]], bool]:
        transactions = self.wealth.transactions.list_for_user(
            self.wealth.user_id,
            limit=TXN_HISTORY_LIMIT,
        )
        history_complete = len(transactions) < TXN_HISTORY_LIMIT
        return transactions, history_complete

    def build_performance_view(
        self,
        portfolio: Dict[str, Any],
        *,
        snapshot_limit: int = 50,
    ) -> WealthPerformanceView:
        """Snapshot history + linked return. No provider calls."""
        portfolio_id = str(portfolio.get("id") or "")
        snapshots = self.list_snapshots(portfolio_id, limit=snapshot_limit)
        history_points = [self._history_point_from_snapshot(s) for s in snapshots]
        history_points_chronological = list(reversed(history_points))

        linked_performance: Optional[PortfolioLinkedPerformance] = None
        if len(snapshots) >= 2:
            snapshots_chronological = list(reversed(snapshots))
            transactions, history_complete = self._transactions_for_portfolio(portfolio_id)
            account_ids = self._portfolio_account_ids(portfolio_id)
            linked_performance = build_linked_performance(
                snapshots_chronological=snapshots_chronological,
                transactions=transactions,
                account_ids=account_ids,
                transaction_history_complete=history_complete,
            )

        return WealthPerformanceView(
            portfolio_id=portfolio_id,
            portfolio_name=str(portfolio.get("name") or ""),
            base_currency=str(portfolio.get("base_currency") or "USD"),
            history_points=history_points_chronological,
            linked_performance=linked_performance,
        )

    def build_benchmark_comparison(
        self,
        portfolio: Dict[str, Any],
        performance_view: WealthPerformanceView,
        benchmark_service: WealthBenchmarkService,
        *,
        snapshot_limit: int = 50,
    ) -> BenchmarkComparisonView:
        portfolio_id = str(portfolio.get("id") or "")
        linked = performance_view.linked_performance
        if linked is None:
            return BenchmarkComparisonView(
                benchmark_symbol="SPY",
                portfolio_normalized=[],
                portfolio_return_pct=None,
                benchmark_return_pct=None,
                relative_return_pct=None,
                performance_comparable=False,
                warnings=["At least two snapshots required for benchmark comparison."],
                provider_fetch_count=benchmark_service.fetch_count,
            )

        snapshots = self.list_snapshots(portfolio_id, limit=snapshot_limit)
        snapshots_chronological = list(reversed(snapshots))
        transactions, _ = self._transactions_for_portfolio(portfolio_id)
        account_ids = self._portfolio_account_ids(portfolio_id)
        portfolio_index = build_portfolio_index_series(
            snapshots_chronological=snapshots_chronological,
            linked=linked,
            transactions=transactions,
            account_ids=account_ids,
        )
        snapshot_dates = [snap.captured_at for snap in snapshots_chronological]

        return benchmark_service.build_spy_comparison(
            snapshot_dates=snapshot_dates,
            portfolio_index_series=portfolio_index,
            portfolio_return_pct=linked.linked_return_pct,
            performance_comparable=linked.performance_comparable,
            base_currency=performance_view.base_currency,
        )
