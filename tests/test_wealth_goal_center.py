from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from services.wealth_contract import (
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_TRANSFER_IN,
    TXN_TYPE_TRANSFER_OUT,
    TXN_TYPE_WITHDRAW,
)
from services.wealth_goal_models import (
    ContributionPlan,
    CurrentWealthSnapshot,
    GoalEvidenceStatus,
    ProjectionLimitation,
    ReturnScenario,
    WealthGoal,
    default_contribution_plan,
)
from services.wealth_goal_planning import (
    build_what_if_projection,
    contribution_year_schedule,
    plan_vs_actual_for_year,
    planning_conversion,
    solve_required_starting_monthly,
)
from services.wealth_projection_engine import project_wealth_goal

AS_OF = date(2026, 8, 17)
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".delete(",
    "create_account",
)
CHANGED = (
    Path("services/wealth_goal_planning.py"),
    Path("components/wealth_goal_center_ui.py"),
)


def _usd(amount: str, *, complete: bool = True, unvalued=()) -> CurrentWealthSnapshot:
    return CurrentWealthSnapshot(
        currency="USD",
        current_value_lower_bound=Decimal(amount),
        valuation_complete=complete,
        unvalued_symbols=tuple(unvalued),
    )


def _txn(txn_type: str, amount: float, *, currency: str = "TRY", executed_at: str = "2026-03-01T12:00:00+00:00", account_id: str = "acc-1") -> dict:
    return {
        "id": f"{txn_type}-{amount}-{executed_at}",
        "account_id": account_id,
        "txn_type": txn_type,
        "quantity": 0,
        "amount": amount,
        "currency": currency,
        "executed_at": executed_at,
        "created_at": executed_at,
    }


class GoalCenterWiringTests(unittest.TestCase):
    def test_goal_center_uses_engine_outputs(self) -> None:
        ui = Path("components/wealth_goal_center_ui.py").read_text(encoding="utf-8")
        page = Path("pages/10_Wealth.py").read_text(encoding="utf-8")
        self.assertIn("project_wealth_goal_scenarios", ui)
        self.assertIn("build_what_if_projection", ui)
        self.assertIn("solve_required_starting_monthly", ui)
        self.assertNotIn("annual_rate / 12", ui)
        self.assertIn("render_wealth_goal_center", page)
        self.assertIn("2031 Hedef", page)
        self.assertIn("CandidatePriceService", ui)
        self.assertIn("nabi_client=None", ui)
        self.assertIn("enrich_nabi=False", ui)
        self.assertIn("persisted current FX", ui)
        self.assertNotIn("FxRateRefreshService", ui)

    def test_partial_valuation_lower_bound_copy(self) -> None:
        ui = Path("components/wealth_goal_center_ui.py").read_text(encoding="utf-8")
        self.assertIn("Ölçülebilen servet: en az", ui)
        self.assertIn("2031 Servet Hedefi", ui)
        self.assertIn("Hedefe kalan ölçülebilir fark", ui)
        self.assertNotIn("Toplam servetin", ui)

    def test_indeterminate_is_not_behind(self) -> None:
        ui = Path("components/wealth_goal_center_ui.py").read_text(encoding="utf-8")
        self.assertIn("Yetersiz değerleme / kur varsayımı", ui)
        self.assertNotIn("geride", ui.lower())
        self.assertEqual(
            GoalEvidenceStatus.INDETERMINATE.value,
            "INDETERMINATE",
        )


class ContributionScheduleTests(unittest.TestCase):
    def test_annual_schedule_from_plan_not_hardcoded_rows(self) -> None:
        plan = default_contribution_plan()
        rows = contribution_year_schedule(plan, as_of=date(2026, 1, 1), through_year=2031)
        by_year = {row.year: row.monthly for row in rows}
        self.assertEqual(by_year[2026], Decimal("60000.00"))
        self.assertEqual(by_year[2027], Decimal("75000.00"))
        self.assertEqual(by_year[2028], Decimal("93750.00"))
        self.assertEqual(by_year[2029], Decimal("117187.50"))
        self.assertEqual(by_year[2030], Decimal("146484.38"))
        self.assertEqual(by_year[2031], Decimal("183105.47"))


