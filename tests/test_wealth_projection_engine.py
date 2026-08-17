from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from services.portfolio_intelligence_contract import (
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_contract import WealthValidationError
from services.wealth_goal_models import (
    ContributionPlan,
    ConversionAssumption,
    CurrentWealthSnapshot,
    GoalEvidenceStatus,
    ProjectionLimitation,
    ReturnScenario,
    WealthGoal,
    current_wealth_from_portfolio_view,
    default_contribution_plan,
    default_return_scenarios,
    default_wealth_goal_2031,
)
from services.wealth_projection_engine import (
    iter_month_ends_after,
    project_wealth_goal,
    project_wealth_goal_scenarios,
)

AS_OF = date(2026, 12, 31)
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "sec_financial",
    "AlphaVantage",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "streamlit",
)


def _usd_snapshot(
    amount: str,
    *,
    complete: bool = True,
    unvalued: tuple[str, ...] = (),
) -> CurrentWealthSnapshot:
    return CurrentWealthSnapshot(
        currency="USD",
        current_value_lower_bound=Decimal(amount),
        valuation_complete=complete,
        unvalued_symbols=unvalued,
    )


def _usd_plan(
    monthly: str,
    *,
    increase: str = "0",
) -> ContributionPlan:
    return ContributionPlan(
        starting_monthly=Decimal(monthly),
        currency="USD",
        annual_increase_rate=Decimal(increase),
    )


def _goal() -> WealthGoal:
    return default_wealth_goal_2031()


def _row(symbol: str, *, priced: bool, included: bool, currency: str = "USD") -> PositionValuationRow:
    return PositionValuationRow(
        position_id=symbol,
        account_id="a",
        asset_id=symbol,
        symbol=symbol,
        asset_class="equity",
        account_name="acc",
        quantity=1,
        average_cost=1,
        valuation_currency=currency,
        price=10.0 if priced else None,
        price_available=priced,
        market_value=10.0 if priced else None,
        cost_basis=1,
        unrealized_pl=None,
        weight_pct=None,
        is_cash=False,
        included_in_base_totals=included,
    )


class WealthGoalConfigTests(unittest.TestCase):
    def test_default_500k_2031_usd(self) -> None:
        goal = _goal()
        self.assertEqual(goal.target_amount, Decimal("500000"))
        self.assertEqual(goal.target_date, date(2031, 12, 31))
        self.assertEqual(goal.currency, "USD")

    def test_default_contribution_plan_try(self) -> None:
        plan = default_contribution_plan()
        self.assertEqual(plan.starting_monthly, Decimal("60000"))
        self.assertEqual(plan.currency, "TRY")
        self.assertEqual(plan.annual_increase_rate, Decimal("0.25"))

    def test_default_scenarios(self) -> None:
        names_rates = [(row.name, row.annual_rate) for row in default_return_scenarios()]
        self.assertEqual(
            names_rates,
            [
                ("Conservative", Decimal("0.06")),
                ("Base", Decimal("0.08")),
                ("Growth", Decimal("0.10")),
            ],
        )


