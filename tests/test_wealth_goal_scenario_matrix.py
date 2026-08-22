from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from services.wealth_goal_models import (
    ContributionPlan,
    CurrentWealthSnapshot,
    GoalEvidenceStatus,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_goal_planning import solve_required_starting_monthly
from services.wealth_goal_scenario_service import (
    BASE_RETURN_RATE,
    DEFAULT_TRACKING_START,
    GOAL_DATE_AVAILABLE,
    GOAL_DATE_UNAVAILABLE,
    MISSING_PLANNING_FX,
    REPORT_BAND_LARGE_SHORTFALL,
    REPORT_BAND_TARGET_REACHED,
    REPORT_BAND_UNAVAILABLE,
    build_goal_scenario_matrix,
    contribution_calendar,
    project_scenario,
    report_feasibility_band,
)
from services.wealth_planning_fx import schedule_from_mapping
from services.wealth_projection_engine import project_wealth_goal
from services.wealth_goal_models import ReturnScenario


AS_OF = date(2026, 8, 21)
TRACKING_START = date(2026, 9, 1)
CURRENT_WEALTH = Decimal("79508.4249")
PLANNING_FX = {2026: 51, 2027: 59, 2028: 66, 2029: 73, 2030: 80, 2031: 87}
CANONICAL_PROJECTED = Decimal("249356.14")
CANONICAL_REQUIRED = Decimal("177996.50")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "alpha_vantage",
    "TwelveData",
    "twelve_data",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "BorsaIstanbul",
    "borsaistanbul",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".delete(",
    "create_account",
    "replace_schedule",
    "upsert_rate",
    "set_contribution_tracking_start",
    "capture_portfolio_snapshot",
    "insert(",
    "update(",
)
SERVICE = Path("services/wealth_goal_scenario_service.py")


def _usd(amount=CURRENT_WEALTH, *, complete: bool = True) -> CurrentWealthSnapshot:
    return CurrentWealthSnapshot(
        currency="USD",
        current_value_lower_bound=Decimal(str(amount)),
        valuation_complete=complete,
    )


def _plan(monthly="60000", *, increase="0.25") -> ContributionPlan:
    return ContributionPlan(
        starting_monthly=Decimal(monthly),
        currency="TRY",
        annual_increase_rate=Decimal(increase),
    )


def _fx():
    return schedule_from_mapping(PLANNING_FX)


def _matrix(**kwargs):
    defaults = dict(
        as_of_date=AS_OF,
        current=_usd(),
        fx_schedule=_fx(),
        contribution_plan=_plan(),
        goal=default_wealth_goal_2031(),
        contribution_tracking_start=TRACKING_START,
    )
    defaults.update(kwargs)
    return build_goal_scenario_matrix(**defaults)


class BaselineReproductionTests(unittest.TestCase):
    def test_baseline_reproduces_canonical_projection(self) -> None:
        matrix = _matrix()
        self.assertEqual(matrix.current_wealth, CURRENT_WEALTH)
        self.assertEqual(matrix.starting_monthly, Decimal("60000"))
        self.assertEqual(matrix.base_return_rate, Decimal("0.08"))
        self.assertEqual(matrix.indexation_rate, Decimal("0.25"))
        self.assertTrue(matrix.valuation_complete)
        self.assertEqual(matrix.baseline.projected_wealth, CANONICAL_PROJECTED)
        self.assertEqual(
            matrix.baseline.surplus_or_shortfall,
            CANONICAL_PROJECTED - Decimal("500000"),
        )
        self.assertEqual(matrix.required_starting_monthly_base, CANONICAL_REQUIRED)
        self.assertEqual(matrix.baseline.engine_result.status, GoalEvidenceStatus.PROJECTED_SHORTFALL)
        self.assertEqual(matrix.baseline.report_band, REPORT_BAND_LARGE_SHORTFALL)


class MonotonicScenarioTests(unittest.TestCase):
    def test_higher_contribution_produces_higher_projected_wealth(self) -> None:
        matrix = _matrix()
        values = [row.projected_wealth for row in matrix.contribution_matrix]
        self.assertTrue(all(item is not None for item in values))
        self.assertEqual(values, sorted(values))
        self.assertGreater(values[-1], values[0])

    def test_higher_return_produces_higher_projected_wealth(self) -> None:
        matrix = _matrix()
        values = [row.projected_wealth for row in matrix.return_matrix]
        self.assertTrue(all(item is not None for item in values))
        self.assertEqual(values, sorted(values))
        self.assertGreater(values[-1], values[0])

    def test_180k_at_base_matches_canonical_engine(self) -> None:
        matrix = _matrix()
        cell = next(
            row
            for row in matrix.contribution_matrix
            if row.starting_monthly == Decimal("180000")
        )
        direct = project_wealth_goal(
            goal=default_wealth_goal_2031(),
            as_of_date=AS_OF,
            current=_usd(),
            contribution_plan=_plan("180000"),
            scenario=ReturnScenario("Planning 8%", Decimal("0.08")),
            fx_schedule=_fx(),
        )
        self.assertEqual(cell.projected_wealth, direct.projected_target_date_value)
        self.assertEqual(cell.target_reached, direct.projected_goal_reached)
        self.assertTrue(cell.target_reached)
        self.assertEqual(cell.report_band, REPORT_BAND_TARGET_REACHED)


