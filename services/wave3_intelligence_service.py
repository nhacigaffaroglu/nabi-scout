from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from services.decision_learning_engine import (
    build_decision_learning_insights,
    build_decision_scorecard,
)
from services.decision_outcome_contract import DecisionLearningInsight, DecisionOutcome, DecisionScorecard
from services.decision_outcome_engine import build_decision_outcomes
from services.portfolio_construction_contract import (
    DecisionTimelineEntry,
    PortfolioConstructionView,
    ReferenceLimitGap,
    ScenarioResult,
)
from services.portfolio_construction_engine import build_portfolio_construction_view
from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView
from services.portfolio_scenario_engine import (
    build_participation_exclusion_view,
    build_portfolio_shock_scenario,
    compare_reference_structure,
    merge_reference_limits,
)
from services.wealth_decision_journal_service import WealthDecisionJournalService


@dataclass(frozen=True)
class Wave3IntelligenceView:
    outcomes: Tuple[DecisionOutcome, ...]
    scorecard: DecisionScorecard
    learning_insights: Tuple[DecisionLearningInsight, ...]
    construction: PortfolioConstructionView
    reference_gaps: Tuple[ReferenceLimitGap, ...]
    timeline: Tuple[DecisionTimelineEntry, ...]
    data_quality_notes: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcomes": [row.to_dict() for row in self.outcomes],
            "scorecard": self.scorecard.to_dict(),
            "learning_insights": [row.to_dict() for row in self.learning_insights],
            "construction": self.construction.to_dict(),
            "reference_gaps": [row.to_dict() for row in self.reference_gaps],
            "timeline": [row.to_dict() for row in self.timeline],
            "data_quality_notes": list(self.data_quality_notes),
        }


def _enriched_symbol_map(dashboard: PortfolioIntelligenceDashboardView) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for row in dashboard.consolidated_symbols:
        result[row.symbol] = {
            "total_quantity": row.total_quantity,
            "price": (
                row.total_market_value / row.total_quantity
                if row.total_market_value is not None and row.total_quantity
                else None
            ),
            "participation_status": row.participation_status,
        }
    return result


def _participation_map(dashboard: PortfolioIntelligenceDashboardView) -> Dict[str, str]:
    return {
        row.symbol: row.participation_status
        for row in dashboard.consolidated_symbols
    }


def build_decision_timeline(
    *,
    outcomes: Iterable[DecisionOutcome],
    monitor_events: Iterable[Mapping[str, Any]],
) -> Tuple[DecisionTimelineEntry, ...]:
    events_by_symbol: Dict[str, list] = {}
    for event in monitor_events:
        sym = str(event.get("symbol") or "").upper()
        if sym:
            events_by_symbol.setdefault(sym, []).append(event)

    timeline: list[DecisionTimelineEntry] = []
    for outcome in outcomes:
        sym_events = events_by_symbol.get(outcome.symbol, [])
        linked_ids = tuple(
            str(event.get("id") or "")
            for event in sym_events[:5]
            if event.get("id")
        )
        timeline.append(
            DecisionTimelineEntry(
                journal_id=outcome.journal_id,
                symbol=outcome.symbol,
                decision_date=outcome.decision_date,
                decision_type=outcome.decision_type,
                title=f"{outcome.symbol} — {outcome.decision_type}",
                monitor_event_ids=linked_ids,
                thesis_change=None,
                position_change=outcome.action_context,
                outcome_status=outcome.outcome_status,
                outcome_pct=outcome.percentage_outcome,
            )
        )
    timeline.sort(key=lambda row: row.decision_date, reverse=True)
    return tuple(timeline)


class Wave3IntelligenceService:
    """Deterministic Wave 3 orchestrator — no LLM/FMP/SEC on render."""

    def __init__(self, client, user_id: str, wealth) -> None:
        self.client = client
        self.user_id = user_id
        self.wealth = wealth
        self.journal = WealthDecisionJournalService(client, user_id)

    def build_view(
        self,
        *,
        portfolio: Dict[str, Any],
        dashboard: PortfolioIntelligenceDashboardView,
        reference_limits_row: Optional[Mapping[str, Any]] = None,
        monitor_events: Optional[Iterable[Mapping[str, Any]]] = None,
    ) -> Wave3IntelligenceView:
        portfolio_id = str(portfolio["id"])
        journal_entries = self.journal.list_entries(portfolio_id=portfolio_id, limit=200)
        transactions = self.wealth.transactions.list_for_user(self.user_id, limit=5000)
        assets_by_id = {str(row["id"]): row for row in self.wealth.list_assets()}

        outcomes = build_decision_outcomes(
            journal_entries=journal_entries,
            transactions=transactions,
            assets_by_id=assets_by_id,
            enriched_by_symbol=_enriched_symbol_map(dashboard),
            participation_by_symbol=_participation_map(dashboard),
        )
        scorecard = build_decision_scorecard(outcomes)
        insights = build_decision_learning_insights(
            outcomes=outcomes,
            journal_entries=journal_entries,
        )
        limits = merge_reference_limits(reference_limits_row)
        construction = build_portfolio_construction_view(
            dashboard,
            default_thresholds=limits,
        )
        reference_gaps = compare_reference_structure(
            construction_view=construction,
            reference_limits=limits,
        )
        timeline = build_decision_timeline(
            outcomes=outcomes,
            monitor_events=monitor_events or (),
        )

        complete = sum(
            1 for row in outcomes if row.evidence_completeness == "complete"
        )
        notes = [
            f"{scorecard.total_evaluated} karar değerlendirildi; "
            f"{complete} tam kanıtlı sonuç.",
            f"{sum(1 for row in outcomes if row.outcome_status == 'UNAVAILABLE')} "
            "karar için geçmiş fiyat kanıtı eksik.",
        ]
        for insight in insights:
            if insight.evidence_count < 3:
                notes.append(
                    f"'{insight.insight_type}' yalnızca {insight.evidence_count} "
                    "gözlem — düşük kanıt."
                )

        return Wave3IntelligenceView(
            outcomes=outcomes,
            scorecard=scorecard,
            learning_insights=insights,
            construction=construction,
            reference_gaps=reference_gaps,
            timeline=timeline,
            data_quality_notes=tuple(notes),
        )

    def build_scenarios(
        self,
        dashboard: PortfolioIntelligenceDashboardView,
        *,
        portfolio_shock_pct: float = -20.0,
        sector: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> Tuple[ScenarioResult, ...]:
        scenarios = [
            build_portfolio_shock_scenario(
                dashboard,
                scenario_id="broad_shock",
                label=f"Geniş portföy şoku {portfolio_shock_pct:+.0f}%",
                shock_pct=portfolio_shock_pct,
            ),
            build_participation_exclusion_view(dashboard),
        ]
        if sector:
            symbols = [
                row.valuation.symbol
                for row in dashboard.enriched_positions
                if (row.sector or "") == sector and not row.valuation.is_cash
            ]
            scenarios.append(
                build_portfolio_shock_scenario(
                    dashboard,
                    scenario_id="sector_shock",
                    label=f"Sektör şoku: {sector} {portfolio_shock_pct:+.0f}%",
                    shock_pct=portfolio_shock_pct,
                    symbol_filter=symbols,
                )
            )
        if symbol:
            scenarios.append(
                build_portfolio_shock_scenario(
                    dashboard,
                    scenario_id="symbol_shock",
                    label=f"Pozisyon şoku: {symbol.upper()} {portfolio_shock_pct:+.0f}%",
                    shock_pct=portfolio_shock_pct,
                    symbol_filter=[symbol.upper()],
                )
            )
        return tuple(scenarios)
