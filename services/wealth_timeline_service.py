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
from services.wealth_timeline_contract import (
    PortfolioPerformancePeriod,
    PortfolioSnapshotView,
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
        payload = snapshot_row_from_intelligence_view(
            user_id=self.wealth.user_id,
            portfolio_id=portfolio_id,
            captured_at=self._now_iso(),
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
