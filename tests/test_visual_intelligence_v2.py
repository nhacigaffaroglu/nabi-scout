"""Visual Intelligence V2 — chart contracts, stability regressions, holdings UI."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.portfolio_intelligence_charts import (
    HoldingsChartRow,
    PL_UNAVAILABLE_MESSAGE,
    build_coverage_status_chart,
    build_holdings_pl_chart,
    build_holdings_weight_chart,
    build_pl_by_position_chart,
    build_risk_budget_chart,
    build_top_concentration_chart,
    count_unpriced_holdings,
    normalize_enriched_holdings,
    normalize_valuation_holdings,
)
from services.portfolio_construction_contract import RiskBudgetDimension


def _enriched_row(
    symbol: str,
    *,
    price_available: bool = True,
    market_value: float = 1000.0,
    weight_pct: float = 10.0,
    unrealized_pl: float = 100.0,
    cost_basis: float = 900.0,
    is_cash: bool = False,
):
    val = MagicMock()
    val.symbol = symbol
    val.price_available = price_available
    val.market_value = market_value if price_available else None
    val.weight_pct = weight_pct if price_available else None
    val.unrealized_pl = unrealized_pl if price_available else None
    val.cost_basis = cost_basis
    val.is_cash = is_cash
    row = MagicMock()
    row.valuation = val
    return row


def _valuation_row(
    symbol: str,
    *,
    price_available: bool = True,
    market_value: float = 1000.0,
    weight_pct: float = 10.0,
    unrealized_pl: float = 100.0,
    cost_basis: float = 900.0,
):
    row = MagicMock()
    row.symbol = symbol
    row.price_available = price_available
    row.market_value = market_value if price_available else None
    row.weight_pct = weight_pct if price_available else None
    row.unrealized_pl = unrealized_pl if price_available else None
    row.cost_basis = cost_basis
    return row


class RiskBudgetChartTests(unittest.TestCase):
    def test_risk_budget_chart_renders_with_warning_import(self) -> None:
        dimensions = (
            RiskBudgetDimension(
                dimension="Top-1",
                current_value=14.0,
                threshold=12.0,
                status="watch",
                evidence="test",
                limitation="",
            ),
        )
        chart = build_risk_budget_chart(dimensions)
        self.assertIsNotNone(chart.to_json())


class HoldingsChartTests(unittest.TestCase):
    def test_unpriced_excluded_from_weight_chart(self) -> None:
        rows = [
            HoldingsChartRow("AAPL", 20.0, 2000.0, 100.0, 5.0, True),
            HoldingsChartRow("MSFT", None, None, None, None, False),
        ]
        self.assertEqual(count_unpriced_holdings(rows), 1)
        chart = build_holdings_weight_chart(rows)
        self.assertIn("AAPL", chart.to_json())

    def test_pl_chart_all_positive(self) -> None:
        rows = [
            HoldingsChartRow("A", 10.0, 100.0, 50.0, 5.0, True),
            HoldingsChartRow("B", 8.0, 80.0, 20.0, 2.0, True),
        ]
        self.assertIsNotNone(build_holdings_pl_chart(rows).to_json())

    def test_pl_chart_all_negative(self) -> None:
        rows = [
            HoldingsChartRow("A", 10.0, 100.0, -50.0, -5.0, True),
            HoldingsChartRow("B", 8.0, 80.0, -20.0, -2.0, True),
        ]
        self.assertIsNotNone(build_holdings_pl_chart(rows).to_json())

    def test_pl_chart_mixed(self) -> None:
        rows = [
            HoldingsChartRow("WIN", 10.0, 100.0, 50.0, 5.0, True),
            HoldingsChartRow("LOSS", 8.0, 80.0, -20.0, -2.0, True),
        ]
        self.assertIsNotNone(build_holdings_pl_chart(rows).to_json())

    def test_pl_chart_excludes_unavailable_not_zero(self) -> None:
        rows = [
            HoldingsChartRow("PRICED", 10.0, 100.0, 10.0, 1.0, True),
            HoldingsChartRow("UNPRICED", 5.0, None, None, None, False),
        ]
        payload = build_holdings_pl_chart(rows).to_json()
        self.assertIn("PRICED", payload)
        self.assertNotIn("UNPRICED", payload)
        self.assertIn("1 fiyatsız hariç", payload)

    def test_pl_chart_one_unpriced_holding_no_keyerror(self) -> None:
        rows = [HoldingsChartRow("UPS", None, None, None, None, False)]
        chart = build_holdings_pl_chart(rows)
        payload = chart.to_json()
        self.assertIn(PL_UNAVAILABLE_MESSAGE, payload)
        self.assertNotIn('"UPS"', payload)

    def test_pl_chart_missing_unrealized_pl_field(self) -> None:
        row = SimpleNamespace(symbol="UPS", price_available=False, market_value=None)
        chart = build_holdings_pl_chart([row])
        self.assertIn(PL_UNAVAILABLE_MESSAGE, chart.to_json())
        normalized = normalize_enriched_holdings(
            [SimpleNamespace(valuation=SimpleNamespace(symbol="UPS", price_available=False))]
        )
        self.assertIsNone(normalized[0].unrealized_pl)
        self.assertIsNotNone(build_holdings_pl_chart(normalized).to_json())

    def test_pl_chart_unrealized_pl_none(self) -> None:
        rows = [HoldingsChartRow("UPS", 10.0, None, None, None, True)]
        payload = build_holdings_pl_chart(rows).to_json()
        self.assertIn(PL_UNAVAILABLE_MESSAGE, payload)

    def test_pl_chart_all_unavailable(self) -> None:
        rows = [
            HoldingsChartRow("UPS", None, None, None, None, False),
            HoldingsChartRow("AAPL", None, None, None, None, False),
        ]
        payload = build_holdings_pl_chart(rows).to_json()
        self.assertIn(PL_UNAVAILABLE_MESSAGE, payload)
        self.assertNotIn('"UPS"', payload)
        self.assertNotIn('"AAPL"', payload)

    def test_pl_chart_empty_rows(self) -> None:
        payload = build_holdings_pl_chart([]).to_json()
        self.assertIn(PL_UNAVAILABLE_MESSAGE, payload)

    def test_pl_chart_mixed_available_unavailable(self) -> None:
        rows = [
            HoldingsChartRow("WIN", 10.0, 1100.0, 100.0, 10.0, True),
            HoldingsChartRow("UPS", None, None, None, None, False),
            HoldingsChartRow("FLAT", 5.0, 500.0, 0.0, 0.0, True),
        ]
        payload = json.dumps(
            json.loads(build_holdings_pl_chart(rows).to_json()),
            ensure_ascii=False,
        )
        self.assertIn("WIN", payload)
        self.assertIn("FLAT", payload)
        self.assertNotIn("UPS", payload)
        self.assertIn("1 fiyatsız hariç", payload)
        parsed = json.loads(build_holdings_pl_chart(rows).to_json())
        values = []
        for dataset in parsed.get("datasets", {}).values():
            if isinstance(dataset, list):
                for item in dataset:
                    if isinstance(item, dict) and "unrealized_pl" in item:
                        values.append(item["unrealized_pl"])
        self.assertIn(100.0, values)
        self.assertIn(0.0, values)
        self.assertNotIn(None, values)

    def test_pl_by_position_unpriced_enriched_no_keyerror(self) -> None:
        chart = build_pl_by_position_chart(
            [_enriched_row("UPS", price_available=False)]
        )
        self.assertIn(PL_UNAVAILABLE_MESSAGE, chart.to_json())

    def test_weight_chart_unpriced_only_no_keyerror(self) -> None:
        payload = build_holdings_weight_chart(
            [HoldingsChartRow("UPS", None, None, None, None, False)]
        ).to_json()
        self.assertIn("Fiyatlı pozisyon yok", payload)

    def test_normalize_enriched_and_valuation(self) -> None:
        enriched = normalize_enriched_holdings([_enriched_row("CASH", is_cash=True)])
        valuation = normalize_valuation_holdings([_valuation_row("AAPL", price_available=False)])
        self.assertEqual(enriched[0].symbol, "CASH")
        self.assertFalse(valuation[0].price_available)


class AllocationHierarchyTests(unittest.TestCase):
    def test_top_concentration_chart(self) -> None:
        chart = build_top_concentration_chart(
            top1_pct=18.0,
            top3_pct=42.0,
            top5_pct=55.0,
            top1_limit=15.0,
            top3_limit=40.0,
        )
        self.assertIsNotNone(chart.to_json())

    def test_coverage_status_chart(self) -> None:
        chart = build_coverage_status_chart(
            participation_pct=80.0,
            research_pct=70.0,
            unknown_participation_pct=5.0,
            unresearched_pct=10.0,
        )
        self.assertIsNotNone(chart.to_json())


class HoldingsUiModuleTests(unittest.TestCase):
    def test_wealth_positions_includes_holdings_module(self) -> None:
        from pathlib import Path

        source = Path("pages/10_Wealth.py").read_text(encoding="utf-8")
        self.assertIn("render_valuation_holdings_analysis", source)

    def test_pi_positions_includes_holdings_module(self) -> None:
        from pathlib import Path

        source = Path("pages/11_Portfolio_Intelligence.py").read_text(encoding="utf-8")
        self.assertIn("render_enriched_holdings_analysis", source)

    def test_reusable_holdings_ui_exists(self) -> None:
        from components.portfolio_holdings_ui import render_enriched_holdings_analysis

        with patch("components.portfolio_holdings_ui.st") as mock_st:
            mock_st.columns.return_value = [MagicMock(), MagicMock()]
            render_enriched_holdings_analysis(
                [_enriched_row("AAPL"), _enriched_row("MSFT", price_available=False)],
                currency="USD",
            )
            self.assertTrue(mock_st.altair_chart.called)


class PiCompositionTests(unittest.TestCase):
    def test_management_expander_after_hero(self) -> None:
        from pathlib import Path

        source = Path("pages/11_Portfolio_Intelligence.py").read_text(encoding="utf-8")
        hero_idx = source.index("render_portfolio_executive_hero")
        mgmt_idx = source.index("render_portfolio_management_expander")
        self.assertLess(hero_idx, mgmt_idx)

    def test_overview_uses_dominant_curve_first(self) -> None:
        from pathlib import Path

        source = Path("components/portfolio_overview_ui.py").read_text(encoding="utf-8")
        self.assertIn("build_portfolio_value_history_chart", source)
        self.assertIn("build_top_concentration_chart", source)


class EmptyPortfolioOnboardingTests(unittest.TestCase):
    def test_pi_empty_path_calls_onboarding_not_only_st_stop(self) -> None:
        source = Path("pages/11_Portfolio_Intelligence.py").read_text(encoding="utf-8")
        self.assertIn("render_empty_portfolio_onboarding", source)
        stop_idx = source.find("st.stop()")
        onboarding_idx = source.find("render_empty_portfolio_onboarding")
        self.assertGreater(stop_idx, 0)
        self.assertGreater(onboarding_idx, 0)
        self.assertLess(onboarding_idx, stop_idx)

    def test_empty_onboarding_manual_entry(self) -> None:
        source = Path("components/portfolio_intelligence_ui.py").read_text(encoding="utf-8")
        visual = Path("components/portfolio_visual_ui.py").read_text(encoding="utf-8")
        self.assertIn("render_empty_portfolio_onboarding", source)
        self.assertIn("render_add_holding_form", source)
        self.assertIn("render_create_account_form", source)
        self.assertNotIn("render_portfolio_bootstrap_section", source)
        self.assertNotIn("render_portfolio_bootstrap_section", visual)

    def test_create_account_expanded_when_no_accounts(self) -> None:
        source = Path("components/portfolio_intelligence_ui.py").read_text(encoding="utf-8")
        self.assertIn("expanded=not accounts", source)

    def test_empty_onboarding_wires_manual_entry(self) -> None:
        source = Path("components/portfolio_intelligence_ui.py").read_text(encoding="utf-8")
        self.assertIn("render_add_holding_form(wealth, portfolio, accounts)", source)
        self.assertIn(
            'render_create_account_form(wealth, str(portfolio["id"]), expanded=not accounts)',
            source,
        )


class DeletePolicyAuditTests(unittest.TestCase):
    def test_no_production_delete_path_in_app(self) -> None:
        for folder in ("components", "pages"):
            for path in Path(folder).rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn(".table('wealth_transactions').delete()", source)
                self.assertNotIn('.table("wealth_transactions").delete()', source)
                self.assertNotIn(".table('wealth_portfolio_snapshots').delete()", source)
                self.assertNotIn('.table("wealth_portfolio_snapshots").delete()', source)


if __name__ == "__main__":
    unittest.main()
