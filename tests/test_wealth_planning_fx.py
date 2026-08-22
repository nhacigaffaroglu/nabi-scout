from __future__ import annotations

import math
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.portfolio_decision_intelligence import build_portfolio_decision
from services.wealth_contract import WealthValidationError
from services.wealth_goal_models import (
    ContributionPlan,
    ConversionAssumption,
    CurrentWealthSnapshot,
    ProjectionLimitation,
    ReturnScenario,
    WealthGoal,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_goal_planning import solve_required_starting_monthly
from services.wealth_planning_fx import (
    PLANNING_FX_PROVENANCE,
    PlanningFxCompleteness,
    parse_usdtry_assumption,
    required_planning_fx_years,
    schedule_from_mapping,
    usd_from_try,
)
from services.wealth_projection_engine import project_wealth_goal
from tests.test_portfolio_decision_intelligence import _complete_usd_view


AS_OF = date(2026, 8, 18)
PROVIDER_TOKENS = (
    "FMPClient",
    "openai",
    "SECFinancialClient",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)
ENGINE = Path("services/wealth_planning_fx.py")
PROJECTION = Path("services/wealth_projection_engine.py")
DIETZ = Path("services/wealth_performance_engine.py")


def _usd(amount: str = "10000") -> CurrentWealthSnapshot:
    return CurrentWealthSnapshot(
        currency="USD",
        current_value_lower_bound=Decimal(amount),
        valuation_complete=True,
    )


def _try_plan(monthly: str = "60000") -> ContributionPlan:
    return ContributionPlan(Decimal(monthly), "TRY", Decimal("0"))


def _goal(target: str = "500000", when: date = date(2031, 12, 31)) -> WealthGoal:
    return WealthGoal("t", Decimal(target), when, "USD")


def _years(as_of=AS_OF, target=date(2031, 12, 31)):
    return required_planning_fx_years(as_of, target)


def _complete(rate="50", as_of=AS_OF, target=date(2031, 12, 31)):
    return schedule_from_mapping({year: Decimal(rate) for year in _years(as_of, target)})


class YearAndParseTests(unittest.TestCase):
    def test_required_years_are_dynamic(self) -> None:
        self.assertEqual(_years(), (2026, 2027, 2028, 2029, 2030, 2031))
        self.assertEqual(
            required_planning_fx_years(date(2028, 1, 1), date(2030, 6, 1)),
            (2028, 2029, 2030),
        )

    def test_usdtry_direction_divides(self) -> None:
        self.assertEqual(usd_from_try(Decimal("60000"), Decimal("50")), Decimal("1200"))
        self.assertNotEqual(usd_from_try(Decimal("60000"), Decimal("50")), Decimal("3000000"))

    def test_zero_negative_nan_inf_rejected(self) -> None:
        for raw in (0, "0", -1, Decimal("-2"), "NaN", Decimal("NaN"), math.inf, -math.inf, "abc"):
            with self.subTest(raw=raw):
                with self.assertRaises(WealthValidationError):
                    parse_usdtry_assumption(raw)


class CompletenessTests(unittest.TestCase):
    def test_none_and_partial_are_incomplete(self) -> None:
        empty = schedule_from_mapping({})
        self.assertEqual(
            empty.completeness(
                as_of=AS_OF,
                target_date=date(2031, 12, 31),
                contribution_currency="TRY",
                goal_currency="USD",
            ),
            PlanningFxCompleteness.NONE,
        )
        self.assertEqual(empty.missing_years(_years()), _years())
        partial = schedule_from_mapping({2026: 40, 2027: 42})
        self.assertEqual(
            partial.completeness(
                as_of=AS_OF,
                target_date=date(2031, 12, 31),
                contribution_currency="TRY",
                goal_currency="USD",
            ),
            PlanningFxCompleteness.PARTIAL,
        )
        self.assertEqual(partial.missing_years(_years()), (2028, 2029, 2030, 2031))

    def test_complete_path_and_same_currency_not_required(self) -> None:
        complete = _complete()
        self.assertTrue(
            complete.is_complete(
                as_of=AS_OF,
                target_date=date(2031, 12, 31),
                contribution_currency="TRY",
                goal_currency="USD",
            )
        )
        empty = schedule_from_mapping({})
        self.assertEqual(
            empty.completeness(
                as_of=AS_OF,
                target_date=date(2031, 12, 31),
                contribution_currency="USD",
                goal_currency="USD",
            ),
            PlanningFxCompleteness.NOT_REQUIRED,
        )


class ProjectionFxTests(unittest.TestCase):
    def test_no_assumptions_projection_unavailable(self) -> None:
        result = project_wealth_goal(
            as_of_date=AS_OF,
            current=_usd(),
            contribution_plan=_try_plan(),
            scenario=ReturnScenario("Base", Decimal("0")),
            goal=_goal(),
            fx_schedule=schedule_from_mapping({}),
        )
        self.assertFalse(result.projection_complete)
        self.assertIsNone(result.projected_target_date_value)
        self.assertIn(ProjectionLimitation.FX_CONVERSION_REQUIRED, result.limitations)

    def test_partial_does_not_forward_fill(self) -> None:
        result = project_wealth_goal(
            as_of_date=date(2026, 11, 30),
            current=_usd("0"),
            contribution_plan=_try_plan("50000"),
            scenario=ReturnScenario("flat", Decimal("0")),
            goal=_goal("1000000", date(2027, 1, 31)),
            fx_schedule=schedule_from_mapping({2026: 50}),
        )
        self.assertFalse(result.projection_complete)
        self.assertIsNone(result.projected_target_date_value)
        self.assertEqual(
            schedule_from_mapping({2026: 50}).missing_years((2026, 2027)),
            (2027,),
        )

    def test_year_specific_rates_and_no_inversion(self) -> None:
        result = project_wealth_goal(
            as_of_date=date(2026, 11, 30),
            current=_usd("0"),
            contribution_plan=_try_plan("50000"),
            scenario=ReturnScenario("flat", Decimal("0")),
            goal=_goal("1000000", date(2027, 1, 31)),
            fx_schedule=schedule_from_mapping({2026: 50, 2027: 25}),
        )
        self.assertTrue(result.projection_complete)
        self.assertEqual(result.projected_target_date_value, Decimal("3000.00"))
        self.assertNotEqual(result.projected_target_date_value, Decimal("3750000.00"))

    def test_usd_current_value_not_double_converted(self) -> None:
        result = project_wealth_goal(
            as_of_date=date(2026, 11, 30),
            current=_usd("10000"),
            contribution_plan=_try_plan("50000"),
            scenario=ReturnScenario("flat", Decimal("0")),
            goal=_goal("1000000", date(2026, 12, 31)),
            fx_schedule=schedule_from_mapping({2026: 50}),
        )
        self.assertEqual(result.projected_target_date_value, Decimal("11000.00"))
        self.assertEqual(result.current_value_lower_bound, Decimal("10000.00"))

    def test_required_monthly_unavailable_until_complete(self) -> None:
        incomplete = solve_required_starting_monthly(
            as_of_date=AS_OF,
            current=_usd(),
            contribution_currency="TRY",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0.08"),
            fx_schedule=schedule_from_mapping({2026: 40}),
            goal=_goal(),
        )
        self.assertFalse(incomplete.available)
        self.assertIsNone(incomplete.starting_monthly)
        self.assertEqual(incomplete.limitation, ProjectionLimitation.FX_CONVERSION_REQUIRED)
        complete = solve_required_starting_monthly(
            as_of_date=date(2026, 11, 30),
            current=_usd("0"),
            contribution_currency="TRY",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0"),
            fx_schedule=schedule_from_mapping({2026: 30}),
            goal=_goal("2000", date(2026, 12, 31)),
        )
        self.assertTrue(complete.available)
        self.assertIsNotNone(complete.starting_monthly)
        self.assertGreater(complete.starting_monthly, Decimal("0"))


class DecisionAndSafetyTests(unittest.TestCase):
    def test_decision_intelligence_no_fake_gap_when_incomplete(self) -> None:
        view = build_portfolio_decision(
            _complete_usd_view(),
            as_of_date=AS_OF,
            plan=default_contribution_plan(),
            fx_schedule=schedule_from_mapping({2026: 40}),
            contribution_tracking_start=date(2026, 9, 1),
        )
        self.assertIn("missing_planning_fx", [row.id for row in view.actions])
        action = next(row for row in view.actions if row.id == "missing_planning_fx")
        self.assertIn(2027, action.context["missing_years"])
        self.assertNotIn("contribution_plan_below_required", [row.id for row in view.actions])

    def test_complete_schedule_allows_canonical_solver_path(self) -> None:
        view = build_portfolio_decision(
            _complete_usd_view(value=480000.0),
            as_of_date=date(2026, 11, 30),
            plan=_try_plan("60000"),
            fx_schedule=schedule_from_mapping({2026: 30}),
            goal=_goal("2000", date(2026, 12, 31)),
        )
        self.assertNotIn("missing_planning_fx", [row.id for row in view.actions])

    def test_no_provider_interpolation_or_tracking_writes(self) -> None:
        source = ENGINE.read_text(encoding="utf-8").lower()
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token.lower(), source)
        self.assertNotIn("forward-fill", source)
        self.assertNotIn("interpolat", source)
        self.assertNotIn("fx_rate_refresh", source)
        self.assertNotIn("contribution_tracking_start_date", ENGINE.read_text(encoding="utf-8"))
        self.assertNotIn("wealth_planning_fx", DIETZ.read_text(encoding="utf-8"))
        self.assertIn("USER_DEFINED", ENGINE.read_text(encoding="utf-8"))
        self.assertIn(PLANNING_FX_PROVENANCE, ENGINE.read_text(encoding="utf-8"))
        self.assertIn("fx_schedule", PROJECTION.read_text(encoding="utf-8"))

    def test_legacy_single_conversion_still_works(self) -> None:
        result = project_wealth_goal(
            as_of_date=date(2026, 11, 30),
            current=_usd("0"),
            contribution_plan=default_contribution_plan(),
            scenario=ReturnScenario("flat", Decimal("0")),
            conversion=ConversionAssumption("TRY", "USD", Decimal("30")),
            goal=_goal("1000000", date(2026, 12, 31)),
        )
        self.assertEqual(result.projected_target_date_value, Decimal("2000.00"))


