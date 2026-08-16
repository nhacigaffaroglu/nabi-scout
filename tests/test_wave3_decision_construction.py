from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.decision_learning_engine import (
    build_decision_learning_insights,
    build_decision_scorecard,
    contains_psychological_inference,
)
from services.decision_outcome_contract import ACTION_TO_DECISION_TYPE
from services.decision_outcome_engine import build_decision_outcome, classify_decision_type
from services.portfolio_ai_adviser_validator import validate_portfolio_ai_response
from services.portfolio_construction_engine import build_portfolio_construction_view
from services.portfolio_exposure_overlap_engine import build_exposure_overlap_signals
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.portfolio_intelligence_enrichment_contract import (
    ConsolidatedSymbolRow,
    EnrichedPositionRow,
    PortfolioIntelligenceDashboardView,
    PortfolioAttentionItem,
    CoverageMetadata,
)
from services.portfolio_scenario_engine import (
    build_portfolio_shock_scenario,
    compare_reference_structure,
    merge_reference_limits,
)
from services.wave3_monitor_detectors import detect_reference_limit_events
from services.wealth_contract import TXN_TYPE_BUY, TXN_TYPE_TRANSFER_IN
from services.wealth_position_engine import materialize_position_from_transactions_as_of


def _position(**kwargs) -> PositionValuationRow:
    defaults = dict(
        position_id="p1",
        account_id="a1",
        asset_id="asset1",
        symbol="AAPL",
        asset_class="equity",
        account_name="Broker",
        quantity=10.0,
        average_cost=100.0,
        valuation_currency="USD",
        price=110.0,
        price_available=True,
        market_value=1100.0,
        cost_basis=1000.0,
        unrealized_pl=100.0,
        weight_pct=25.0,
        is_cash=False,
        included_in_base_totals=True,
    )
    defaults.update(kwargs)
    if defaults.get("price") is None:
        defaults["price_available"] = False
    return PositionValuationRow(**defaults)


def _health() -> PortfolioHealthMetrics:
    return PortfolioHealthMetrics(
        largest_position_weight_pct=55.0,
        top3_concentration_pct=100.0,
        largest_asset_class_concentration_pct=99.0,
        cash_pct=0.0,
        invested_pct=100.0,
        priced_position_coverage_pct=100.0,
    )


def _dashboard(
    *,
    positions=None,
    consolidated=None,
    sector=None,
) -> PortfolioIntelligenceDashboardView:
    positions = positions or [
        _position(),
        _position(
            symbol="MSFT",
            asset_id="asset2",
            weight_pct=20.0,
            market_value=880.0,
            quantity=8.0,
        ),
    ]
    base = PortfolioIntelligenceView(
        portfolio_id="pf1",
        portfolio_name="Test",
        base_currency="USD",
        priced_total_market_value=2000.0,
        priced_total_cost_basis=1800.0,
        priced_total_unrealized_pl=200.0,
        priced_position_count=len(positions),
        unpriced_position_count=0,
        foreign_currency_position_count=0,
        total_position_count=len(positions),
        mixed_currency_warning=False,
        fx_supported=True,
        priced_positions=list(positions),
        unpriced_positions=[],
        foreign_currency_positions=[],
        asset_class_allocation=[],
        account_allocation=[],
        health=_health(),
        valuation_errors=[],
        price_provider="cache",
        unique_price_symbols_fetched=0,
    )
    enriched = tuple(
        EnrichedPositionRow(
            valuation=row,
            company_name=row.symbol,
            account_id="a1",
            account_label="Broker",
            institution="Broker",
            account_weight_pct=row.weight_pct,
            sector="Technology" if row.symbol == "AAPL" else "Technology",
            industry="Software",
            country="US",
            participation_status="Uygun",
            research_coverage="research_available",
            research_coverage_label="Araştırma mevcut",
            research_allowed_inferred=True,
            research_status="completed",
            has_candidate=True,
            has_participation_snapshot=True,
        )
        for row in positions
    )
    consolidated = consolidated or (
        ConsolidatedSymbolRow(
            symbol="AAPL",
            company_name="Apple",
            total_quantity=10.0,
            total_cost_basis=1000.0,
            total_market_value=1100.0,
            total_unrealized_pl=100.0,
            portfolio_weight_pct=55.0,
            participation_status="Uygun",
            research_coverage_label="Araştırma mevcut",
            account_breakdown=(),
        ),
        ConsolidatedSymbolRow(
            symbol="MSFT",
            company_name="Microsoft",
            total_quantity=8.0,
            total_cost_basis=800.0,
            total_market_value=880.0,
            total_unrealized_pl=80.0,
            portfolio_weight_pct=45.0,
            participation_status="Uygun",
            research_coverage_label="Araştırma mevcut",
            account_breakdown=(),
        ),
    )
    sector = sector or (AllocationSlice("Technology", "Technology", 1980.0, 99.0),)
    return PortfolioIntelligenceDashboardView(
        base=base,
        enriched_positions=enriched,
        sector_allocation=sector,
        country_allocation=(AllocationSlice("US", "US", 1980.0, 99.0),),
        currency_allocation=(AllocationSlice("USD", "USD", 1980.0, 99.0),),
        participation_allocation=(AllocationSlice("uygun", "Uygun", 1980.0, 99.0),),
        research_coverage_allocation=(
            AllocationSlice("research_available", "Araştırma mevcut", 1980.0, 99.0),
        ),
        account_allocation=(AllocationSlice("a1", "Broker", 1980.0, 99.0),),
        consolidated_symbols=consolidated,
        selected_account_id=None,
        participation_eligible_weight_pct=99.0,
        participation_non_eligible_weight_pct=0.0,
        participation_review_weight_pct=0.0,
        participation_unknown_weight_pct=0.0,
        research_coverage_weight_pct=99.0,
        unresearched_weight_pct=0.0,
        top5_concentration_pct=100.0,
        return_pct=None,
        attention_items=(PortfolioAttentionItem("c1", "watch", "t", "d"),),
        coverage=CoverageMetadata(
            priced_market_value_coverage_pct=100.0,
            participation_status_coverage_pct=100.0,
            sector_coverage_pct=100.0,
            price_data_complete=True,
            limitations=(),
        ),
    )


