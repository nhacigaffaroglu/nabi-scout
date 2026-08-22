from __future__ import annotations

import inspect
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from services.wealth_goal_models import (
    ContributionPlan,
    CurrentWealthSnapshot,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_goal_scenario_service import (
    EXTENDED_HORIZON_AVAILABLE,
    EXTENDED_HORIZON_BLOCKED,
    analyze_extended_goal_horizon,
)
from services.wealth_planning_fx import (
    CONTINUATION_ANCHOR_YEARS,
    EXTENDED_PLANNING_FX_YEARS,
    PROPOSED_PLANNING_FX_STATUS,
    propose_planning_fx_continuation,
    required_planning_fx_years,
    schedule_from_mapping,
)


AS_OF = date(2026, 8, 21)
CURRENT_WEALTH = Decimal("79508.4249")
PLANNING_FX = {2026: 51, 2027: 59, 2028: 66, 2029: 73, 2030: 80, 2031: 87}
CANONICAL_PROJECTED = Decimal("249356.14")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "TwelveData",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "BorsaIstanbul",
)
WRITE_TOKENS = (
    "replace_schedule",
    "save_planning_fx_schedule",
    "post_transaction",
    "upsert_rate",
    "capture_portfolio_snapshot",
    "set_contribution_tracking_start",
)
FX_MODULE = Path("services/wealth_planning_fx.py")
SCENARIO_MODULE = Path("services/wealth_goal_scenario_service.py")


def _usd() -> CurrentWealthSnapshot:
    return CurrentWealthSnapshot(
        currency="USD",
        current_value_lower_bound=CURRENT_WEALTH,
        valuation_complete=True,
    )


def _plan() -> ContributionPlan:
    return ContributionPlan(Decimal("60000"), "TRY", Decimal("0.25"))


def _persisted_fx():
    return schedule_from_mapping(PLANNING_FX)


def _approved_through_2036():
    proposal = propose_planning_fx_continuation(_persisted_fx())
    merged = dict(PLANNING_FX)
    merged.update(proposal.as_mapping())
    return schedule_from_mapping(merged)


class ContinuationProposalTests(unittest.TestCase):
    def test_proposal_follows_2029_2031_increment_and_is_not_saved(self) -> None:
        fx = _persisted_fx()
        proposal = propose_planning_fx_continuation(fx)
        self.assertEqual(proposal.status, PROPOSED_PLANNING_FX_STATUS)
        self.assertEqual(proposal.anchor_years, CONTINUATION_ANCHOR_YEARS)
        self.assertEqual(proposal.observed_increments, (Decimal("7"), Decimal("7")))
        self.assertEqual(proposal.continuation_increment, Decimal("7"))
        self.assertEqual(proposal.observed_change_pct, (Decimal("9.59"), Decimal("8.75")))
        by_year = {row.year: row for row in proposal.years}
        self.assertEqual(tuple(by_year), EXTENDED_PLANNING_FX_YEARS)
        self.assertEqual(by_year[2032].proposed_usdtry, Decimal("94"))
        self.assertEqual(by_year[2033].proposed_usdtry, Decimal("101"))
        self.assertEqual(by_year[2034].proposed_usdtry, Decimal("108"))
        self.assertEqual(by_year[2035].proposed_usdtry, Decimal("115"))
        self.assertEqual(by_year[2036].proposed_usdtry, Decimal("122"))
        self.assertEqual(by_year[2032].implied_annual_change_pct, Decimal("8.05"))
        self.assertEqual(by_year[2032].status, PROPOSED_PLANNING_FX_STATUS)
        self.assertIsNone(fx.usdtry_for_year(2032))
        self.assertEqual(fx.usdtry_for_year(2031), Decimal("87"))
        source = inspect.getsource(propose_planning_fx_continuation)
        self.assertNotIn("save_planning_fx_schedule", source)
        self.assertNotIn("replace_schedule", source)

    def test_proposal_does_not_forward_fill_persisted_schedule(self) -> None:
        fx = _persisted_fx()
        propose_planning_fx_continuation(fx)
        self.assertEqual(
            fx.missing_years(required_planning_fx_years(AS_OF, date(2036, 12, 31))),
            EXTENDED_PLANNING_FX_YEARS,
        )