class RepositorySaveTests(unittest.TestCase):
    def test_save_path_uses_repository_not_ledger(self) -> None:
        from services.wealth_planning_fx import save_planning_fx_schedule

        wealth = MagicMock()
        wealth.user_id = "user-1"
        wealth.client = MagicMock()
        repo_client = wealth.client
        table = MagicMock()
        repo_client.table.return_value = table
        table.delete.return_value = table
        table.eq.return_value = table
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"year": 2026, "usdtry": "40"}])
        save_planning_fx_schedule(wealth, portfolio_id="pf-1", values={2026: 40})
        self.assertTrue(repo_client.table.called)
        self.assertNotIn("wealth_transactions", str(repo_client.table.call_args_list))

    def test_additional_years_insert_without_replacing_existing(self) -> None:
        from services.wealth_planning_fx import persist_additional_planning_fx_years

        wealth = MagicMock()
        wealth.user_id = "user-1"
        wealth.client = MagicMock()
        existing = [
            {"year": year, "usdtry": str(rate), "provenance": PLANNING_FX_PROVENANCE}
            for year, rate in (
                (2026, 51),
                (2027, 59),
                (2028, 66),
                (2029, 73),
                (2030, 80),
                (2031, 87),
            )
        ]
        inserted = [
            {"year": year, "usdtry": str(rate), "provenance": PLANNING_FX_PROVENANCE}
            for year, rate in (
                (2032, 94),
                (2033, 101),
                (2034, 108),
                (2035, 115),
                (2036, 122),
            )
        ]
        with patch(
            "services.wealth_planning_fx.load_planning_fx_schedule",
            side_effect=[
                schedule_from_mapping({2026: 51, 2027: 59, 2028: 66, 2029: 73, 2030: 80, 2031: 87}),
                schedule_from_mapping(
                    {
                        2026: 51,
                        2027: 59,
                        2028: 66,
                        2029: 73,
                        2030: 80,
                        2031: 87,
                        2032: 94,
                        2033: 101,
                        2034: 108,
                        2035: 115,
                        2036: 122,
                    }
                ),
            ],
        ), patch(
            "services.wealth_planning_fx.WealthPlanningFxRepository"
        ) as repo_cls:
            repo = repo_cls.return_value
            repo.list_for_portfolio.return_value = existing
            repo.insert_absent_years.return_value = inserted
            schedule, count = persist_additional_planning_fx_years(
                wealth,
                portfolio_id="pf-1",
                values={2032: 94, 2033: 101, 2034: 108, 2035: 115, 2036: 122},
            )
        repo.replace_schedule.assert_not_called()
        repo.insert_absent_years.assert_called_once()
        self.assertEqual(count, 5)
        self.assertEqual(schedule.usdtry_for_year(2026), Decimal("51"))
        self.assertEqual(schedule.usdtry_for_year(2031), Decimal("87"))
        self.assertEqual(schedule.usdtry_for_year(2036), Decimal("122"))

    def test_additional_years_cannot_change_existing(self) -> None:
        from services.wealth_planning_fx import persist_additional_planning_fx_years

        wealth = MagicMock()
        wealth.user_id = "user-1"
        wealth.client = MagicMock()
        with patch(
            "services.wealth_planning_fx.load_planning_fx_schedule",
            return_value=schedule_from_mapping({2026: 51, 2031: 87}),
        ), patch(
            "services.wealth_planning_fx.WealthPlanningFxRepository"
        ) as repo_cls:
            with self.assertRaises(WealthValidationError):
                persist_additional_planning_fx_years(
                    wealth,
                    portfolio_id="pf-1",
                    values={2031: 99},
                )
            repo_cls.return_value.insert_absent_years.assert_not_called()
            repo_cls.return_value.replace_schedule.assert_not_called()


if __name__ == "__main__":
    unittest.main()