class RequiredMonthlyTests(unittest.TestCase):
    def test_required_monthly_at_8pct_matches_canonical_solver(self) -> None:
        matrix = _matrix()
        solved = solve_required_starting_monthly(
            as_of_date=AS_OF,
            current=_usd(),
            contribution_currency="TRY",
            annual_increase_rate=Decimal("0.25"),
            annual_return_rate=Decimal("0.08"),
            fx_schedule=_fx(),
            goal=default_wealth_goal_2031(),
        )
        self.assertEqual(matrix.required_starting_monthly_base, solved.starting_monthly)
        self.assertEqual(solved.starting_monthly, CANONICAL_REQUIRED)
        self.assertEqual(matrix.break_even.break_even_monthly, CANONICAL_REQUIRED)
        self.assertEqual(matrix.break_even.current_monthly, Decimal("60000"))
        self.assertEqual(
            matrix.break_even.absolute_gap,
            CANONICAL_REQUIRED - Decimal("60000"),
        )

    def test_required_monthly_decreases_as_assumed_return_increases(self) -> None:
        matrix = _matrix()
        required = [
            row.required_starting_monthly for row in matrix.required_monthly_by_return
        ]
        self.assertTrue(all(item is not None for item in required))
        self.assertEqual(required, sorted(required, reverse=True))
        self.assertGreater(required[0], required[-1])


class IsolationTests(unittest.TestCase):
    def test_scenario_calculation_does_not_mutate_contribution_plan(self) -> None:
        plan = _plan()
        before = (
            plan.starting_monthly,
            plan.currency,
            plan.annual_increase_rate,
        )
        _matrix(contribution_plan=plan)
        self.assertEqual(
            (plan.starting_monthly, plan.currency, plan.annual_increase_rate),
            before,
        )
        self.assertEqual(plan.starting_monthly, Decimal("60000"))
        self.assertEqual(plan.annual_increase_rate, Decimal("0.25"))

    def test_scenario_calculation_does_not_mutate_planning_fx(self) -> None:
        fx = _fx()
        before = tuple((row.year, row.usdtry) for row in fx.rates)
        matrix = _matrix(fx_schedule=fx)
        after = tuple((row.year, row.usdtry) for row in fx.rates)
        self.assertEqual(before, after)
        self.assertIsNone(fx.usdtry_for_year(2032))
        self.assertEqual(fx.usdtry_for_year(2031), Decimal("87"))
        self.assertTrue(
            any(row.availability == GOAL_DATE_UNAVAILABLE for row in matrix.goal_date_extensions)
        )

    def test_complete_valuation_remains_starting_evidence(self) -> None:
        current = _usd(complete=True)
        matrix = _matrix(current=current)
        self.assertTrue(current.valuation_complete)
        self.assertTrue(matrix.valuation_complete)
        self.assertEqual(current.current_value_lower_bound, CURRENT_WEALTH)
        self.assertEqual(matrix.current_wealth, CURRENT_WEALTH)

    def test_indexation_remains_25_percent(self) -> None:
        plan = default_contribution_plan()
        matrix = _matrix(contribution_plan=plan)
        self.assertEqual(plan.annual_increase_rate, Decimal("0.25"))
        self.assertEqual(matrix.indexation_rate, Decimal("0.25"))
        by_year = {row.year: row.monthly for row in matrix.current_plan_schedule}
        self.assertEqual(by_year[2026], Decimal("60000.00"))
        self.assertEqual(by_year[2027], Decimal("75000.00"))
        self.assertEqual(by_year[2028], Decimal("93750.00"))
        self.assertEqual(by_year[2029], Decimal("117187.50"))
        self.assertEqual(by_year[2030], Decimal("146484.38"))
        self.assertEqual(by_year[2031], Decimal("183105.47"))