class ProjectionMathTests(unittest.TestCase):
    def test_monthly_compounding_end_of_month_contribution(self) -> None:
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=_usd_snapshot("1000"),
            contribution_plan=_usd_plan("100"),
            scenario=ReturnScenario("test", Decimal("0.12")),
            goal=WealthGoal("t", Decimal("1000000"), date(2027, 1, 31)),
        )
        # One full month: 1000 * (1+0.01) + 100 = 1110. BOM would be 1111.
        self.assertEqual(result.month_count, 1)
        self.assertEqual(result.projected_target_date_value, Decimal("1110.00"))
        self.assertEqual(result.total_projected_contributions, Decimal("100.00"))
        self.assertEqual(result.projected_investment_growth, Decimal("10.00"))

    def test_scenario_rates_diverge(self) -> None:
        bands = project_wealth_goal_scenarios(
            as_of_date=AS_OF,
            current=_usd_snapshot("10000"),
            contribution_plan=_usd_plan("0"),
            goal=WealthGoal("t", Decimal("1000000"), date(2027, 12, 31)),
        )
        values = [row.projected_target_date_value for row in bands]
        self.assertEqual([row.scenario_name for row in bands], ["Conservative", "Base", "Growth"])
        self.assertEqual(len(values), 3)
        self.assertLess(values[0], values[1])
        self.assertLess(values[1], values[2])

    def test_annual_contribution_increase_on_calendar_year(self) -> None:
        result = project_wealth_goal(
            as_of_date=date(2026, 11, 30),
            current=_usd_snapshot("0"),
            contribution_plan=_usd_plan("100", increase="0.25"),
            scenario=ReturnScenario("flat", Decimal("0")),
            goal=WealthGoal("t", Decimal("1000000"), date(2027, 1, 31)),
        )
        # Dec 2026: 100; Jan 2027: 125. Zero return, EOM add only.
        self.assertEqual(result.total_projected_contributions, Decimal("225.00"))
        self.assertEqual(result.projected_target_date_value, Decimal("225.00"))

    def test_horizon_uses_actual_month_ends_not_year_delta(self) -> None:
        target = date(2031, 12, 31)
        early = iter_month_ends_after(date(2026, 1, 31), target)
        late = iter_month_ends_after(date(2026, 12, 31), target)
        self.assertEqual(len(late), 60)
        self.assertEqual(len(early), 71)
        self.assertNotEqual(len(early), 2031 - 2026)

    def test_goal_reach_date_from_simulation(self) -> None:
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=_usd_snapshot("90"),
            contribution_plan=_usd_plan("10"),
            scenario=ReturnScenario("flat", Decimal("0")),
            goal=WealthGoal("t", Decimal("100"), date(2027, 3, 31)),
        )
        self.assertTrue(result.projected_goal_reached)
        self.assertEqual(result.projected_goal_reach_date, date(2027, 1, 31))
        self.assertEqual(result.status, GoalEvidenceStatus.PROJECTED_TO_REACH)

    def test_target_already_reached(self) -> None:
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=_usd_snapshot("500000"),
            contribution_plan=_usd_plan("0"),
            scenario=ReturnScenario("Base", Decimal("0.08")),
        )
        self.assertEqual(result.status, GoalEvidenceStatus.REACHED)
        self.assertTrue(result.projected_goal_reached)
        self.assertEqual(result.projected_goal_reach_date, AS_OF)
        self.assertEqual(result.measurable_gap, Decimal("0.00"))

    def test_zero_contributions_compounds_existing_only(self) -> None:
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=_usd_snapshot("1000"),
            contribution_plan=_usd_plan("0"),
            scenario=ReturnScenario("test", Decimal("0.12")),
            goal=WealthGoal("t", Decimal("1000000"), date(2027, 1, 31)),
        )
        self.assertEqual(result.total_projected_contributions, Decimal("0.00"))
        self.assertEqual(result.projected_target_date_value, Decimal("1010.00"))

    def test_zero_return_accumulates_contributions_only(self) -> None:
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=_usd_snapshot("50"),
            contribution_plan=_usd_plan("25"),
            scenario=ReturnScenario("flat", Decimal("0")),
            goal=WealthGoal("t", Decimal("1000000"), date(2027, 2, 28)),
        )
        self.assertEqual(result.projected_target_date_value, Decimal("100.00"))
        self.assertEqual(result.projected_investment_growth, Decimal("0.00"))

    def test_negative_return_reduces_balance(self) -> None:
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=_usd_snapshot("1000"),
            contribution_plan=_usd_plan("0"),
            scenario=ReturnScenario("down", Decimal("-0.12")),
            goal=WealthGoal("t", Decimal("1000000"), date(2027, 1, 31)),
        )
        self.assertEqual(result.projected_target_date_value, Decimal("990.00"))
        self.assertLess(result.projected_investment_growth, Decimal("0"))


