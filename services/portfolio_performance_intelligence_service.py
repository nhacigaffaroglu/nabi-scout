from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from repositories.candidate_repository import CandidateRepository
from services.portfolio_change_engine import PortfolioChangeEvent, compare_portfolio_snapshots
from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView
from services.portfolio_opportunity_engine import PortfolioOpportunityRow, build_portfolio_opportunities
from services.wealth_goal_projection_engine import GoalProjectionResult, project_goal
from services.wealth_income_service import (
    CashFlowSummary,
    PortfolioIncomeSummary,
    summarize_lifetime_cash_flows,
    summarize_portfolio_income,
)
from services.wealth_performance_engine import build_performance_period
from services.wealth_timeline_contract import PortfolioPerformancePeriod, WealthPerformanceView
from services.wealth_timeline_service import WealthTimelineService


@dataclass(frozen=True)
class PortfolioPerformanceSummary:
    current_value: Optional[float]
    invested_capital: float
    net_contributions: float
    total_gain: Optional[float]
    unrealized_pl: float
    investment_gain: Optional[float]
    net_external_flow: Optional[float]
    dividend_income: float
    fee_total: float
    return_pct: Optional[float]
    latest_period: Optional[PortfolioPerformancePeriod]
    linked_return_pct: Optional[float]
    performance_available: bool
    limitations: Tuple[str, ...]


@dataclass(frozen=True)
class PortfolioDataQualityPanel:
    priced_positions: int
    total_positions: int
    priced_weight_pct: Optional[float]
    snapshot_count: int
    performance_available: bool
    income_available: bool
    change_events_available: bool
    fx_partial: bool
    limitations: Tuple[str, ...]


@dataclass(frozen=True)
class PortfolioIntelligenceV13View:
    dashboard: PortfolioIntelligenceDashboardView
    performance: PortfolioPerformanceSummary
    performance_history: WealthPerformanceView
    income: PortfolioIncomeSummary
    cash_flow: CashFlowSummary
    change_events: Tuple[PortfolioChangeEvent, ...]
    opportunities: Tuple[PortfolioOpportunityRow, ...]
    goal_projections: Tuple[GoalProjectionResult, ...]
    data_quality: PortfolioDataQualityPanel