class DecisionClassificationTests(unittest.TestCase):
    def test_action_context_maps_to_decision_type(self) -> None:
        self.assertEqual(classify_decision_type({"action_context": "added"}), "initiated_position")
        self.assertEqual(classify_decision_type({"action_context": "reviewed"}), "reviewed_without_trade")

    def test_transfer_not_in_action_map(self) -> None:
        self.assertNotIn("transfer", ACTION_TO_DECISION_TYPE)


class DecisionOutcomeTests(unittest.TestCase):
    def test_outcome_with_txn_price(self) -> None:
        entry = {
            "id": "j1",
            "symbol": "AAPL",
            "created_at": "2026-01-01T10:00:00+00:00",
            "action_context": "added",
            "thesis": "Quality compounder",
        }
        txns = [
            {
                "id": "t1",
                "asset_id": "asset1",
                "txn_type": TXN_TYPE_BUY,
                "quantity": 10.0,
                "amount": 1000.0,
                "executed_at": "2026-01-01T10:00:00+00:00",
            }
        ]
        assets = {"asset1": {"symbol": "AAPL"}}
        enriched = {"AAPL": {"total_quantity": 10.0, "price": 110.0}}
        outcome = build_decision_outcome(
            entry=entry,
            transactions=txns,
            assets_by_id=assets,
            enriched_by_symbol=enriched,
            as_of="2026-06-01T10:00:00+00:00",
        )
        self.assertEqual(outcome.decision_price, 100.0)
        self.assertAlmostEqual(outcome.percentage_outcome or 0.0, 10.0)

    def test_missing_price_is_unavailable_not_fabricated(self) -> None:
        entry = {
            "id": "j2",
            "symbol": "AAPL",
            "created_at": "2026-01-01T10:00:00+00:00",
            "action_context": "added",
        }
        outcome = build_decision_outcome(
            entry=entry,
            transactions=[],
            assets_by_id={},
            enriched_by_symbol={"AAPL": {"total_quantity": 10.0, "price": 110.0}},
        )
        self.assertIn(outcome.outcome_status, {"UNAVAILABLE", "PARTIAL"})
        self.assertTrue(outcome.limitations)

    def test_transfer_excluded_from_linked_txn(self) -> None:
        entry = {
            "id": "j3",
            "symbol": "AAPL",
            "created_at": "2026-01-01T10:00:00+00:00",
            "action_context": "increased",
        }
        txns = [
            {
                "id": "t2",
                "asset_id": "asset1",
                "txn_type": TXN_TYPE_TRANSFER_IN,
                "quantity": 5.0,
                "amount": 500.0,
                "executed_at": "2026-01-01T10:00:00+00:00",
            }
        ]
        outcome = build_decision_outcome(
            entry=entry,
            transactions=txns,
            assets_by_id={"asset1": {"symbol": "AAPL"}},
            enriched_by_symbol={"AAPL": {"total_quantity": 5.0, "price": 100.0}},
        )
        self.assertIsNone(outcome.decision_price)


class LearningEngineTests(unittest.TestCase):
    def test_minimum_sample_threshold(self) -> None:
        insights = build_decision_learning_insights(
            outcomes=(),
            journal_entries=({"id": "1", "action_context": "added"},),
        )
        self.assertEqual(insights, ())

    def test_no_psychological_inference_helper(self) -> None:
        self.assertTrue(contains_psychological_inference("FOMO ile aldım"))
        self.assertFalse(contains_psychological_inference("Tekrarlayan yoğunlaşma"))