class ActualContributionTests(unittest.TestCase):
    def test_transfers_excluded_from_actual_contributions(self) -> None:
        plan = default_contribution_plan()
        result = plan_vs_actual_for_year(
            plan,
            as_of=AS_OF,
            account_ids=["acc-1", "acc-2"],
            transactions=[
                _txn(TXN_TYPE_TRANSFER_OUT, 50000, account_id="acc-1"),
                _txn(TXN_TYPE_TRANSFER_IN, 50000, account_id="acc-2"),
                _txn(TXN_TYPE_DEPOSIT, 10000),
            ],
        )
        self.assertTrue(result.available)
        self.assertEqual(result.actual_net_external, Decimal("10000.00"))

    def test_dividends_excluded_from_actual_contributions(self) -> None:
        plan = default_contribution_plan()
        result = plan_vs_actual_for_year(
            plan,
            as_of=AS_OF,
            account_ids=["acc-1"],
            transactions=[
                _txn(TXN_TYPE_DIVIDEND, 8000),
                _txn(TXN_TYPE_DEPOSIT, 20000),
            ],
        )
        self.assertEqual(result.actual_net_external, Decimal("20000.00"))

    def test_plan_vs_actual_math(self) -> None:
        plan = default_contribution_plan()
        result = plan_vs_actual_for_year(
            plan,
            as_of=AS_OF,
            account_ids=["acc-1"],
            transactions=[
                _txn(TXN_TYPE_DEPOSIT, 180000),
                _txn(TXN_TYPE_WITHDRAW, 30000),
            ],
        )
        self.assertEqual(result.planned_year_total, Decimal("720000.00"))
        self.assertEqual(result.actual_net_external, Decimal("150000.00"))
        self.assertEqual(result.difference, Decimal("-570000.00"))
        self.assertEqual(result.completion_pct, Decimal("20.83"))
        self.assertFalse(result.evidence_partial)

    def test_buy_only_ledger_is_partial_contribution_evidence(self) -> None:
        plan = default_contribution_plan()
        result = plan_vs_actual_for_year(
            plan,
            as_of=AS_OF,
            account_ids=["acc-1"],
            transactions=[
                _txn("buy", 50000, currency="USD"),
            ],
        )
        self.assertTrue(result.available)
        self.assertTrue(result.evidence_partial)
        self.assertEqual(result.actual_net_external, Decimal("0.00"))
        self.assertIsNone(result.completion_pct)
        self.assertTrue(any("nakit katkı" in note for note in result.warnings))


class WhatIfTests(unittest.TestCase):
    def test_what_if_monthly_contribution_changes_totals(self) -> None:
        low = build_what_if_projection(
            as_of_date=date(2026, 12, 31),
            current=_usd("0"),
            monthly_contribution=Decimal("100"),
            contribution_currency="USD",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0"),
            target_date=date(2027, 1, 31),
        )
        high = build_what_if_projection(
            as_of_date=date(2026, 12, 31),
            current=_usd("0"),
            monthly_contribution=Decimal("200"),
            contribution_currency="USD",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0"),
            target_date=date(2027, 1, 31),
        )
        self.assertEqual(low.total_projected_contributions, Decimal("100.00"))
        self.assertEqual(high.total_projected_contributions, Decimal("200.00"))

    def test_what_if_annual_increase(self) -> None:
        result = build_what_if_projection(
            as_of_date=date(2026, 11, 30),
            current=_usd("0"),
            monthly_contribution=Decimal("100"),
            contribution_currency="USD",
            annual_increase_rate=Decimal("0.25"),
            annual_return_rate=Decimal("0"),
            target_date=date(2027, 1, 31),
        )
        self.assertEqual(result.total_projected_contributions, Decimal("225.00"))

    def test_what_if_return_rate(self) -> None:
        flat = build_what_if_projection(
            as_of_date=date(2026, 12, 31),
            current=_usd("1000"),
            monthly_contribution=Decimal("0"),
            contribution_currency="USD",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0"),
            target_date=date(2027, 1, 31),
        )
        growth = build_what_if_projection(
            as_of_date=date(2026, 12, 31),
            current=_usd("1000"),
            monthly_contribution=Decimal("0"),
            contribution_currency="USD",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0.12"),
            target_date=date(2027, 1, 31),
        )
        self.assertEqual(flat.projected_target_date_value, Decimal("1000.00"))
        self.assertEqual(growth.projected_target_date_value, Decimal("1010.00"))

    def test_explicit_usdtry_planning_assumption(self) -> None:
        conversion = planning_conversion(Decimal("30"))
        result = build_what_if_projection(
            as_of_date=date(2026, 11, 30),
            current=_usd("0"),
            monthly_contribution=Decimal("60000"),
            contribution_currency="TRY",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0"),
            target_date=date(2026, 12, 31),
            conversion=conversion,
        )
        self.assertTrue(result.projection_complete)
        self.assertEqual(result.projected_target_date_value, Decimal("2000.00"))

    def test_what_if_target_date_changes_month_count(self) -> None:
        near = build_what_if_projection(
            as_of_date=date(2026, 12, 31),
            current=_usd("0"),
            monthly_contribution=Decimal("100"),
            contribution_currency="USD",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0"),
            target_date=date(2027, 1, 31),
        )
        far = build_what_if_projection(
            as_of_date=date(2026, 12, 31),
            current=_usd("0"),
            monthly_contribution=Decimal("100"),
            contribution_currency="USD",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0"),
            target_date=date(2027, 3, 31),
        )
        self.assertEqual(near.month_count, 1)
        self.assertEqual(far.month_count, 3)
        self.assertGreater(far.projected_target_date_value, near.projected_target_date_value)

    def test_user_fx_does_not_value_current_bist_assets(self) -> None:
        snapshot = _usd("10000", complete=False, unvalued=("BIMAS", "ASELS", "TUPRS"))
        result = build_what_if_projection(
            as_of_date=AS_OF,
            current=snapshot,
            monthly_contribution=Decimal("60000"),
            contribution_currency="TRY",
            annual_increase_rate=Decimal("0.25"),
            annual_return_rate=Decimal("0.08"),
            conversion=planning_conversion(Decimal("34")),
        )
        self.assertEqual(result.current_value_lower_bound, Decimal("10000.00"))
        self.assertEqual(snapshot.unvalued_symbols, ("BIMAS", "ASELS", "TUPRS"))
        self.assertFalse(result.valuation_complete)


