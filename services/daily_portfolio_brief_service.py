from __future__ import annotations

from datetime import date
from typing import Dict, Tuple

from services.monitor_contract import DailyPortfolioBriefContext, MonitorEventView
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.portfolio_intelligence_enrichment_service import PortfolioIntelligenceDashboardView


def build_daily_portfolio_brief(
    *,
    portfolio: Dict[str, object],
    dashboard: PortfolioIntelligenceDashboardView,
    monitor: MonitorIntelligenceService,
) -> DailyPortfolioBriefContext:
    portfolio_id = str(portfolio["id"])
    portfolio_name = str(portfolio.get("name") or "Portföy")
    events = monitor.list_events(
        portfolio_id=portfolio_id,
        dashboard=dashboard,
        limit=200,
    )

    counts: Dict[str, int] = {
        "total": len(events),
        "high_critical": 0,
        "portfolio": 0,
        "thesis": 0,
        "participation": 0,
        "research": 0,
        "unreviewed": 0,
    }
    for event in events:
        if event.materiality in {"high", "critical"}:
            counts["high_critical"] += 1
        if event.review_status == "new":
            counts["unreviewed"] += 1
        category = event.event_category
        if category in counts:
            counts[category] += 1

    highest = tuple(
        event for event in events if event.materiality in {"high", "critical"}
    )[:8]
    portfolio_affected = tuple(
        event for event in events if event.portfolio_impact and event.portfolio_impact.held
    )[:12]
    thesis_relevant = tuple(
        event
        for event in events
        if event.thesis_relevance
        and event.thesis_relevance.relevance
        in {"potential_invalidation", "review_recommended", "thesis_present"}
    )[:12]
    participation_events = tuple(
        event for event in events if event.event_category == "participation"
    )[:12]
    research_events = tuple(
        event for event in events if event.event_category == "research"
    )[:12]

    unresolved = tuple(
        f"{event.title} ({event.materiality})"
        for event in events
        if event.review_status == "new" and event.materiality in {"high", "critical"}
    )[:10]

    base = dashboard.base
    data_quality = {
        "priced_position_count": base.priced_position_count,
        "unpriced_position_count": base.unpriced_position_count,
        "priced_coverage_pct": dashboard.coverage.priced_market_value_coverage_pct,
        "limitations": list(dashboard.coverage.limitations),
    }
    source_freshness = {
        "snapshot_count": None,
        "monitor_event_count": len(events),
        "latest_detected_at": events[0].detected_at if events else None,
    }
    limitations = tuple(dashboard.coverage.limitations)
    if not events:
        limitations = (*limitations, "Bugün için kayıtlı monitor olayı yok.")

    return DailyPortfolioBriefContext(
        brief_date=date.today().isoformat(),
        portfolio_id=portfolio_id,
        portfolio_name=portfolio_name,
        event_counts=counts,
        highest_priority_events=highest,
        portfolio_affected_events=portfolio_affected,
        thesis_relevant_events=thesis_relevant,
        participation_events=participation_events,
        research_events=research_events,
        unresolved_attention=unresolved,
        data_quality=data_quality,
        source_freshness=source_freshness,
        limitations=limitations,
    )