class ConstructionEngineTests(unittest.TestCase):
    def test_top_concentration(self) -> None:
        view = build_portfolio_construction_view(_dashboard())
        self.assertEqual(view.concentration.top1_symbol, "AAPL")
        self.assertAlmostEqual(view.concentration.top1_weight_pct or 0.0, 55.0)

    def test_overlap_same_sector(self) -> None:
        signals = build_exposure_overlap_signals(_dashboard())
        sector_signals = [s for s in signals if s.overlap_type == "sector_exposure_overlap"]
        self.assertTrue(sector_signals)
        self.assertNotIn("correlation", sector_signals[0].limitation.lower())


class ScenarioEngineTests(unittest.TestCase):
    def test_portfolio_shock(self) -> None:
        scenario = build_portfolio_shock_scenario(
            _dashboard(),
            scenario_id="s1",
            label="Shock -20%",
            shock_pct=-20.0,
        )
        self.assertFalse(scenario.is_forecast)
        self.assertIsNotNone(scenario.portfolio_impact_pct)
        self.assertLess(scenario.portfolio_impact_pct or 0.0, 0.0)

    def test_unpriced_excluded(self) -> None:
        unpriced = _position(
            symbol="XYZ",
            asset_id="asset2",
            price=None,
            market_value=None,
            weight_pct=None,
            price_available=False,
        )
        dash = _dashboard(positions=[_position(), unpriced])
        scenario = build_portfolio_shock_scenario(
            dash,
            scenario_id="s2",
            label="Shock",
            shock_pct=-10.0,
        )
        self.assertIn("XYZ", scenario.excluded_unpriced_symbols)


class ReferenceLimitTests(unittest.TestCase):
    def test_gap_has_no_trade_instruction(self) -> None:
        construction = build_portfolio_construction_view(_dashboard())
        gaps = compare_reference_structure(
            construction_view=construction,
            reference_limits=merge_reference_limits(None),
        )
        self.assertTrue(gaps)
        for gap in gaps:
            self.assertNotIn("sat", gap.note.lower())
            self.assertNotIn("sell", gap.note.lower())


class PortfolioAIValidatorWave3Tests(unittest.TestCase):
    def test_rejects_behavioral_claim(self) -> None:
        result = validate_portfolio_ai_response(
            portfolio_id="p1",
            raw_payload={
                "executive_summary": "FOMO ile tekrarlayan alımlar yapmışsınız.",
                "limitations": [],
            },
            context_payload={"decision_review": {"scorecard": {}}},
        )
        self.assertFalse(result.ok)
        self.assertIn("behavioral_inference", result.issues)

    def test_rejects_var(self) -> None:
        result = validate_portfolio_ai_response(
            portfolio_id="p1",
            raw_payload={"executive_summary": "VaR 12% görünüyor.", "limitations": []},
            context_payload={},
        )
        self.assertFalse(result.ok)
        self.assertIn("unsupported_risk_metric", result.issues)

    def test_allows_context_echo_of_missing_correlation(self) -> None:
        result = validate_portfolio_ai_response(
            portfolio_id="p1",
            raw_payload={
                "executive_summary": "İstatistiksel korelasyon hesaplanmadı; yalnızca sektör örtüşmesi var.",
                "limitations": [],
            },
            context_payload={
                "decision_review": {
                    "construction": {
                        "overlap_signals": [
                            {"limitation": "İstatistiksel korelasyon iddiası yok"}
                        ]
                    }
                }
            },
        )
        self.assertTrue(result.ok)


class MonitorWave3Tests(unittest.TestCase):
    def test_reference_limit_event_dedupe_key(self) -> None:
        from services.portfolio_construction_contract import ReferenceLimitGap

        gap = ReferenceLimitGap(
            dimension="max_single_position_pct",
            current_value=18.0,
            reference_limit=12.0,
            gap_pp=6.0,
            status="breach",
            note="gap",
        )
        drafts = detect_reference_limit_events(
            user_id="u1",
            portfolio_id="p1",
            reference_gaps=[gap],
        )
        self.assertEqual(len(drafts), 1)
        self.assertIn("CONCENTRATION", drafts[0].event_type)


class PositionAsOfTests(unittest.TestCase):
    def test_materialize_as_of_excludes_future_txns(self) -> None:
        txns = [
            {
                "id": "1",
                "txn_type": TXN_TYPE_BUY,
                "quantity": 5.0,
                "amount": 500.0,
                "executed_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": "2",
                "txn_type": TXN_TYPE_BUY,
                "quantity": 5.0,
                "amount": 500.0,
                "executed_at": "2026-06-01T00:00:00+00:00",
            },
        ]
        qty, _ = materialize_position_from_transactions_as_of(txns, as_of="2026-02-01T00:00:00+00:00")
        self.assertAlmostEqual(qty, 5.0)


class MigrationContractTests(unittest.TestCase):
    def test_wave3_migration_present(self) -> None:
        from pathlib import Path

        sql = (
            Path(__file__).resolve().parents[1]
            / "database"
            / "migration_wave3_decision_construction.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("portfolio_reference_limits", sql)
        self.assertIn("enable row level security", sql.lower())
        self.assertIn("PRE-DEPLOY MIGRATION REQUIRED", sql)


if __name__ == "__main__":
    unittest.main()
