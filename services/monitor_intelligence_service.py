from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from repositories.investment_thesis_repository import InvestmentThesisRepository
from repositories.monitor_event_repository import MonitorEventRepository
from repositories.participation_assessment_repository import ParticipationAssessmentRepository
from repositories.user_monitor_event_state_repository import UserMonitorEventStateRepository
from services.monitor_contract import MonitorEventView, PortfolioImpactView, ThesisRelevanceView
from services.monitor_dedupe import draft_to_row
from services.monitor_event_detectors import (
    detect_participation_events,
    detect_portfolio_events,
    detect_thesis_events,
)
from services.monitor_portfolio_impact_engine import (
    build_enriched_index,
    build_held_symbol_index,
    build_portfolio_impact,
)
from services.monitor_thesis_relevance_engine import assess_thesis_relevance
from services.portfolio_intelligence_enrichment_service import PortfolioIntelligenceDashboardView
from services.wealth_decision_journal_service import WealthDecisionJournalService
from services.wealth_timeline_service import WealthTimelineService


MATERIALITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class MonitorIntelligenceService:
    def __init__(self, client, user_id: str) -> None:
        self.client = client
        self.user_id = user_id
        self.events = MonitorEventRepository(client)
        self.states = UserMonitorEventStateRepository(client)
        self.participation = ParticipationAssessmentRepository(client)
        self.thesis = InvestmentThesisRepository(client)
        self.journal = WealthDecisionJournalService(client, user_id)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def refresh_portfolio_events(
        self,
        *,
        portfolio: Dict[str, Any],
        dashboard: PortfolioIntelligenceDashboardView,
        wave3_view: Optional[Any] = None,
    ) -> Tuple[int, int]:
        from services.wealth_core_service import WealthCoreService

        wealth = WealthCoreService(self.client, self.user_id)
        timeline = WealthTimelineService(wealth)
        portfolio_id = str(portfolio["id"])
        snapshots = timeline.list_snapshots(portfolio_id, limit=2)
        created = skipped = 0
        if len(snapshots) >= 2:
            drafts = detect_portfolio_events(
                user_id=self.user_id,
                portfolio_id=portfolio_id,
                previous=snapshots[1],
                current=snapshots[0],
            )
            for draft in drafts:
                _, inserted = self.events.upsert_draft(
                    draft_to_row(draft, detected_at=self._now_iso())
                )
                if inserted:
                    created += 1
                else:
                    skipped += 1

        if wave3_view is not None:
            from services.wave3_monitor_detectors import (
                detect_decision_evidence_gap_event,
                detect_reference_limit_events,
            )

            now = self._now_iso()
            for draft in detect_reference_limit_events(
                user_id=self.user_id,
                portfolio_id=portfolio_id,
                reference_gaps=wave3_view.reference_gaps,
            ):
                payload = draft_to_row(draft, detected_at=now)
                _, inserted = self.events.upsert_draft(payload)
                created += 1 if inserted else 0
                skipped += 0 if inserted else 1
            unavailable = sum(
                1 for row in wave3_view.outcomes if row.outcome_status == "UNAVAILABLE"
            )
            for draft in detect_decision_evidence_gap_event(
                user_id=self.user_id,
                portfolio_id=portfolio_id,
                unavailable_count=unavailable,
                total_count=len(wave3_view.outcomes),
            ):
                payload = draft_to_row(draft, detected_at=now)
                _, inserted = self.events.upsert_draft(payload)
                created += 1 if inserted else 0
                skipped += 0 if inserted else 1

        now = self._now_iso()
        created_w4, skipped_w4 = self._refresh_wave4_events(
            portfolio_id=portfolio_id,
            dashboard=dashboard,
            snapshots=snapshots,
        )
        created += created_w4
        skipped += skipped_w4

        held_symbols = self._held_symbols(dashboard)
        for symbol in held_symbols:
            created_part, skipped_part = self._refresh_symbol_events(symbol)
            created += created_part
            skipped += skipped_part
        return created, skipped

    def _refresh_wave4_events(
        self,
        *,
        portfolio_id: str,
        dashboard: PortfolioIntelligenceDashboardView,
        snapshots: Sequence[Any],
    ) -> Tuple[int, int]:
        from services.wave4_monitor_context import (
            collect_fund_symbols,
            collect_missing_price_symbols,
            collect_stale_fund_symbols,
            collect_stale_fx_pairs,
            snapshot_allocation_flags,
        )
        from services.wave4_monitor_detectors import (
            detect_allocation_change_events,
            detect_fund_holdings_stale_events,
            detect_fx_stale_events,
            detect_missing_price_events,
        )

        created = skipped = 0
        now = self._now_iso()
        base = dashboard.base

        valuation_currencies = {
            row.valuation.valuation_currency
            for row in dashboard.enriched_positions
            if row.valuation.valuation_currency
        }
        stale_pairs = collect_stale_fx_pairs(
            self.client,
            base_currency=base.base_currency,
            valuation_currencies=valuation_currencies,
        )
        missing_prices = collect_missing_price_symbols(dashboard)
        fund_symbols = collect_fund_symbols(dashboard)
        stale_funds = collect_stale_fund_symbols(self.client, fund_symbols)

        asset_class_changed = currency_changed = False
        if len(snapshots) >= 2:
            asset_class_changed, currency_changed = snapshot_allocation_flags(
                snapshots[1],
                snapshots[0],
            )

        draft_batches = (
            detect_fx_stale_events(
                user_id=self.user_id,
                portfolio_id=portfolio_id,
                stale_pairs=stale_pairs,
            ),
            detect_missing_price_events(
                user_id=self.user_id,
                portfolio_id=portfolio_id,
                symbols=missing_prices,
            ),
            detect_fund_holdings_stale_events(
                user_id=self.user_id,
                portfolio_id=portfolio_id,
                symbols=stale_funds,
            ),
            detect_allocation_change_events(
                user_id=self.user_id,
                portfolio_id=portfolio_id,
                asset_class_changed=asset_class_changed,
                currency_changed=currency_changed,
            ),
        )
        for drafts in draft_batches:
            for draft in drafts:
                _, inserted = self.events.upsert_draft(
                    draft_to_row(draft, detected_at=now)
                )
                if inserted:
                    created += 1
                else:
                    skipped += 1
        return created, skipped

    def _held_symbols(self, dashboard: PortfolioIntelligenceDashboardView) -> Set[str]:
        symbols: Set[str] = set()
        for item in dashboard.consolidated_symbols:
            symbol = str(getattr(item, "symbol", "") or "").upper()
            if symbol and symbol != "CASH":
                symbols.add(symbol)
        return symbols

    def _refresh_symbol_events(self, symbol: str) -> Tuple[int, int]:
        created = skipped = 0
        participation_history = self.participation.get_recent_history(symbol, limit=2)
        if len(participation_history) >= 2:
            drafts = detect_participation_events(
                symbol=symbol,
                previous_row=participation_history[1],
                current_row=participation_history[0],
            )
            for draft in drafts:
                _, inserted = self.events.upsert_draft(
                    draft_to_row(draft, detected_at=self._now_iso())
                )
                if inserted:
                    created += 1
                else:
                    skipped += 1

        thesis_history = self.thesis.get_recent_history(symbol, limit=2)
        if len(thesis_history) >= 2:
            drafts = detect_thesis_events(
                symbol=symbol,
                current_row=thesis_history[0],
                previous_row=thesis_history[1],
            )
            for draft in drafts:
                _, inserted = self.events.upsert_draft(
                    draft_to_row(draft, detected_at=self._now_iso())
                )
                if inserted:
                    created += 1
                else:
                    skipped += 1
        return created, skipped

    def list_events(
        self,
        *,
        portfolio_id: str,
        dashboard: PortfolioIntelligenceDashboardView,
        category: Optional[str] = None,
        review_status: Optional[str] = None,
        held_only: bool = False,
        limit: int = 100,
    ) -> Tuple[MonitorEventView, ...]:
        held_symbols = self._held_symbols(dashboard)
        rows = self.events.list_recent(
            user_id=self.user_id,
            portfolio_id=portfolio_id,
            symbols=sorted(held_symbols) if held_symbols else None,
            limit=limit,
        )
        state_rows = {
            str(row["monitor_event_id"]): row
            for row in self.states.list_for_user(self.user_id, limit=1000)
        }
        held_index = build_held_symbol_index(dashboard.consolidated_symbols)
        enriched_index = build_enriched_index(dashboard.enriched_positions)
        thesis_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        journal_cache: Dict[str, List[Dict[str, Any]]] = {}

        views: List[MonitorEventView] = []
        for row in rows:
            if category and str(row.get("event_category") or "") != category:
                continue
            symbol = str(row.get("symbol") or "").upper() or None
            impact = build_portfolio_impact(
                symbol=symbol,
                held_symbols=held_index,
                enriched_by_symbol=enriched_index,
            )
            if held_only and not impact.held:
                continue
            state = state_rows.get(str(row.get("id") or ""), {})
            status = str(state.get("status") or "new")
            if review_status and status != review_status:
                continue

            thesis_payload = None
            journal_entries: List[Dict[str, Any]] = []
            if symbol:
                if symbol not in thesis_cache:
                    latest = self.thesis.get_latest(symbol)
                    payload = None
                    if latest:
                        payload = latest.get("thesis_payload") or latest.get("payload")
                    thesis_cache[symbol] = payload if isinstance(payload, dict) else None
                thesis_payload = thesis_cache[symbol]
                if symbol not in journal_cache:
                    journal_cache[symbol] = self.journal.list_entries(symbol=symbol, limit=5)
                journal_entries = journal_cache[symbol]

            thesis_rel = assess_thesis_relevance(
                symbol=symbol,
                event_summary=str(row.get("summary") or ""),
                thesis_payload=thesis_payload,
                journal_entries=journal_entries,
            )
            views.append(self._row_to_view(row, status=status, impact=impact, thesis=thesis_rel))

        views.sort(
            key=lambda item: (
                MATERIALITY_ORDER.get(item.materiality, 99),
                item.detected_at,
            )
        )
        return tuple(views[:limit])

    def mark_reviewed(self, monitor_event_id: str) -> None:
        self.states.upsert_state(
            user_id=self.user_id,
            monitor_event_id=monitor_event_id,
            status="reviewed",
        )

    def dismiss(self, monitor_event_id: str) -> None:
        self.states.upsert_state(
            user_id=self.user_id,
            monitor_event_id=monitor_event_id,
            status="dismissed",
        )

    def restore(self, monitor_event_id: str) -> None:
        self.states.upsert_state(
            user_id=self.user_id,
            monitor_event_id=monitor_event_id,
            status="new",
        )

    def symbol_summary(self, symbol: str, *, dashboard: Optional[PortfolioIntelligenceDashboardView] = None) -> Dict[str, Any]:
        rows = self.events.list_for_symbol(symbol, limit=20)
        state_rows = {
            str(row["monitor_event_id"]): row
            for row in self.states.list_for_user(self.user_id, limit=1000)
        }
        held = False
        if dashboard is not None:
            held = symbol.upper() in self._held_symbols(dashboard)
        unresolved_high = 0
        for row in rows:
            materiality = str(row.get("materiality") or "")
            status = str(state_rows.get(str(row.get("id") or ""), {}).get("status") or "new")
            if materiality in {"high", "critical"} and status == "new":
                unresolved_high += 1
        return {
            "symbol": symbol.upper(),
            "event_count": len(rows),
            "unresolved_high_priority": unresolved_high,
            "held": held,
            "latest_title": rows[0].get("title") if rows else None,
        }

    @staticmethod
    def _row_to_view(
        row: Dict[str, Any],
        *,
        status: str,
        impact: PortfolioImpactView,
        thesis: ThesisRelevanceView,
    ) -> MonitorEventView:
        return MonitorEventView(
            event_id=str(row.get("id") or ""),
            user_id=str(row.get("user_id")) if row.get("user_id") else None,
            portfolio_id=str(row.get("portfolio_id")) if row.get("portfolio_id") else None,
            symbol=str(row.get("symbol") or "") or None,
            event_type=str(row.get("event_type") or ""),
            event_category=str(row.get("event_category") or ""),
            severity=str(row.get("severity") or "info"),
            materiality=str(row.get("materiality") or "info"),
            occurred_at=str(row.get("occurred_at") or ""),
            detected_at=str(row.get("detected_at") or ""),
            title=str(row.get("title") or ""),
            summary=str(row.get("summary") or ""),
            evidence_type=row.get("evidence_type"),
            evidence_reference=row.get("evidence_reference"),
            previous_value=row.get("previous_value"),
            current_value=row.get("current_value"),
            absolute_change=float(row["absolute_change"]) if row.get("absolute_change") is not None else None,
            percentage_change=float(row["percentage_change"]) if row.get("percentage_change") is not None else None,
            event_payload=row.get("event_payload") or {},
            notification_eligible=bool(row.get("notification_eligible")),
            notification_reason=row.get("notification_reason"),
            review_status=status,
            portfolio_impact=impact,
            thesis_relevance=thesis,
        )