class RequiredContributionTests(unittest.TestCase):
    def test_binary_search_reaches_target_within_tolerance(self) -> None:
        goal = WealthGoal("t", Decimal("1200"), date(2027, 12, 31), "USD")
        solved = solve_required_starting_monthly(
            as_of_date=date(2026, 12, 31),
            current=_usd("0"),
            contribution_currency="USD",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("0"),
            goal=goal,
            tolerance=Decimal("0.01"),
        )
        self.assertTrue(solved.available)
        self.assertEqual(solved.starting_monthly, Decimal("100.00"))
        check = project_wealth_goal(
            goal=goal,
            as_of_date=date(2026, 12, 31),
            current=_usd("0"),
            contribution_plan=ContributionPlan(solved.starting_monthly, "USD", Decimal("0")),
            scenario=ReturnScenario("x", Decimal("0")),
        )
        self.assertGreaterEqual(check.projected_target_date_value, Decimal("1199.00"))
        self.assertLessEqual(check.projected_target_date_value, Decimal("1201.00"))

    def test_insufficient_fx_returns_unavailable(self) -> None:
        solved = solve_required_starting_monthly(
            as_of_date=AS_OF,
            current=_usd("10000"),
            contribution_currency="TRY",
            annual_increase_rate=Decimal("0.25"),
            annual_return_rate=Decimal("0.08"),
        )
        self.assertFalse(solved.available)
        self.assertIsNone(solved.starting_monthly)
        self.assertEqual(solved.limitation, ProjectionLimitation.FX_CONVERSION_REQUIRED)

    def test_impossible_required_contribution_is_unavailable(self) -> None:
        goal = WealthGoal("t", Decimal("500000"), date(2027, 1, 31), "USD")
        solved = solve_required_starting_monthly(
            as_of_date=date(2026, 12, 31),
            current=_usd("0"),
            contribution_currency="USD",
            annual_increase_rate=Decimal("0"),
            annual_return_rate=Decimal("-0.99"),
            goal=goal,
            max_monthly=Decimal("10"),
        )
        self.assertFalse(solved.available)
        self.assertIsNone(solved.starting_monthly)


class SafetyInvariantTests(unittest.TestCase):
    def test_no_remote_fx_or_provider_calls(self) -> None:
        for path in CHANGED:
            source = path.read_text(encoding="utf-8").lower()
            for token in PROVIDER_TOKENS:
                with self.subTest(path=str(path), token=token):
                    self.assertNotIn(token.lower(), source)

    def test_no_ledger_writes(self) -> None:
        for path in (
            Path("services/wealth_goal_planning.py"),
            Path("components/wealth_goal_center_ui.py"),
        ):
            source = path.read_text(encoding="utf-8")
            for token in WRITE_TOKENS:
                with self.subTest(path=str(path), token=token):
                    self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
