from __future__ import annotations

from typing import Optional, Tuple

from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_adviser_contract import AdviserBrief, AdviserContext, AdviserUserContext
from services.wealth_adviser_grounding import build_adviser_brief, build_adviser_context
from services.wealth_diagnostics_contract import PortfolioDiagnosticsView
from services.wealth_timeline_contract import BenchmarkComparisonView, WealthPerformanceView


class WealthAdviserService:
    """Build deterministic adviser grounding from existing Wealth views only."""

    def build_context(
        self,
        portfolio_view: PortfolioIntelligenceView,
        diagnostics_view: PortfolioDiagnosticsView,
        *,
        performance_view: Optional[WealthPerformanceView] = None,
        benchmark_view: Optional[BenchmarkComparisonView] = None,
        transaction_history_complete: bool = True,
        generated_from_snapshot_count: int = 0,
        user_context: Optional[AdviserUserContext] = None,
    ) -> AdviserContext:
        context = build_adviser_context(
            portfolio_view=portfolio_view,
            diagnostics_view=diagnostics_view,
            performance_view=performance_view,
            benchmark_view=benchmark_view,
            transaction_history_complete=transaction_history_complete,
            generated_from_snapshot_count=generated_from_snapshot_count,
        )
        if user_context is None:
            return context
        return AdviserContext(
            portfolio=context.portfolio,
            findings=context.findings,
            data_quality=context.data_quality,
            generated_from_snapshot_count=context.generated_from_snapshot_count,
            deterministic_only=context.deterministic_only,
            schema_version=context.schema_version,
            user_context=user_context,
        )

    def build_brief(
        self,
        portfolio_view: PortfolioIntelligenceView,
        diagnostics_view: PortfolioDiagnosticsView,
        *,
        performance_view: Optional[WealthPerformanceView] = None,
        benchmark_view: Optional[BenchmarkComparisonView] = None,
        transaction_history_complete: bool = True,
        generated_from_snapshot_count: int = 0,
        user_context: Optional[AdviserUserContext] = None,
    ) -> AdviserBrief:
        context = self.build_context(
            portfolio_view,
            diagnostics_view,
            performance_view=performance_view,
            benchmark_view=benchmark_view,
            transaction_history_complete=transaction_history_complete,
            generated_from_snapshot_count=generated_from_snapshot_count,
            user_context=user_context,
        )
        return build_adviser_brief(context, user_context=user_context)

    def build_preview(
        self,
        portfolio_view: PortfolioIntelligenceView,
        diagnostics_view: PortfolioDiagnosticsView,
        *,
        performance_view: Optional[WealthPerformanceView] = None,
        benchmark_view: Optional[BenchmarkComparisonView] = None,
        transaction_history_complete: bool = True,
        generated_from_snapshot_count: int = 0,
        user_context: Optional[AdviserUserContext] = None,
    ) -> Tuple[AdviserContext, AdviserBrief]:
        context = self.build_context(
            portfolio_view,
            diagnostics_view,
            performance_view=performance_view,
            benchmark_view=benchmark_view,
            transaction_history_complete=transaction_history_complete,
            generated_from_snapshot_count=generated_from_snapshot_count,
            user_context=user_context,
        )
        return context, build_adviser_brief(context, user_context=user_context)
