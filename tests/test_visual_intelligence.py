import unittest
from unittest.mock import MagicMock, patch

from components.nabi_design_system import render_status_badge
from services.nabi_visual_insights import build_portfolio_insights
from services.portfolio_intelligence_charts import (
    build_allocation_bar_chart,
    build_performance_vs_contributions_chart,
    build_performance_waterfall_chart,
    build_portfolio_value_history_chart,
    build_scenario_impact_chart,
)
from services.portfolio_construction_contract import ReferenceLimitGap, ScenarioResult
from services.wealth_timeline_contract import PortfolioHistoryPoint, PortfolioPerformancePeriod


class _BaseStub:
    unpriced_position_count = 0
    base_currency = "USD"
    priced_total_market_value = 100000.0
    health = MagicMock(priced_position_coverage_pct=100.0)
    price_provider = "persisted"


class _DashboardStub:
    base = _BaseStub()
    enriched_positions = ()
    consolidated_symbols = ()
    participation_eligible_weight_pct = 80.0
    participation_unknown_weight_pct = 5.0
    research_coverage_weight_pct = 70.0
    unresearched_weight_pct = 10.0
    sector_allocation = ()
    account_allocation = ()
    participation_allocation = ()
    research_coverage_allocation = ()
    currency_allocation = ()
    attention_items = ()
    asset_class_allocation = []


class VisualIntelligenceChartTests(unittest.TestCase):
    def test_empty_allocation_chart_renders(self) -> None:
        chart = build_allocation_bar_chart([], title="Test")
        self.assertIsNotNone(chart)

    def test_insufficient_history_message(self) -> None:
        chart = build_portfolio_value_history_chart([])
        self.assertIsNotNone(chart)

    def test_contribution_chart_does_not_fabricate(self) -> None:
        chart = build_performance_vs_contributions_chart(
            investment_gain=None,
            net_contributions=0.0,
            currency="USD",
        )
        self.assertIsNotNone(chart)

    def test_waterfall_requires_comparable_period(self) -> None:
        chart = build_performance_waterfall_chart(None, currency="USD")
        self.assertIsNotNone(chart)

    def test_waterfall_with_period(self) -> None:
        period = PortfolioPerformancePeriod(
            period_start_at="2026-01-01",
            period_end_at="2026-06-01",
            base_currency="USD",
            start_priced_value=100000.0,
            end_priced_value=110000.0,
            portfolio_value_change=10000.0,
            external_inflows=5000.0,
            external_outflows=0.0,
            net_external_flow=5000.0,
            investment_gain=5000.0,
            dividend_income=200.0,
            fee_cost=50.0,
            start_coverage_pct=100.0,
            end_coverage_pct=100.0,
            start_unpriced_count=0,
            end_unpriced_count=0,
            performance_comparable=True,
            simple_period_return_pct=10.0,
            warnings=[],
        )
        chart = build_performance_waterfall_chart(period, currency="USD")
        self.assertIsNotNone(chart)

    def test_scenario_label_not_forecast_in_ui_module(self) -> None:
        from components.portfolio_wave3_ui import render_scenarios_section
        import inspect

        source = inspect.getsource(render_scenarios_section)
        self.assertIn("SCENARIO", source.upper())
        self.assertIn("NOT FORECAST", source.upper())

    def test_scenario_impact_chart_empty(self) -> None:
        chart = build_scenario_impact_chart([], currency="USD")
        self.assertIsNotNone(chart)

    def test_scenario_impact_chart_with_data(self) -> None:
        scenarios = (
            ScenarioResult(
                scenario_id="broad_shock",
                scenario_label="Broad -20%",
                shock_pct=-20.0,
                affected_positions=(),
                current_priced_value=100000.0,
                shocked_value=80000.0,
                portfolio_impact_pct=-20.0,
                portfolio_impact_abs=-20000.0,
                coverage_pct=95.0,
                excluded_unpriced_symbols=(),
                assumptions=("SCENARIO — NOT FORECAST",),
                limitations=(),
            ),
        )
        chart = build_scenario_impact_chart(scenarios, currency="USD")
        self.assertIsNotNone(chart)


class VisualInsightTests(unittest.TestCase):
    def test_insights_deterministic_no_llm(self) -> None:
        insights = build_portfolio_insights(dashboard=_DashboardStub())
        self.assertIsInstance(insights, list)

    def test_partial_valuation_insight(self) -> None:
        dash = _DashboardStub()
        dash.base.unpriced_position_count = 3
        dash.base.health.priced_position_coverage_pct = 72.0
        insights = build_portfolio_insights(dashboard=dash)
        self.assertTrue(any("72" in line or "fiyat" in line.lower() for line in insights))

    def test_decision_scorecard_not_investor_score(self) -> None:
        from components.portfolio_wave3_ui import render_decisions_section
        import inspect

        source = inspect.getsource(render_decisions_section)
        self.assertIn("Karar skor kartı", source)
        self.assertNotIn("investor score", source.lower())


class DesignSystemTests(unittest.TestCase):
    def test_status_badge_renders_html(self) -> None:
        badge = render_status_badge("Uygun", "success")
        self.assertIn("Uygun", badge)
        self.assertIn("span", badge)


class ZeroCostRenderTests(unittest.TestCase):
    def test_home_dashboard_no_remote_on_build_view(self) -> None:
        from pathlib import Path

        source = Path("components/nabi_home_dashboard.py").read_text(encoding="utf-8")
        self.assertIn("enrich_nabi=False", source)


class PortfolioResearchContextSecretFreeTests(unittest.TestCase):
    def test_research_context_module_has_no_service_role(self) -> None:
        from pathlib import Path

        source = Path("services/portfolio_research_context.py").read_text(encoding="utf-8")
        self.assertNotIn("service_role", source.lower())


if __name__ == "__main__":
    unittest.main()
