from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Tuple

from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_core_service import WealthCoreService
from services.wealth_diagnostics_contract import PortfolioDiagnosticsView
from services.wealth_diagnostics_engine import build_portfolio_diagnostics
from services.wealth_portfolio_return_engine import build_portfolio_index_series
from services.wealth_timeline_contract import BenchmarkComparisonView, WealthPerformanceView
from services.wealth_timeline_service import TXN_HISTORY_LIMIT, WealthTimelineService


class WealthDiagnosticsService:
    """Assemble deterministic portfolio diagnostics from existing Wealth views."""

    def __init__(self, wealth: WealthCoreService):
        self.wealth = wealth

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _transaction_history_complete(self) -> bool:
        transactions = self.wealth.transactions.list_for_user(
            self.wealth.user_id,
            limit=TXN_HISTORY_LIMIT,
        )
        return len(transactions) < TXN_HISTORY_LIMIT

    def _portfolio_account_ids(self, portfolio_id: str) -> Set[str]:
        return {
            str(row["id"])
            for row in self.wealth.list_accounts()
            if str(row.get("portfolio_id") or "") == portfolio_id
        }

    def _performance_index_points(
        self,
        *,
        portfolio: Dict[str, Any],
        performance_view: Optional[WealthPerformanceView],
    ) -> Optional[list[Tuple[str, float]]]:
        if (
            performance_view is None
            or performance_view.linked_performance is None
            or not performance_view.linked_performance.performance_comparable
        ):
            return None

        portfolio_id = str(portfolio.get("id") or "")
        timeline = WealthTimelineService(self.wealth)
        snapshots = timeline.list_snapshots(portfolio_id)
        if len(snapshots) < 2:
            return None

        snapshots_chronological = list(reversed(snapshots))
        transactions = self.wealth.transactions.list_for_user(
            self.wealth.user_id,
            limit=TXN_HISTORY_LIMIT,
        )
        account_ids = self._portfolio_account_ids(portfolio_id)
        series = build_portfolio_index_series(
            snapshots_chronological=snapshots_chronological,
            linked=performance_view.linked_performance,
            transactions=transactions,
            account_ids=account_ids,
        )
        comparable_points = [
            (label, value)
            for label, value in series
            if value is not None
        ]
        return comparable_points if len(comparable_points) >= 2 else None

    def build_diagnostics_view(
        self,
        portfolio: Dict[str, Any],
        portfolio_view: PortfolioIntelligenceView,
        *,
        performance_view: Optional[WealthPerformanceView] = None,
        benchmark_view: Optional[BenchmarkComparisonView] = None,
        transaction_history_complete: Optional[bool] = None,
        generated_at: Optional[str] = None,
    ) -> PortfolioDiagnosticsView:
        history_complete = (
            self._transaction_history_complete()
            if transaction_history_complete is None
            else transaction_history_complete
        )
        index_points = self._performance_index_points(
            portfolio=portfolio,
            performance_view=performance_view,
        )
        if (
            index_points is None
            and benchmark_view is not None
            and benchmark_view.performance_comparable
        ):
            index_points = [
                (point.label_date, point.portfolio_index)
                for point in benchmark_view.portfolio_normalized
                if point.portfolio_index is not None
            ] or None

        return build_portfolio_diagnostics(
            portfolio_id=str(portfolio.get("id") or portfolio_view.portfolio_id),
            generated_at=generated_at or self._now_iso(),
            portfolio_view=portfolio_view,
            performance_view=performance_view,
            benchmark_view=benchmark_view,
            performance_index_points=index_points,
            transaction_history_complete=history_complete,
        )