class PortfolioPerformanceIntelligenceService:
    """Compose Wealth timeline, income, goals, and opportunity layers for PI."""

    def __init__(self, wealth, *, nabi_client=None) -> None:
        self.wealth = wealth
        self.timeline = WealthTimelineService(wealth)
        self.nabi_client = nabi_client

    def _portfolio_account_ids(self, portfolio_id: str) -> Set[str]:
        return {
            str(row["id"])
            for row in self.wealth.list_accounts()
            if str(row.get("portfolio_id") or "") == portfolio_id
        }

    def _assets_by_id(self) -> Dict[str, Dict[str, Any]]:
        return {str(row["id"]): row for row in self.wealth.list_assets()}

    def _accounts_by_id(self) -> Dict[str, Dict[str, Any]]:
        return {str(row["id"]): row for row in self.wealth.list_accounts()}

    def build_view(
        self,
        portfolio: Dict[str, Any],
        dashboard: PortfolioIntelligenceDashboardView,
    ) -> PortfolioIntelligenceV13View:
        portfolio_id = str(portfolio["id"])
        base = dashboard.base
        account_ids = self._portfolio_account_ids(portfolio_id)
        accounts_by_id = self._accounts_by_id()
        assets_by_id = self._assets_by_id()
        transactions = self.wealth.transactions.list_for_user(self.wealth.user_id, limit=5000)

        cash_flow = summarize_lifetime_cash_flows(
            transactions,
            account_ids=account_ids,
            base_currency=base.base_currency,
        )
        income = summarize_portfolio_income(
            transactions,
            account_ids=account_ids,
            accounts_by_id=accounts_by_id,
            assets_by_id=assets_by_id,
            base_currency=base.base_currency,
            portfolio_market_value=base.priced_total_market_value,
        )

        snapshots = self.timeline.list_snapshots(portfolio_id, limit=50)
        performance_history = self.timeline.build_performance_view(portfolio)

        latest_period: Optional[PortfolioPerformancePeriod] = None
        linked_return_pct: Optional[float] = None
        investment_gain: Optional[float] = None
        net_external_flow: Optional[float] = None
        perf_limitations: List[str] = []

        if len(snapshots) >= 2:
            latest_period = self.timeline.compare_snapshots(snapshots[-1], snapshots[0])
            investment_gain = latest_period.investment_gain
            net_external_flow = latest_period.net_external_flow
            if latest_period.warnings:
                perf_limitations.extend(latest_period.warnings)
        else:
            perf_limitations.append(
                "Geçmiş performans için en az iki portföy görüntüsü gerekli."
            )

        if performance_history.linked_performance:
            linked_return_pct = performance_history.linked_performance.linked_return_pct
            if performance_history.linked_performance.warnings:
                perf_limitations.extend(performance_history.linked_performance.warnings)

        total_gain = None
        if base.priced_total_market_value is not None:
            total_gain = (
                base.priced_total_unrealized_pl
                + income.total_dividends
                - income.fee_total
            )

        performance = PortfolioPerformanceSummary(
            current_value=base.priced_total_market_value,
            invested_capital=base.priced_total_cost_basis,
            net_contributions=cash_flow.net_external_flow,
            total_gain=total_gain,
            unrealized_pl=base.priced_total_unrealized_pl,
            investment_gain=investment_gain,
            net_external_flow=net_external_flow,
            dividend_income=income.total_dividends,
            fee_total=income.fee_total,
            return_pct=dashboard.return_pct,
            latest_period=latest_period,
            linked_return_pct=linked_return_pct,
            performance_available=len(snapshots) >= 2,
            limitations=tuple(dict.fromkeys(perf_limitations)),
        )

        change_events: Tuple[PortfolioChangeEvent, ...] = ()
        if len(snapshots) >= 2:
            change_events = compare_portfolio_snapshots(snapshots[1], snapshots[0])

        candidates: List[Dict[str, Any]] = []
        if self.nabi_client is not None:
            try:
                repo = CandidateRepository(self.nabi_client)
                candidates = repo.get_all(limit=200)
            except Exception:
                candidates = []

        opportunities = build_portfolio_opportunities(
            dashboard.enriched_positions,
            candidates,
        )

        goal_projections: List[GoalProjectionResult] = []
        try:
            from repositories.wealth_adviser_goal_repository import WealthAdviserGoalRepository

            goal_repo = WealthAdviserGoalRepository(self.wealth.client)
            for goal in goal_repo.list_active_for_user(
                self.wealth.user_id,
                portfolio_id=portfolio_id,
            ):
                goal_projections.append(
                    project_goal(
                        goal_title=str(goal.get("title") or "Hedef"),
                        target_value=(
                            float(goal["target_amount"])
                            if goal.get("target_amount") is not None
                            else None
                        ),
                        target_date=str(goal.get("target_date") or "") or None,
                        current_value=base.priced_total_market_value,
                        currency=str(goal.get("currency") or base.base_currency),
                        monthly_contribution_assumption=(
                            float(goal["monthly_contribution_assumption"])
                            if goal.get("monthly_contribution_assumption") is not None
                            else None
                        ),
                        expected_annual_return_assumption=(
                            float(goal["expected_annual_return_assumption"])
                            if goal.get("expected_annual_return_assumption") is not None
                            else None
                        ),
                    )
                )
        except Exception:
            pass

        priced_weight = None
        if base.total_position_count > 0:
            priced_weight = (
                (base.priced_position_count / base.total_position_count) * 100.0
            )

        data_quality = PortfolioDataQualityPanel(
            priced_positions=base.priced_position_count,
            total_positions=base.total_position_count,
            priced_weight_pct=priced_weight,
            snapshot_count=len(snapshots),
            performance_available=len(snapshots) >= 2,
            income_available=income.total_dividends > 0 or income.fee_total > 0,
            change_events_available=len(change_events) > 0,
            fx_partial=base.foreign_currency_position_count > 0,
            limitations=tuple(dashboard.coverage.limitations),
        )

        return PortfolioIntelligenceV13View(
            dashboard=dashboard,
            performance=performance,
            performance_history=performance_history,
            income=income,
            cash_flow=cash_flow,
            change_events=change_events,
            opportunities=opportunities,
            goal_projections=tuple(goal_projections),
            data_quality=data_quality,
        )
