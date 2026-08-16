from __future__ import annotations

import unittest
from datetime import datetime, timezone

from services.portfolio_change_engine import compare_portfolio_snapshots
from services.portfolio_opportunity_engine import (
    OPPORTUNITY_LABEL_DIVERSIFICATION,
    OPPORTUNITY_LABEL_RESEARCH,
    build_portfolio_opportunities,
)
from services.wealth_goal_projection_engine import project_goal
from services.wealth_income_service import (
    summarize_lifetime_cash_flows,
    summarize_portfolio_income,
)
from services.wealth_timeline_contract import PortfolioSnapshotView


def _snapshot(
    *,
    captured_at: str,
    value: float,
    payload: dict | None = None,
) -> PortfolioSnapshotView:
    return PortfolioSnapshotView(
        id="s1",
        user_id="u1",
        portfolio_id="p1",
        captured_at=captured_at,
        base_currency="USD",
        priced_market_value=value,
        total_cost_basis=value * 0.8,
        unrealized_pl=value * 0.2,
        cash_value=0.0,
        invested_value=value,
        liabilities_total=None,
        net_wealth_partial=value,
        priced_position_coverage_pct=100.0,
        unpriced_position_count=0,
        mixed_currency_warning=False,
        valuation_payload=payload or {},
        created_at=captured_at,
    )