class TrackingAndCalendarTests(unittest.TestCase):
    def test_tracking_start_2026_09_01_respected(self) -> None:
        self.assertEqual(TRACKING_START, DEFAULT_TRACKING_START)
        rows = contribution_calendar(
            _plan(),
            as_of=AS_OF,
            target_date=date(2031, 12, 31),
            tracking_start=TRACKING_START,
        )
        by_year = {row.year: row for row in rows}
        self.assertEqual(by_year[2026].months, 4)
        self.assertEqual(by_year[2026].annual_total, Decimal("240000.00"))
        self.assertEqual(by_year[2027].months, 12)
        self.assertNotIn(2025, by_year)
        fabricated = contribution_calendar(
            _plan(),
            as_of=date(2026, 1, 1),
            target_date=date(2031, 12, 31),
            tracking_start=None,
        )
        self.assertEqual(next(row.months for row in fabricated if row.year == 2026), 12)
        clipped = contribution_calendar(
            _plan(),
            as_of=date(2026, 1, 1),
            target_date=date(2031, 12, 31),
            tracking_start=TRACKING_START,
        )
        self.assertEqual(next(row.months for row in clipped if row.year == 2026), 4)

    def test_break_even_schedule_uses_solved_starting_monthly(self) -> None:
        matrix = _matrix()
        self.assertEqual(matrix.break_even_schedule[0].monthly, CANONICAL_REQUIRED)
        self.assertEqual(matrix.break_even_schedule[0].year, 2026)
        self.assertEqual(matrix.break_even_schedule[0].months, 4)


class GoalDateFxIsolationTests(unittest.TestCase):
    def test_extended_dates_fail_safely_when_planning_fx_absent(self) -> None:
        matrix = _matrix()
        by_date = {row.target_date: row for row in matrix.goal_date_extensions}
        self.assertEqual(by_date[date(2031, 12, 31)].availability, GOAL_DATE_AVAILABLE)
        self.assertEqual(by_date[date(2031, 12, 31)].projected_wealth, CANONICAL_PROJECTED)
        for year in range(2032, 2037):
            row = by_date[date(year, 12, 31)]
            self.assertEqual(row.availability, GOAL_DATE_UNAVAILABLE)
            self.assertEqual(row.limitation, MISSING_PLANNING_FX)
            self.assertIsNone(row.projected_wealth)
            self.assertIn(year, row.missing_planning_fx_years)
            self.assertNotIn(2031, row.missing_planning_fx_years)

    def test_no_fx_forward_fill(self) -> None:
        fx = _fx()
        row = project_scenario(
            as_of_date=AS_OF,
            current=_usd(),
            contribution_plan=_plan(),
            annual_return_rate=Decimal("0.08"),
            fx_schedule=fx,
            goal=default_wealth_goal_2031(),
            target_date=date(2032, 12, 31),
        )
        self.assertFalse(row.projection_complete)
        self.assertIsNone(row.projected_wealth)
        self.assertEqual(row.limitation, MISSING_PLANNING_FX)
        self.assertEqual(fx.usdtry_for_year(2032), None)
        self.assertEqual(fx.usdtry_for_year(2031), Decimal("87"))
        source = SERVICE.read_text(encoding="utf-8").lower()
        self.assertNotIn("forward-fill", source)
        self.assertNotIn("forward_fill", source)
        self.assertNotIn("interpolat", source)


class SafetyInvariantTests(unittest.TestCase):
    def test_no_market_provider_calls_in_source(self) -> None:
        source = SERVICE.read_text(encoding="utf-8").lower()
        for token in PROVIDER_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token.lower(), source)
        self.assertNotIn("build_portfolio_decision", source)
        self.assertNotIn("save_planning_fx_schedule", source)

    def test_no_db_writes_in_source(self) -> None:
        source = SERVICE.read_text(encoding="utf-8")
        for token in WRITE_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_runtime_does_not_call_providers_or_writes(self) -> None:
        boom = AssertionError("scenario matrix must not call providers or persist")
        with patch("services.current_market_data.fetch_equity_quote", side_effect=boom), patch(
            "services.current_market_data.fetch_fx_rate", side_effect=boom
        ), patch(
            "services.fx_rate_refresh_service.FxRateRefreshService.refresh_pairs",
            side_effect=boom,
        ), patch(
            "services.wealth_planning_fx.save_planning_fx_schedule", side_effect=boom
        ), patch(
            "services.wealth_external_cash_flow.set_contribution_tracking_start",
            side_effect=boom,
        ):
            matrix = _matrix()
        self.assertEqual(matrix.baseline.projected_wealth, CANONICAL_PROJECTED)

    def test_report_bands_are_not_domain_enums(self) -> None:
        models = Path("services/wealth_goal_models.py").read_text(encoding="utf-8")
        self.assertNotIn("TARGET_REACHED", models)
        self.assertNotIn("NEAR_TARGET", models)
        self.assertNotIn("MATERIAL_SHORTFALL", models)
        self.assertNotIn("LARGE_SHORTFALL", models)
        self.assertEqual(report_feasibility_band(Decimal("100")), REPORT_BAND_TARGET_REACHED)
        self.assertEqual(report_feasibility_band(Decimal("49.87")), REPORT_BAND_LARGE_SHORTFALL)
        self.assertEqual(report_feasibility_band(None), REPORT_BAND_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