class ValidationAndEvidenceTests(unittest.TestCase):
    def test_invalid_inputs_rejected(self) -> None:
        with self.assertRaises(WealthValidationError):
            project_wealth_goal(
                as_of_date=AS_OF,
                current=_usd_snapshot("1"),
                contribution_plan=_usd_plan("0"),
                scenario=ReturnScenario("x", Decimal("0")),
                goal=WealthGoal("t", Decimal("-1"), date(2031, 12, 31)),
            )
        with self.assertRaises(WealthValidationError):
            project_wealth_goal(
                as_of_date=AS_OF,
                current=_usd_snapshot("1"),
                contribution_plan=_usd_plan("-1"),
                scenario=ReturnScenario("x", Decimal("0")),
            )
        with self.assertRaises(WealthValidationError):
            ContributionPlan(Decimal("1"), "USD", Decimal("-1")).validate()
        with self.assertRaises(WealthValidationError):
            project_wealth_goal(
                as_of_date=date(2032, 1, 1),
                current=_usd_snapshot("1"),
                contribution_plan=_usd_plan("0"),
                scenario=ReturnScenario("x", Decimal("0")),
            )

    def test_partial_valuation_is_not_shortfall(self) -> None:
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=_usd_snapshot(
                "10000",
                complete=False,
                unvalued=("BIMAS", "ASELS", "TUPRS"),
            ),
            contribution_plan=_usd_plan("0"),
            scenario=ReturnScenario("Base", Decimal("0.08")),
        )
        self.assertFalse(result.valuation_complete)
        self.assertEqual(result.status, GoalEvidenceStatus.INDETERMINATE)
        self.assertIsNone(result.projected_goal_reached)
        self.assertIn(ProjectionLimitation.PARTIAL_VALUATION, result.limitations)
        self.assertEqual(result.current_value_lower_bound, Decimal("10000.00"))
        self.assertNotEqual(result.current_value_lower_bound, Decimal("0"))

    def test_try_contributions_without_fx_are_indeterminate(self) -> None:
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=_usd_snapshot("10000"),
            contribution_plan=default_contribution_plan(),
            scenario=ReturnScenario("Base", Decimal("0.08")),
        )
        self.assertFalse(result.projection_complete)
        self.assertIsNone(result.projected_target_date_value)
        self.assertEqual(result.status, GoalEvidenceStatus.INDETERMINATE)
        self.assertIn(ProjectionLimitation.FX_CONVERSION_REQUIRED, result.limitations)

    def test_explicit_fx_converts_try_without_mixing_raw_try(self) -> None:
        result = project_wealth_goal(
            as_of_date=date(2026, 11, 30),
            current=_usd_snapshot("0"),
            contribution_plan=default_contribution_plan(),
            scenario=ReturnScenario("flat", Decimal("0")),
            conversion=ConversionAssumption("TRY", "USD", Decimal("30")),
            goal=WealthGoal("t", Decimal("1000000"), date(2026, 12, 31)),
        )
        # Same calendar year: 60000 TRY / 30 = 2000 USD. Must not add 60000 as USD.
        self.assertEqual(result.projected_target_date_value, Decimal("2000.00"))
        self.assertNotEqual(result.projected_target_date_value, Decimal("60000.00"))
        self.assertTrue(result.projection_complete)

    def test_missing_valuation_not_coerced_to_zero_via_pi_view(self) -> None:
        health = PortfolioHealthMetrics(0, 0, 0, 0, 0, 50)
        view = PortfolioIntelligenceView(
            portfolio_id="p",
            portfolio_name="n",
            base_currency="USD",
            priced_total_market_value=12345.67,
            priced_total_cost_basis=10000,
            priced_total_unrealized_pl=2345.67,
            priced_position_count=1,
            unpriced_position_count=3,
            foreign_currency_position_count=0,
            total_position_count=4,
            mixed_currency_warning=True,
            fx_supported=False,
            priced_positions=[_row("AAPL", priced=True, included=True)],
            unpriced_positions=[
                _row("BIMAS", priced=False, included=False, currency="TRY"),
                _row("ASELS", priced=False, included=False, currency="TRY"),
                _row("TUPRS", priced=False, included=False, currency="TRY"),
            ],
            foreign_currency_positions=[],
            asset_class_allocation=[],
            account_allocation=[],
            health=health,
            valuation_errors=[],
            price_provider="candidate_db",
            unique_price_symbols_fetched=0,
        )
        snapshot = current_wealth_from_portfolio_view(view)
        self.assertEqual(snapshot.current_value_lower_bound, Decimal("12345.67"))
        self.assertFalse(snapshot.valuation_complete)
        self.assertEqual(snapshot.unvalued_symbols, ("BIMAS", "ASELS", "TUPRS"))
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=snapshot,
            contribution_plan=_usd_plan("0"),
            scenario=ReturnScenario("Base", Decimal("0.08")),
        )
        self.assertEqual(result.current_value_lower_bound, Decimal("12345.67"))
        self.assertEqual(result.status, GoalEvidenceStatus.INDETERMINATE)

    def test_holdings_recover_unvalued_when_view_lists_omit_bist(self) -> None:
        health = PortfolioHealthMetrics(0, 0, 0, 0, 0, 50)
        view = PortfolioIntelligenceView(
            portfolio_id="p",
            portfolio_name="n",
            base_currency="USD",
            priced_total_market_value=12345.67,
            priced_total_cost_basis=10000,
            priced_total_unrealized_pl=2345.67,
            priced_position_count=1,
            unpriced_position_count=3,
            foreign_currency_position_count=0,
            total_position_count=4,
            mixed_currency_warning=False,
            fx_supported=False,
            priced_positions=[_row("AAPL", priced=True, included=True)],
            unpriced_positions=[],
            foreign_currency_positions=[],
            asset_class_allocation=[],
            account_allocation=[],
            health=health,
            valuation_errors=[],
            price_provider="candidate_snapshot",
            unique_price_symbols_fetched=0,
        )
        snapshot = current_wealth_from_portfolio_view(
            view,
            positions=[
                {"asset_id": "a", "quantity": 10},
                {"asset_id": "b", "quantity": 10},
                {"asset_id": "c", "quantity": 10},
            ],
            assets=[
                {"id": "a", "symbol": "BIMAS"},
                {"id": "b", "symbol": "ASELS"},
                {"id": "c", "symbol": "TUPRS"},
            ],
        )
        self.assertFalse(snapshot.valuation_complete)
        self.assertEqual(snapshot.unvalued_symbols, ("BIMAS", "ASELS", "TUPRS"))
        self.assertEqual(snapshot.current_value_lower_bound, Decimal("12345.67"))

    def test_deterministic_repeated_calculation(self) -> None:
        kwargs = dict(
            as_of_date=AS_OF,
            current=_usd_snapshot("25000"),
            contribution_plan=_usd_plan("100"),
            scenario=ReturnScenario("Base", Decimal("0.08")),
        )
        first = project_wealth_goal(**kwargs)
        second = project_wealth_goal(**kwargs)
        self.assertEqual(first, second)

    def test_engine_modules_make_no_provider_calls(self) -> None:
        for rel in (
            "services/wealth_goal_models.py",
            "services/wealth_projection_engine.py",
        ):
            source = Path(rel).read_text(encoding="utf-8").lower()
            for token in PROVIDER_TOKENS:
                with self.subTest(rel=rel, token=token):
                    self.assertNotIn(token.lower(), source)


if __name__ == "__main__":
    unittest.main()