class ExtendedHorizonGateTests(unittest.TestCase):
    def test_blocked_when_2032_2036_unapproved(self) -> None:
        fx = _persisted_fx()
        analysis = analyze_extended_goal_horizon(
            as_of_date=AS_OF,
            current=_usd(),
            fx_schedule=fx,
            contribution_plan=_plan(),
        )
        self.assertEqual(analysis.status, EXTENDED_HORIZON_BLOCKED)
        self.assertEqual(analysis.missing_planning_fx_years, EXTENDED_PLANNING_FX_YEARS)
        self.assertEqual(analysis.target_year_matrix, ())
        self.assertEqual(analysis.required_monthly_by_goal_year, ())
        self.assertEqual(analysis.earliest_reach, ())
        self.assertEqual(analysis.return_sensitivity, ())
        self.assertEqual(analysis.proposal_status, PROPOSED_PLANNING_FX_STATUS)
        self.assertIsNone(fx.usdtry_for_year(2032))
        self.assertEqual(default_wealth_goal_2031().target_date, date(2031, 12, 31))
        self.assertEqual(default_contribution_plan().starting_monthly, Decimal("60000"))

    def test_available_in_memory_schedule_does_not_mutate_persisted_path(self) -> None:
        persisted = _persisted_fx()
        approved = _approved_through_2036()
        analysis = analyze_extended_goal_horizon(
            as_of_date=AS_OF,
            current=_usd(),
            fx_schedule=approved,
            contribution_plan=_plan(),
        )
        self.assertEqual(analysis.status, EXTENDED_HORIZON_AVAILABLE)
        cell_2031_60k = analysis.target_year_matrix[0][0]
        self.assertEqual(cell_2031_60k.target_date, date(2031, 12, 31))
        self.assertEqual(cell_2031_60k.projected_wealth, CANONICAL_PROJECTED)
        self.assertTrue(analysis.required_monthly_by_goal_year[0].available)
        later_60k = [row.projected_wealth for row in analysis.target_year_matrix[0]]
        self.assertTrue(all(item is not None for item in later_60k))
        self.assertEqual(later_60k, sorted(later_60k))
        self.assertIsNone(persisted.usdtry_for_year(2032))
        self.assertEqual(persisted.usdtry_for_year(2031), Decimal("87"))
        self.assertEqual(default_wealth_goal_2031().target_date, date(2031, 12, 31))

    def test_earliest_reach_uses_engine_month_end_not_interpolation(self) -> None:
        from calendar import monthrange

        analysis = analyze_extended_goal_horizon(
            as_of_date=AS_OF,
            current=_usd(),
            fx_schedule=_approved_through_2036(),
            contribution_plan=_plan(),
        )
        self.assertTrue(analysis.earliest_reach)
        for row in analysis.earliest_reach:
            if not row.reached:
                self.assertEqual(row.label, "NOT REACHED BY 2036")
                self.assertIsNone(row.reach_date)
                continue
            self.assertIsNotNone(row.reach_date)
            last_day = monthrange(row.reach_date.year, row.reach_date.month)[1]
            self.assertEqual(row.reach_date.day, last_day)
            self.assertEqual(row.label, str(row.reach_year))


class SafetyInvariantTests(unittest.TestCase):
    def test_no_provider_or_write_calls(self) -> None:
        boom = AssertionError("extended horizon must not persist or fetch FX")
        with patch(
            "services.wealth_planning_fx.save_planning_fx_schedule", side_effect=boom
        ), patch(
            "services.current_market_data.fetch_fx_rate", side_effect=boom
        ), patch(
            "services.current_market_data.fetch_equity_quote", side_effect=boom
        ):
            blocked = analyze_extended_goal_horizon(
                as_of_date=AS_OF,
                current=_usd(),
                fx_schedule=_persisted_fx(),
                contribution_plan=_plan(),
            )
            available = analyze_extended_goal_horizon(
                as_of_date=AS_OF,
                current=_usd(),
                fx_schedule=_approved_through_2036(),
                contribution_plan=_plan(),
            )
        self.assertEqual(blocked.status, EXTENDED_HORIZON_BLOCKED)
        self.assertEqual(available.status, EXTENDED_HORIZON_AVAILABLE)

    def test_source_has_no_provider_or_write_tokens_in_new_helpers(self) -> None:
        propose_src = inspect.getsource(propose_planning_fx_continuation)
        analyze_src = inspect.getsource(analyze_extended_goal_horizon)
        for source in (propose_src, analyze_src):
            lower = source.lower()
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token.lower(), lower)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
        fx_text = FX_MODULE.read_text(encoding="utf-8").lower()
        self.assertNotIn("forward-fill", fx_text)
        self.assertNotIn("interpolat", fx_text)
        scenario_text = SCENARIO_MODULE.read_text(encoding="utf-8")
        self.assertIn("Never persists planning FX", scenario_text)


if __name__ == "__main__":
    unittest.main()
