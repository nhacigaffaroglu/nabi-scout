from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from repositories.monitor_event_repository import MonitorEventRepository
from services.monitor_contract import (
    EVENT_PARTICIPATION_STATUS_CHANGED,
    EVENT_PORTFOLIO_WEIGHT_CHANGED,
    MonitorEventDraft,
)
from services.monitor_dedupe import build_dedupe_key
from services.monitor_event_detectors import (
    detect_participation_events,
    detect_portfolio_events,
    detect_thesis_events,
)
from services.monitor_materiality_engine import classify_materiality
from services.monitor_portfolio_impact_engine import build_portfolio_impact
from services.monitor_thesis_relevance_engine import assess_thesis_relevance
from services.portfolio_ai_adviser_contract import PortfolioAIAdviserResponse
from services.portfolio_ai_adviser_display import polish_portfolio_ai_response
from services.portfolio_ai_adviser_prompt import compute_portfolio_ai_semantic_identity
from services.portfolio_ai_adviser_validator import validate_portfolio_ai_response
from services.wealth_timeline_contract import PortfolioSnapshotView


def _snapshot(**kwargs) -> PortfolioSnapshotView:
    defaults = {
        "id": "s1",
        "user_id": "u1",
        "portfolio_id": "p1",
        "captured_at": "2026-08-16T00:00:00+00:00",
        "base_currency": "USD",
        "priced_market_value": 10000.0,
        "total_cost_basis": 9000.0,
        "unrealized_pl": 1000.0,
        "cash_value": 0.0,
        "invested_value": 10000.0,
        "liabilities_total": None,
        "net_wealth_partial": None,
        "priced_position_coverage_pct": 100.0,
        "unpriced_position_count": 0,
        "mixed_currency_warning": False,
        "valuation_payload": {
            "priced_positions": [
                {
                    "symbol": "AAPL",
                    "weight_pct": 5.0,
                    "market_value": 500.0,
                }
            ],
            "research_coverage_weight_pct": 60.0,
        },
        "created_at": "2026-08-16T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return PortfolioSnapshotView(**defaults)


class MonitorMaterialityTests(unittest.TestCase):
    def test_participation_uygun_to_kontrol_et_is_high(self) -> None:
        level = classify_materiality(
            event_type=EVENT_PARTICIPATION_STATUS_CHANGED,
            severity="watch",
            previous_value="Uygun",
            current_value="Kontrol Et",
        )
        self.assertEqual(level, "high")

    def test_small_weight_change_is_info(self) -> None:
        level = classify_materiality(
            event_type=EVENT_PORTFOLIO_WEIGHT_CHANGED,
            severity="info",
            portfolio_weight=2.0,
            absolute_change=0.3,
        )
        self.assertEqual(level, "info")


class MonitorDetectorTests(unittest.TestCase):
    def test_portfolio_weight_change_detected(self) -> None:
        prev = _snapshot(
            valuation_payload={
                "priced_positions": [{"symbol": "AAPL", "weight_pct": 5.0}],
                "research_coverage_weight_pct": 60.0,
            }
        )
        curr = _snapshot(
            captured_at="2026-08-17T00:00:00+00:00",
            priced_market_value=11000.0,
            valuation_payload={
                "priced_positions": [{"symbol": "AAPL", "weight_pct": 8.0}],
                "research_coverage_weight_pct": 60.0,
            },
        )
        events = detect_portfolio_events(
            user_id="u1",
            portfolio_id="p1",
            previous=prev,
            current=curr,
        )
        codes = {event.event_type for event in events}
        self.assertIn(EVENT_PORTFOLIO_WEIGHT_CHANGED, codes)

    def test_participation_dedupe_key_stable(self) -> None:
        current = {
            "id": "snap-2",
            "status": "Kontrol Et",
            "assessed_at": "2026-08-16T12:00:00+00:00",
        }
        previous = {"id": "snap-1", "status": "Uygun", "assessed_at": "2026-08-15T12:00:00+00:00"}
        first = detect_participation_events(symbol="AAPL", previous_row=previous, current_row=current)
        second = detect_participation_events(symbol="AAPL", previous_row=previous, current_row=current)
        self.assertEqual(first[0].dedupe_key, second[0].dedupe_key)


class MonitorRepositoryDedupeTests(unittest.TestCase):
    def test_upsert_draft_conflict_returns_existing(self) -> None:
        repo = MonitorEventRepository(MagicMock())
        existing = {"id": "evt-1", "dedupe_key": "abc"}
        repo.get_by_dedupe_key = MagicMock(return_value=existing)
        repo.client.table.return_value.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint"
        )
        draft = MonitorEventDraft(
            user_id="u1",
            portfolio_id="p1",
            symbol="AAPL",
            event_type=EVENT_PORTFOLIO_WEIGHT_CHANGED,
            event_category="portfolio",
            severity="info",
            materiality="info",
            occurred_at="2026-08-16T00:00:00+00:00",
            dedupe_key="abc",
            title="test",
            summary="test",
        )
        from services.monitor_dedupe import draft_to_row

        row, inserted = repo.upsert_draft(draft_to_row(draft, detected_at="2026-08-16T00:00:00+00:00"))
        self.assertFalse(inserted)
        self.assertEqual(row["id"], "evt-1")


class PortfolioImpactTests(unittest.TestCase):
    def test_not_held_symbol(self) -> None:
        impact = build_portfolio_impact(
            symbol="MSFT",
            held_symbols={},
            enriched_by_symbol={},
        )
        self.assertFalse(impact.held)

    def test_unpriced_weight_limitation(self) -> None:
        impact = build_portfolio_impact(
            symbol="AAPL",
            held_symbols={
                "AAPL": {
                    "total_quantity": 10,
                    "portfolio_weight_pct": None,
                    "account_breakdown": [],
                    "account_count": 1,
                }
            },
            enriched_by_symbol={},
        )
        self.assertTrue(impact.held)
        self.assertIsNone(impact.portfolio_weight)
        self.assertTrue(impact.limitations)