class WealthIncomeServiceTests(unittest.TestCase):
    def test_transfer_excluded_from_external_cash_flow(self) -> None:
        txns = [
            {
                "id": "d1",
                "account_id": "a1",
                "txn_type": "deposit",
                "amount": 1000.0,
                "currency": "USD",
                "executed_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": "t1",
                "account_id": "a1",
                "txn_type": "transfer_out",
                "amount": 400.0,
                "currency": "USD",
                "executed_at": "2026-02-01T00:00:00+00:00",
            },
        ]
        summary = summarize_lifetime_cash_flows(
            txns,
            account_ids={"a1"},
            base_currency="USD",
        )
        self.assertAlmostEqual(summary.total_deposits, 1000.0)
        self.assertAlmostEqual(summary.net_external_flow, 1000.0)

    def test_dividend_income_summary(self) -> None:
        txns = [
            {
                "id": "div1",
                "account_id": "a1",
                "asset_id": "asset-aapl",
                "txn_type": "dividend",
                "quantity": 0,
                "amount": 25.0,
                "currency": "USD",
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
        assets = {"asset-aapl": {"symbol": "AAPL"}}
        income = summarize_portfolio_income(
            txns,
            account_ids={"a1"},
            accounts_by_id={"a1": {"institution": "Test", "name": "Broker"}},
            assets_by_id=assets,
            base_currency="USD",
            portfolio_market_value=10000.0,
        )
        self.assertAlmostEqual(income.total_dividends, 25.0)
        self.assertEqual(income.by_symbol[0].symbol, "AAPL")


class GoalProjectionEngineTests(unittest.TestCase):
    def test_zero_return_projection(self) -> None:
        result = project_goal(
            goal_title="Test",
            target_value=10000.0,
            target_date="2027-12-31",
            current_value=5000.0,
            currency="USD",
            monthly_contribution_assumption=100.0,
            expected_annual_return_assumption=0.0,
        )
        base = next(s for s in result.scenarios if s.label == "Baz")
        self.assertIsNotNone(base.projected_value)
        self.assertGreater(base.projected_value, 5000.0)

    def test_scenarios_labeled_as_user_assumption(self) -> None:
        result = project_goal(
            goal_title="Test",
            target_value=10000.0,
            target_date="2027-12-31",
            current_value=5000.0,
            currency="USD",
        )
        for scenario in result.scenarios:
            self.assertIn("NABI tahmini değildir", scenario.assumptions_note)


class PortfolioChangeEngineTests(unittest.TestCase):
    def test_weight_change_event(self) -> None:
        prev = _snapshot(
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000,
            payload={
                "priced_positions": [
                    {"symbol": "CRM", "weight_pct": 8.2},
                ],
                "research_coverage_weight_pct": 62.0,
            },
        )
        curr = _snapshot(
            captured_at="2026-02-01T00:00:00+00:00",
            value=11000,
            payload={
                "priced_positions": [
                    {"symbol": "CRM", "weight_pct": 11.4},
                ],
                "research_coverage_weight_pct": 74.0,
            },
        )
        events = compare_portfolio_snapshots(prev, curr)
        codes = {event.code for event in events}
        self.assertIn("WEIGHT_CHANGE", codes)
        self.assertIn("RESEARCH_COVERAGE_CHANGE", codes)


class OpportunityEngineTests(unittest.TestCase):
    def test_no_buy_sell_wording(self) -> None:
        rows = build_portfolio_opportunities(
            enriched_positions=[],
            candidates=[
                {
                    "symbol": "JNJ",
                    "company_name": "Johnson",
                    "participation_status": "Uygun",
                    "research_status": "completed",
                    "sector": "Healthcare",
                    "nabi_score": 80,
                }
            ],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].opportunity_label, OPPORTUNITY_LABEL_DIVERSIFICATION)
        self.assertNotIn("Buy", rows[0].explanation)
        self.assertNotIn("Sat", rows[0].explanation)

    def test_already_held_excluded(self) -> None:
        from services.portfolio_intelligence_contract import PriceQuote
        from services.portfolio_intelligence_engine import value_position

        row = value_position(
            position={
                "id": "p1",
                "account_id": "a1",
                "asset_id": "asset-jnj",
                "quantity": 1,
                "average_cost": 100,
                "cost_currency": "USD",
            },
            asset={"symbol": "JNJ", "asset_class": "equity", "currency": "USD"},
            account={"name": "Test", "institution": "Test"},
            base_currency="USD",
            quote=PriceQuote(price=110, currency="USD", available=True, source="test"),
        )
        from services.portfolio_intelligence_enrichment_service import _enrich_position

        enriched = _enrich_position(row, None, account={"name": "Test", "institution": "Test"})
        rows = build_portfolio_opportunities(
            [enriched],
            [{"symbol": "JNJ", "participation_status": "Uygun", "research_status": "done"}],
        )
        self.assertEqual(len(rows), 0)


class PortfolioResearchContextV3Tests(unittest.TestCase):
    def test_v3_includes_performance_when_v13_passed(self) -> None:
        from services.portfolio_intelligence_enrichment_contract import (
            CoverageMetadata,
            PortfolioIntelligenceDashboardView,
        )
        from services.portfolio_intelligence_contract import (
            PortfolioHealthMetrics,
            PortfolioIntelligenceView,
        )
        from services.portfolio_performance_intelligence_service import (
            PortfolioDataQualityPanel,
            PortfolioPerformanceSummary,
        )
        from services.portfolio_research_context import build_portfolio_research_context
        from services.wealth_income_service import PortfolioIncomeSummary
        from services.wealth_income_service import CashFlowSummary

        health = PortfolioHealthMetrics(
            largest_position_weight_pct=0.0,
            top3_concentration_pct=0.0,
            largest_asset_class_concentration_pct=0.0,
            cash_pct=0.0,
            invested_pct=0.0,
            priced_position_coverage_pct=100.0,
        )
        base = PortfolioIntelligenceView(
            portfolio_id="p1",
            portfolio_name="Main",
            base_currency="USD",
            priced_total_market_value=1000.0,
            priced_total_cost_basis=800.0,
            priced_total_unrealized_pl=200.0,
            priced_position_count=1,
            unpriced_position_count=0,
            foreign_currency_position_count=0,
            total_position_count=1,
            mixed_currency_warning=False,
            fx_supported=True,
            priced_positions=[],
            unpriced_positions=[],
            foreign_currency_positions=[],
            asset_class_allocation=[],
            account_allocation=[],
            health=health,
            valuation_errors=[],
            price_provider="test",
            unique_price_symbols_fetched=0,
        )
        dashboard = PortfolioIntelligenceDashboardView(
            base=base,
            enriched_positions=(),
            sector_allocation=(),
            country_allocation=(),
            currency_allocation=(),
            participation_allocation=(),
            research_coverage_allocation=(),
            account_allocation=(),
            consolidated_symbols=(),
            selected_account_id=None,
            participation_eligible_weight_pct=0.0,
            participation_non_eligible_weight_pct=0.0,
            participation_review_weight_pct=0.0,
            participation_unknown_weight_pct=0.0,
            research_coverage_weight_pct=0.0,
            unresearched_weight_pct=0.0,
            top5_concentration_pct=0.0,
            return_pct=25.0,
            coverage=CoverageMetadata(
                priced_market_value_coverage_pct=100.0,
                participation_status_coverage_pct=100.0,
                sector_coverage_pct=100.0,
                price_data_complete=True,
                limitations=(),
            ),
            attention_items=(),
        )
        v13 = type(
            "V13",
            (),
            {
                "performance": PortfolioPerformanceSummary(
                    current_value=1000.0,
                    invested_capital=800.0,
                    net_contributions=500.0,
                    total_gain=200.0,
                    unrealized_pl=200.0,
                    investment_gain=100.0,
                    net_external_flow=50.0,
                    dividend_income=10.0,
                    fee_total=1.0,
                    return_pct=25.0,
                    latest_period=None,
                    linked_return_pct=None,
                    performance_available=False,
                    limitations=(),
                ),
                "income": PortfolioIncomeSummary(
                    base_currency="USD",
                    total_dividends=10.0,
                    dividends_ytd=10.0,
                    trailing_twelve_months=10.0,
                    fee_total=1.0,
                    net_income=9.0,
                    income_yield_pct=1.0,
                    portfolio_market_value=1000.0,
                    by_symbol=(),
                    by_account=(),
                    timeline=(),
                    limitations=(),
                ),
                "cash_flow": CashFlowSummary(
                    base_currency="USD",
                    total_deposits=500.0,
                    total_withdrawals=0.0,
                    total_dividends=10.0,
                    total_fees=1.0,
                    net_external_flow=500.0,
                    limitations=(),
                ),
                "change_events": (),
                "goal_projections": (),
                "opportunities": (),
                "data_quality": PortfolioDataQualityPanel(
                    priced_positions=1,
                    total_positions=1,
                    priced_weight_pct=100.0,
                    snapshot_count=0,
                    performance_available=False,
                    income_available=True,
                    change_events_available=False,
                    fx_partial=False,
                    limitations=(),
                ),
            },
        )()
        ctx = build_portfolio_research_context(dashboard, v13=v13)
        self.assertEqual(ctx.schema_version, "portfolio_research_context_v3")
        self.assertIsNotNone(ctx.performance)
        self.assertAlmostEqual(ctx.performance["net_contributions"], 500.0)


if __name__ == "__main__":
    unittest.main()
