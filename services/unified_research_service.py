from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

from services.investment_thesis_contract import InvestmentThesisView
from services.investment_thesis_service import InvestmentThesisService
from services.portfolio_company_fit_engine import assess_portfolio_company_fit
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.unified_research_contract import (
    MonitoringPlanItem,
    NabiResearchContext,
    ParticipationResearchContext,
    UNIFIED_RESEARCH_SCHEMA_VERSION,
    UnifiedResearchContext,
)
from services.unified_research_serializer import (
    serialize_company_intelligence_for_adviser,
    serialize_investment_thesis_for_adviser,
)
from services.wealth_exposure_bridge import build_wealth_exposure_context
from services.wealth_adviser_contract import AdviserUserContext
from services.research_eligibility_contract import ResearchEligibilityResult
from services.research_eligibility_service import require_research_allowed


def _nabi_context(candidate: Optional[Mapping[str, Any]]) -> Optional[NabiResearchContext]:
    if not candidate:
        return None
    return NabiResearchContext(
        decision=candidate.get("decision"),
        nabi_score=candidate.get("nabi_score"),
        research_status=candidate.get("research_status"),
        decision_label=candidate.get("decision_label") or candidate.get("decision"),
    )


def _participation_context(
    participation_view: Any,
) -> Optional[ParticipationResearchContext]:
    if participation_view is None or not getattr(participation_view, "available", False):
        return None
    result = getattr(participation_view, "result", None)
    if result is None:
        return None
    assessment = result.participation_assessment
    return ParticipationResearchContext(
        status=assessment.status,
        confidence=assessment.confidence,
        assessed_at=getattr(result, "assessed_at", None),
        limitations=tuple(getattr(result, "warnings", ()) or ()),
    )


def _build_monitoring_plan(
    thesis: Optional[InvestmentThesisView],
    exposure: Any,
    diagnostics_items: Tuple[Any, ...] = (),
) -> Tuple[MonitoringPlanItem, ...]:
    items = []
    if thesis:
        for index, row in enumerate(thesis.monitoring_plan[:6]):
            items.append(
                MonitoringPlanItem(
                    item_id=f"thesis-{index + 1}",
                    source="investment_thesis",
                    metric_or_event=row.metric_or_event,
                    why_it_matters=row.why_it_matters,
                    current_state=row.current_state,
                    next_known_date=row.next_known_date,
                )
            )
    if exposure is not None and getattr(exposure, "held", False):
        items.append(
            MonitoringPlanItem(
                item_id="portfolio-exposure",
                source="wealth",
                metric_or_event=f"{exposure.symbol} portföy ağırlığı",
                why_it_matters=exposure.concentration_context or "Maruziyet izlenmeli.",
                current_state=(
                    f"%{exposure.portfolio_weight_pct:.1f}"
                    if exposure.portfolio_weight_pct is not None
                    else "veri mevcut değil"
                ),
            )
        )
    for index, diagnostic in enumerate(diagnostics_items[:3]):
        items.append(
            MonitoringPlanItem(
                item_id=f"diagnostic-{index + 1}",
                source="wealth_diagnostics",
                metric_or_event=diagnostic.title,
                why_it_matters=diagnostic.statement,
                current_state=diagnostic.severity,
            )
        )
    return tuple(items[:8])


class UnifiedResearchService:
    def build_context(
        self,
        *,
        symbol: str,
        research_eligibility: ResearchEligibilityResult,
        company_intelligence_view=None,
        candidate: Optional[Mapping[str, Any]] = None,
        participation_view=None,
        portfolio_view: Optional[PortfolioIntelligenceView] = None,
        user_context: Optional[AdviserUserContext] = None,
        previous_thesis_snapshot: Optional[Mapping[str, Any]] = None,
        diagnostics_items: Tuple[Any, ...] = (),
    ) -> UnifiedResearchContext:
        normalized = str(symbol or "").strip().upper()
        require_research_allowed(research_eligibility, symbol=normalized)
        thesis_service = InvestmentThesisService()
        thesis_view = None
        if company_intelligence_view is not None:
            thesis_view = thesis_service.build_view(
                company_intelligence_view,
                research_eligibility=research_eligibility,
                candidate=dict(candidate) if candidate else None,
                participation_context=(
                    _participation_context(participation_view).status
                    if _participation_context(participation_view)
                    else None
                ),
                previous_snapshot=previous_thesis_snapshot,
            )
        exposure = build_wealth_exposure_context(portfolio_view, normalized)
        fit = assess_portfolio_company_fit(thesis_view, exposure)
        dq: Dict[str, Any] = {}
        if company_intelligence_view and company_intelligence_view.data_quality:
            dq = company_intelligence_view.data_quality.to_dict()
        if exposure.limitations:
            dq.setdefault("wealth_limitations", []).extend(list(exposure.limitations))
        profile = user_context.investor_profile if user_context else {}
        goals = user_context.active_goals if user_context else ()
        change_summary = tuple(
            item.to_dict() for item in (thesis_view.change_summary if thesis_view else ())
        )
        return UnifiedResearchContext(
            symbol=normalized,
            company_name=(
                company_intelligence_view.company_name if company_intelligence_view else None
            ),
            schema_version=UNIFIED_RESEARCH_SCHEMA_VERSION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            company_intelligence=serialize_company_intelligence_for_adviser(
                company_intelligence_view
            ),
            investment_thesis=serialize_investment_thesis_for_adviser(thesis_view),
            nabi_context=_nabi_context(candidate),
            participation_context=_participation_context(participation_view),
            wealth_exposure_context=exposure,
            portfolio_fit=fit,
            investor_profile=dict(profile),
            active_goals=tuple(dict(item) for item in goals),
            monitoring_plan=_build_monitoring_plan(thesis_view, exposure, diagnostics_items),
            thesis_change_summary=change_summary,
            data_quality=dq,
            provenance=(),
            focus_symbol=normalized,
        )