class ThesisRelevanceTests(unittest.TestCase):
    def test_no_authoritative_invalidation_claim(self) -> None:
        view = assess_thesis_relevance(
            symbol="AAPL",
            event_summary="FCF margin declined materially",
            thesis_payload={
                "thesis_status": "WATCH",
                "confidence": "MEDIUM",
                "invalidation_conditions": [{"statement": "FCF margin materially deteriorates"}],
            },
            journal_entries=[],
        )
        self.assertIn(view.relevance, {"potential_invalidation", "review_recommended", "thesis_present"})
        self.assertNotIn("invalidated", view.explanation.lower())

    def test_journal_only_review_recommended(self) -> None:
        view = assess_thesis_relevance(
            symbol="AAPL",
            event_summary="Revenue changed",
            thesis_payload=None,
            journal_entries=[{"invalidation_conditions": "Margin collapse"}],
        )
        self.assertEqual(view.relevance, "review_recommended")


class PortfolioAIValidatorTests(unittest.TestCase):
    def test_rejects_trade_instruction(self) -> None:
        result = validate_portfolio_ai_response(
            portfolio_id="p1",
            raw_payload={
                "executive_summary": "AAPL al ve pozisyonu artır.",
                "what_changed": [],
                "portfolio_implications": [],
                "thesis_watch": [],
                "participation_watch": [],
                "research_gaps": [],
                "questions_to_review": [],
                "limitations": [],
                "evidence_references": [],
            },
            context_payload={"portfolio_context": {}},
        )
        self.assertFalse(result.ok)

    def test_rejects_target_price(self) -> None:
        result = validate_portfolio_ai_response(
            portfolio_id="p1",
            raw_payload={
                "executive_summary": "Hedef fiyat 250 USD.",
                "what_changed": [],
                "portfolio_implications": [],
                "thesis_watch": [],
                "participation_watch": [],
                "research_gaps": [],
                "questions_to_review": [],
                "limitations": [],
                "evidence_references": [],
            },
            context_payload={"portfolio_context": {}},
        )
        self.assertFalse(result.ok)

    def test_accepts_valid_response(self) -> None:
        result = validate_portfolio_ai_response(
            portfolio_id="p1",
            raw_payload={
                "executive_summary": "Portföy ağırlığı değişti; kanıt sınırlı.",
                "what_changed": ["AAPL ağırlığı arttı"],
                "portfolio_implications": ["Yoğunlaşma izlenmeli"],
                "thesis_watch": [],
                "participation_watch": [],
                "research_gaps": [],
                "questions_to_review": ["Veri tazeliği yeterli mi?"],
                "limitations": ["Eksik fiyat"],
                "evidence_references": ["monitor_event:1"],
            },
            context_payload={"portfolio_context": {"summary": {}}},
        )
        self.assertTrue(result.ok)


class PortfolioAISemanticIdentityTests(unittest.TestCase):
    def test_timestamp_only_change_same_identity(self) -> None:
        base = {
            "context_version": "portfolio_ai_context_v1",
            "portfolio_context": {"portfolio_id": "p1", "summary": {"position_count": 2}},
            "daily_brief": {"event_counts": {"total": 1}},
            "selected_events": [],
        }
        other = dict(base)
        other["generated_at"] = datetime.now(timezone.utc).isoformat()
        self.assertEqual(
            compute_portfolio_ai_semantic_identity(base),
            compute_portfolio_ai_semantic_identity(other),
        )

    def test_material_change_new_identity(self) -> None:
        base = {
            "context_version": "portfolio_ai_context_v1",
            "portfolio_context": {"portfolio_id": "p1", "summary": {"position_count": 2}},
            "daily_brief": {"event_counts": {"total": 1}},
            "selected_events": [],
        }
        changed = dict(base)
        changed["daily_brief"] = {"event_counts": {"total": 5}}
        self.assertNotEqual(
            compute_portfolio_ai_semantic_identity(base),
            compute_portfolio_ai_semantic_identity(changed),
        )


class PortfolioAIDisplayTests(unittest.TestCase):
    def test_polish_does_not_touch_unrelated_status(self) -> None:
        response = PortfolioAIAdviserResponse(
            portfolio_id="p1",
            status="AVAILABLE",
            evidence_level="MEDIUM",
            executive_summary="  Test summary  ",
            what_changed=(" item ",),
        )
        polished = polish_portfolio_ai_response(response)
        self.assertEqual(polished.status, "AVAILABLE")
        self.assertEqual(polished.executive_summary, "Test summary")


class PortfolioAINoAutoLlmTests(unittest.TestCase):
    def test_fetch_persisted_does_not_call_llm(self) -> None:
        from services.portfolio_ai_adviser_service import PortfolioAIAdviserService

        client = MagicMock()
        service = PortfolioAIAdviserService(client, "u1")
        service.repo.get_exact = MagicMock(
            return_value={
                "status": "AVAILABLE",
                "response_payload": PortfolioAIAdviserResponse(
                    portfolio_id="p1",
                    status="AVAILABLE",
                    evidence_level="MEDIUM",
                    executive_summary="Cached",
                ).to_dict(),
            }
        )
        with patch.object(service, "llm") as llm_mock:
            result = service.fetch_persisted(portfolio_id="p1", semantic_identity="abc")
        llm_mock.complete.assert_not_called()
        self.assertIsNotNone(result)
        self.assertEqual(result.executive_summary, "Cached")


if __name__ == "__main__":
    unittest.main()
