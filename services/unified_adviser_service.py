from __future__ import annotations

from typing import Optional

from services.unified_research_contract import UnifiedResearchContext
from services.wealth_adviser_contract import AdviserBrief, AdviserUserContext
from services.wealth_adviser_grounding import build_adviser_brief, build_adviser_context
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_diagnostics_contract import PortfolioDiagnosticsView
from services.wealth_timeline_contract import BenchmarkComparisonView, WealthPerformanceView


class UnifiedAdviserService:
    """Enrich Wealth adviser brief notes with unified company/thesis context."""

    def enrich_brief(
        self,
        brief: AdviserBrief,
        unified_research: Optional[UnifiedResearchContext],
    ) -> AdviserBrief:
        if unified_research is None:
            return brief
        notes = list(brief.data_quality_notes)
        thesis = unified_research.investment_thesis or {}
        if thesis.get("thesis_status"):
            notes.append(
                f"Odak sembol {unified_research.symbol}: tez durumu {thesis['thesis_status']}."
            )
        if thesis.get("key_question"):
            notes.append(f"Ana yatırım sorusu: {thesis['key_question']}")
        exposure = unified_research.wealth_exposure_context
        if exposure is not None:
            if exposure.held and exposure.portfolio_weight_pct is not None:
                notes.append(
                    f"{exposure.symbol} portföy ağırlığı: %{exposure.portfolio_weight_pct:.1f}."
                )
            elif not exposure.held:
                notes.append(f"{exposure.symbol} portföyde tutulmuyor.")
        for fit in unified_research.portfolio_fit[:2]:
            notes.append(fit.statement)
        if unified_research.thesis_change_summary:
            notes.append("Kayıtlı tez geçmişine göre yapısal değişiklikler mevcut.")
        return AdviserBrief(
            headline=brief.headline,
            portfolio_summary=brief.portfolio_summary,
            top_findings=brief.top_findings,
            supporting_findings=brief.supporting_findings,
            data_quality_notes=tuple(dict.fromkeys(notes)),
            questions_for_user=brief.questions_for_user,
            prohibited_claims=brief.prohibited_claims,
            context=brief.context,
            preference_summary=brief.preference_summary,
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
        unified_research: Optional[UnifiedResearchContext] = None,
    ) -> AdviserBrief:
        context = build_adviser_context(
            portfolio_view=portfolio_view,
            diagnostics_view=diagnostics_view,
            performance_view=performance_view,
            benchmark_view=benchmark_view,
            transaction_history_complete=transaction_history_complete,
            generated_from_snapshot_count=generated_from_snapshot_count,
        )
        if user_context is not None:
            from services.wealth_adviser_contract import AdviserContext, ADVISER_SCHEMA_VERSION

            context = AdviserContext(
                portfolio=context.portfolio,
                findings=context.findings,
                data_quality=context.data_quality,
                generated_from_snapshot_count=context.generated_from_snapshot_count,
                deterministic_only=context.deterministic_only,
                schema_version=ADVISER_SCHEMA_VERSION,
                user_context=user_context,
            )
        brief = build_adviser_brief(context, user_context=user_context)
        return self.enrich_brief(brief, unified_research)
