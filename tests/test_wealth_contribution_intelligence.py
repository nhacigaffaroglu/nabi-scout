from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from services.wealth_contract import (
    TXN_TYPE_BUY,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_FEE,
    TXN_TYPE_SELL,
    TXN_TYPE_TRANSFER_IN,
    TXN_TYPE_TRANSFER_OUT,
    TXN_TYPE_WITHDRAW,
)
from services.wealth_contribution_intelligence import (
    ContributionEvidenceQuality,
    MonthlyActionStatus,
    PerformanceEvidenceQuality,
    PlanAdequacyStatus,
    PlanAttributionStatus,
    build_contribution_intelligence,
    select_period_start_snapshot,
)
from services.wealth_goal_models import (
    ContributionPlan,
    CurrentWealthSnapshot,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_external_cash_flow import ContributionReconciliation
from services.wealth_goal_planning import (
    monthly_for_year,
    planning_conversion,
    solve_required_starting_monthly,
)
from services.wealth_performance_engine import snapshot_view_from_row
from services.wealth_timeline_contract import PortfolioSnapshotView

AS_OF = date(2026, 8, 17)
ACCOUNT = "acc-1"
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
    Path("services/wealth_contribution_intelligence.py"),
    Path("components/wealth_goal_center_ui.py"),
)


def _usd(amount: str, *, complete: bool = True, unvalued=()) -> CurrentWealthSnapshot:
    return CurrentWealthSnapshot(
        currency="USD",
        current_value_lower_bound=Decimal(amount),
        valuation_complete=complete,
        unvalued_symbols=tuple(unvalued),
    )


def _txn(
    txn_type: str,
    amount: float,
    *,
    currency: str = "TRY",
    executed_at: str = "2026-08-10T12:00:00+00:00",
    account_id: str = ACCOUNT,
) -> dict:
    return {
        "id": f"{txn_type}-{amount}-{executed_at}-{account_id}",
        "account_id": account_id,
        "txn_type": txn_type,
        "quantity": 0,
        "amount": amount,
        "currency": currency,
        "executed_at": executed_at,
        "created_at": executed_at,
    }


def _recon(through: date = AS_OF, portfolio_id: str = "pf-1") -> tuple[ContributionReconciliation, ...]:
    return (ContributionReconciliation(portfolio_id=portfolio_id, reconciled_through=through),)


_DEFAULT_TRACKING = object()


def _intel(
    transactions,
    *,
    current=None,
    conversion=None,
    account_ids=None,
    plan=None,
    as_of=AS_OF,
    start_snapshot=None,
    end_snapshot=None,
    reconciled: bool = False,
    contribution_reconciliations=None,
    tracking_start=_DEFAULT_TRACKING,
):
    recons = contribution_reconciliations
    if recons is None and reconciled:
        recons = _recon(as_of)
    return build_contribution_intelligence(
        as_of_date=as_of,
        current=current or _usd("10000", complete=False, unvalued=("BIMAS",)),
        transactions=transactions,
        account_ids=[ACCOUNT] if account_ids is None else account_ids,
        plan=plan or default_contribution_plan(),
        goal=default_wealth_goal_2031(),
        conversion=conversion,
        start_snapshot=start_snapshot,
        end_snapshot=end_snapshot,
        contribution_reconciliations=recons,
        contribution_tracking_start=(
            date(as_of.year, 1, 1) if tracking_start is _DEFAULT_TRACKING else tracking_start
        ),
    )


def _snap(
    *,
    snap_id: str,
    captured_at: str,
    value: float,
    coverage: float = 100.0,
    unpriced: int = 0,
    currency: str = "USD",
) -> PortfolioSnapshotView:
    return snapshot_view_from_row(
        {
            "id": snap_id,
            "user_id": "planning",
            "portfolio_id": "planning",
            "captured_at": captured_at,
            "base_currency": currency,
            "priced_market_value": value,
            "total_cost_basis": 0.0,
            "unrealized_pl": 0.0,
            "cash_value": 0.0,
            "invested_value": value,
            "liabilities_total": None,
            "net_wealth_partial": None,
            "priced_position_coverage_pct": coverage,
            "unpriced_position_count": unpriced,
            "mixed_currency_warning": False,
            "valuation_payload": {},
            "created_at": captured_at,
        }
    )


class MonthlyPlanTests(unittest.TestCase):
    def test_applicable_monthly_plan_from_contribution_plan(self) -> None:
        plan = default_contribution_plan()
        view = _intel([])
        expected = monthly_for_year(plan, as_of=AS_OF, year=AS_OF.year)
        self.assertEqual(view.planned_monthly_contribution, expected)
        self.assertEqual(view.planned_monthly_contribution, Decimal("60000.00"))

    def test_annual_step_up_reuses_monthly_for_year(self) -> None:
        plan = default_contribution_plan()
        self.assertEqual(plan.annual_increase_rate, Decimal("0.25"))
        self.assertEqual(
            monthly_for_year(plan, as_of=AS_OF, year=2027),
            Decimal("75000.00"),
        )
        self.assertEqual(
            monthly_for_year(plan, as_of=AS_OF, year=2028),
            Decimal("93750.00"),
        )


class ActualContributionSemanticsTests(unittest.TestCase):
    def test_monthly_actual_deposits(self) -> None:
        view = _intel([_txn(TXN_TYPE_DEPOSIT, 40000)], reconciled=True)
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))
        self.assertEqual(
            view.monthly_evidence_quality, ContributionEvidenceQuality.COMPLETE
        )

    def test_withdrawals_reduce_actual_net_contribution(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 50000),
                _txn(TXN_TYPE_WITHDRAW, 10000, executed_at="2026-08-12T12:00:00+00:00"),
            ],
            reconciled=True,
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))

    def test_buy_excluded(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 40000),
                _txn(TXN_TYPE_BUY, 25000, currency="USD"),
            ],
            reconciled=True,
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))

    def test_sell_excluded(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 40000),
                _txn(TXN_TYPE_SELL, 18000, currency="USD"),
            ],
            reconciled=True,
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))

    def test_transfer_excluded(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 40000),
                _txn(TXN_TYPE_TRANSFER_OUT, 50000),
                _txn(TXN_TYPE_TRANSFER_IN, 50000, account_id="acc-2"),
            ],
            account_ids=["acc-1", "acc-2"],
            reconciled=True,
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))

    def test_dividend_excluded(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 40000),
                _txn(TXN_TYPE_DIVIDEND, 8000),
            ],
            reconciled=True,
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))

    def test_opening_lots_excluded(self) -> None:
        view = _intel([_txn(TXN_TYPE_BUY, 50000, currency="USD")])
        self.assertIsNone(view.actual_monthly_net_contribution)
        self.assertEqual(
            view.monthly_evidence_quality, ContributionEvidenceQuality.PARTIAL
        )

    def test_no_deposit_evidence_is_not_confirmed_zero(self) -> None:
        view = _intel([_txn(TXN_TYPE_BUY, 12000, currency="USD")])
        self.assertIsNone(view.actual_monthly_net_contribution)
        self.assertIsNone(view.monthly_remaining)
        self.assertNotEqual(view.actual_monthly_net_contribution, Decimal("0"))


class EvidenceStateTests(unittest.TestCase):
    def test_evidence_complete(self) -> None:
        view = _intel([_txn(TXN_TYPE_DEPOSIT, 10000)], reconciled=True)
        self.assertEqual(
            view.monthly_evidence_quality, ContributionEvidenceQuality.COMPLETE
        )
        self.assertEqual(view.ytd_evidence_quality, ContributionEvidenceQuality.COMPLETE)
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("10000.00"))

    def test_deposit_without_reconciliation_is_partial(self) -> None:
        view = _intel([_txn(TXN_TYPE_DEPOSIT, 10000)])
        self.assertEqual(
            view.monthly_evidence_quality, ContributionEvidenceQuality.PARTIAL
        )
        self.assertIsNone(view.actual_monthly_net_contribution)
        self.assertIsNone(view.monthly_remaining)

    def test_reconciled_zero_flow_is_complete_zero(self) -> None:
        view = _intel([], reconciled=True)
        self.assertEqual(
            view.monthly_evidence_quality, ContributionEvidenceQuality.COMPLETE
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("0.00"))

    def test_evidence_partial(self) -> None:
        view = _intel([_txn(TXN_TYPE_SELL, 3000, currency="USD")])
        self.assertEqual(
            view.monthly_evidence_quality, ContributionEvidenceQuality.PARTIAL
        )
        self.assertEqual(view.ytd_evidence_quality, ContributionEvidenceQuality.PARTIAL)
        self.assertIsNone(view.actual_monthly_net_contribution)

    def test_evidence_unavailable(self) -> None:
        empty = _intel([], account_ids=[])
        self.assertEqual(
            empty.monthly_evidence_quality, ContributionEvidenceQuality.UNAVAILABLE
        )
        self.assertEqual(
            empty.evidence_quality, ContributionEvidenceQuality.UNAVAILABLE
        )
        self.assertIsNone(empty.actual_monthly_net_contribution)
        none = _intel([])
        self.assertEqual(
            none.monthly_evidence_quality, ContributionEvidenceQuality.UNAVAILABLE
        )
        self.assertIsNone(none.actual_monthly_net_contribution)


class MonthlyActionTests(unittest.TestCase):
    def test_monthly_remaining(self) -> None:
        view = _intel([_txn(TXN_TYPE_DEPOSIT, 40000)], reconciled=True)
        self.assertEqual(view.monthly_remaining, Decimal("20000.00"))
        self.assertEqual(view.monthly_surplus, Decimal("0.00"))
        self.assertEqual(view.monthly_action_status, MonthlyActionStatus.CONTRIBUTION_DUE)
        self.assertIn("20,000.00 TRY", view.monthly_action_summary)

    def test_monthly_surplus(self) -> None:
        view = _intel([_txn(TXN_TYPE_DEPOSIT, 80000)], reconciled=True)
        self.assertEqual(view.monthly_remaining, Decimal("0.00"))
        self.assertEqual(view.monthly_surplus, Decimal("20000.00"))
        self.assertEqual(view.monthly_action_status, MonthlyActionStatus.AHEAD)
        self.assertEqual(view.monthly_action_summary, "Bu ayki katkı planı karşılandı.")

    def test_on_plan_and_incomplete_action_copy(self) -> None:
        on_plan = _intel([_txn(TXN_TYPE_DEPOSIT, 60000)], reconciled=True)
        self.assertEqual(on_plan.monthly_action_status, MonthlyActionStatus.ON_PLAN)
        self.assertEqual(on_plan.monthly_action_summary, "Bu ayki katkı planı karşılandı.")
        incomplete = _intel([_txn(TXN_TYPE_BUY, 1, currency="USD")])
        self.assertEqual(
            incomplete.monthly_action_status, MonthlyActionStatus.EVIDENCE_INCOMPLETE
        )
        self.assertEqual(
            incomplete.monthly_action_summary,
            "Bu ay için güvenilir katkı geçmişi eksik; kalan tutar kesin hesaplanamıyor.",
        )


class YtdTrackingTests(unittest.TestCase):
    def test_ytd_planned_uses_calendar_months(self) -> None:
        view = _intel([])
        self.assertEqual(view.planned_ytd_contribution, Decimal("480000.00"))
        self.assertEqual(view.planned_full_year_contribution, Decimal("720000.00"))
        self.assertNotEqual(
            view.planned_ytd_contribution, view.planned_full_year_contribution
        )

    def test_ytd_actual_amount(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 10000, executed_at="2026-03-01T12:00:00+00:00"),
                _txn(TXN_TYPE_DEPOSIT, 40000),
                _txn(TXN_TYPE_FEE, 50),
            ],
            reconciled=True,
        )
        self.assertEqual(view.actual_ytd_net_contribution, Decimal("50000.00"))
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))

    def test_ytd_completion(self) -> None:
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 240000, executed_at="2026-02-01T12:00:00+00:00")],
            reconciled=True,
        )
        self.assertEqual(view.ytd_remaining, Decimal("240000.00"))
        self.assertEqual(view.ytd_completion_pct, Decimal("50.00"))


class AdequacyAndFxTests(unittest.TestCase):
    def test_base_8pct_required_contribution_comparison(self) -> None:
        conversion = planning_conversion(Decimal("40"))
        current = _usd("10000")
        plan = default_contribution_plan()
        solved = solve_required_starting_monthly(
            as_of_date=AS_OF,
            current=current,
            contribution_currency=plan.currency,
            annual_increase_rate=plan.annual_increase_rate,
            annual_return_rate=Decimal("0.08"),
            conversion=conversion,
        )
        view = build_contribution_intelligence(
            as_of_date=AS_OF,
            current=current,
            transactions=[_txn(TXN_TYPE_DEPOSIT, 60000)],
            account_ids=[ACCOUNT],
            plan=plan,
            conversion=conversion,
        )
        self.assertTrue(solved.available)
        self.assertEqual(
            view.required_starting_monthly_contribution, solved.starting_monthly
        )
        self.assertIsNotNone(view.plan_vs_required_difference)
        self.assertIn(
            view.plan_adequacy_status,
            {
                PlanAdequacyStatus.SUFFICIENT,
                PlanAdequacyStatus.BELOW_REQUIRED,
                PlanAdequacyStatus.ABOVE_REQUIRED,
            },
        )

    def test_missing_usdtry_is_indeterminate(self) -> None:
        view = _intel([_txn(TXN_TYPE_DEPOSIT, 60000)], current=_usd("10000"))
        self.assertIsNone(view.required_starting_monthly_contribution)
        self.assertEqual(view.plan_adequacy_status, PlanAdequacyStatus.INDETERMINATE)
        self.assertIn("USDTRY", view.adequacy_summary)

    def test_explicit_planning_usdtry_works(self) -> None:
        conversion = planning_conversion(Decimal("40"))
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 60000)],
            current=_usd("10000"),
            conversion=conversion,
        )
        self.assertIsNotNone(view.required_starting_monthly_contribution)
        self.assertNotEqual(view.plan_adequacy_status, PlanAdequacyStatus.INDETERMINATE)

    def test_partial_valuation_is_not_below_required(self) -> None:
        conversion = planning_conversion(Decimal("40"))
        tiny = ContributionPlan(Decimal("1"), "TRY", Decimal("0"))
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 1)],
            current=_usd("100", complete=False, unvalued=("BIMAS", "ASELS", "TUPRS")),
            conversion=conversion,
            plan=tiny,
        )
        self.assertEqual(view.plan_adequacy_status, PlanAdequacyStatus.INDETERMINATE)

    def test_planning_fx_does_not_value_current_bist_assets(self) -> None:
        snapshot = _usd("58642.17", complete=False, unvalued=("BIMAS", "ASELS", "TUPRS"))
        before = snapshot.current_value_lower_bound
        view = build_contribution_intelligence(
            as_of_date=AS_OF,
            current=snapshot,
            transactions=[],
            account_ids=[ACCOUNT],
            conversion=planning_conversion(Decimal("40")),
        )
        self.assertEqual(snapshot.current_value_lower_bound, before)
        self.assertEqual(snapshot.unvalued_symbols, ("BIMAS", "ASELS", "TUPRS"))
        self.assertFalse(snapshot.valuation_complete)
        self.assertNotIn("BIMAS", view.monthly_action_summary)


class PerformancePlanningTests(unittest.TestCase):
    def test_performance_unavailable_without_start_snapshot(self) -> None:
        view = _intel([])
        self.assertEqual(
            view.performance_evidence_quality, PerformanceEvidenceQuality.UNAVAILABLE
        )
        self.assertIsNone(view.investment_return_pct)
        self.assertIsNone(view.investment_gain_loss)
        self.assertFalse(view.planning_benchmark_available)
        self.assertEqual(view.attribution_status, PlanAttributionStatus.EVIDENCE_INCOMPLETE)

    def test_no_fake_zero_return(self) -> None:
        view = _intel([_txn(TXN_TYPE_BUY, 1, currency="USD")])
        self.assertIsNone(view.investment_return_pct)
        self.assertNotEqual(view.investment_return_pct, Decimal("0"))

    def test_performance_partial_unpriced_start(self) -> None:
        start = _snap(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
            coverage=50.0,
            unpriced=3,
        )
        end = _snap(
            snap_id="s2",
            captured_at="2026-08-17T23:59:59+00:00",
            value=11000.0,
        )
        view = _intel(
            [],
            current=_usd("11000"),
            start_snapshot=start,
            end_snapshot=end,
        )
        self.assertEqual(
            view.performance_evidence_quality, PerformanceEvidenceQuality.PARTIAL
        )
        self.assertIsNone(view.investment_return_pct)
        self.assertFalse(view.planning_benchmark_available)

    def test_performance_complete_evidenced_zero_return(self) -> None:
        start = _snap(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
        )
        end = _snap(
            snap_id="s2",
            captured_at="2026-08-17T23:59:59+00:00",
            value=10000.0,
        )
        plan = ContributionPlan(Decimal("0"), "USD", Decimal("0"))
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 0, currency="USD")],
            current=_usd("10000"),
            plan=plan,
            start_snapshot=start,
            end_snapshot=end,
        )
        self.assertEqual(
            view.performance_evidence_quality, PerformanceEvidenceQuality.COMPLETE
        )
        self.assertEqual(view.investment_return_pct, Decimal("0.00"))
        self.assertEqual(view.investment_gain_loss, Decimal("0.00"))

    def test_contribution_gap_without_claiming_performance(self) -> None:
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 10000)],
            current=_usd("10000"),
            reconciled=True,
        )
        self.assertEqual(
            view.ytd_evidence_quality, ContributionEvidenceQuality.COMPLETE
        )
        self.assertEqual(
            view.performance_evidence_quality, PerformanceEvidenceQuality.UNAVAILABLE
        )
        self.assertEqual(view.attribution_status, PlanAttributionStatus.CONTRIBUTION_GAP)

    def test_contribution_surplus_is_ahead_without_performance(self) -> None:
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 900000, executed_at="2026-02-01T12:00:00+00:00")],
            current=_usd("10000"),
            reconciled=True,
        )
        self.assertEqual(view.attribution_status, PlanAttributionStatus.AHEAD)

    def test_performance_gap_only(self) -> None:
        start = _snap(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
        )
        end = _snap(
            snap_id="s2",
            captured_at="2026-08-17T23:59:59+00:00",
            value=10000.0,
        )
        plan = ContributionPlan(Decimal("0"), "USD", Decimal("0"))
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 0, currency="USD")],
            current=_usd("10000"),
            plan=plan,
            start_snapshot=start,
            end_snapshot=end,
            reconciled=True,
        )
        self.assertTrue(view.planning_benchmark_available)
        self.assertEqual(view.attribution_status, PlanAttributionStatus.PERFORMANCE_GAP)

    def test_both_gaps(self) -> None:
        start = _snap(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
        )
        end = _snap(
            snap_id="s2",
            captured_at="2026-08-17T23:59:59+00:00",
            value=10000.0,
        )
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 10000, currency="USD")],
            current=_usd("10000"),
            plan=ContributionPlan(Decimal("60000"), "USD", Decimal("0")),
            start_snapshot=start,
            end_snapshot=end,
            reconciled=True,
        )
        self.assertEqual(view.attribution_status, PlanAttributionStatus.BOTH)

    def test_on_track(self) -> None:
        start = _snap(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
        )
        probe = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 0, currency="USD")],
            current=_usd("10000"),
            plan=ContributionPlan(Decimal("0"), "USD", Decimal("0")),
            start_snapshot=start,
            end_snapshot=_snap(
                snap_id="probe",
                captured_at="2026-08-17T23:59:59+00:00",
                value=10000.0,
            ),
            reconciled=True,
        )
        self.assertIsNotNone(probe.planning_path_value)
        path = float(probe.planning_path_value)
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 0, currency="USD")],
            current=_usd(str(path)),
            plan=ContributionPlan(Decimal("0"), "USD", Decimal("0")),
            start_snapshot=start,
            end_snapshot=_snap(
                snap_id="s2",
                captured_at="2026-08-17T23:59:59+00:00",
                value=path,
            ),
            reconciled=True,
        )
        self.assertEqual(view.attribution_status, PlanAttributionStatus.ON_TRACK)

    def test_ahead_with_performance(self) -> None:
        start = _snap(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
        )
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 0, currency="USD")],
            current=_usd("20000"),
            plan=ContributionPlan(Decimal("0"), "USD", Decimal("0")),
            start_snapshot=start,
            end_snapshot=_snap(
                snap_id="s2",
                captured_at="2026-08-17T23:59:59+00:00",
                value=20000.0,
            ),
            reconciled=True,
        )
        self.assertEqual(view.attribution_status, PlanAttributionStatus.AHEAD)

    def test_missing_fx_with_complete_contribution_is_plan_indeterminate(self) -> None:
        view = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 480000, executed_at="2026-02-01T12:00:00+00:00")],
            current=_usd("10000"),
            reconciled=True,
        )
        self.assertEqual(view.ytd_evidence_quality, ContributionEvidenceQuality.COMPLETE)
        self.assertEqual(view.ytd_remaining, Decimal("0.00"))
        self.assertEqual(
            view.attribution_status, PlanAttributionStatus.PLAN_INDETERMINATE
        )

    def test_partial_bist_is_not_a_negative_diagnosis(self) -> None:
        view = _intel(
            [_txn(TXN_TYPE_BUY, 1, currency="USD")],
            current=_usd("10000", complete=False, unvalued=("BIMAS", "ASELS", "TUPRS")),
        )
        self.assertEqual(view.attribution_status, PlanAttributionStatus.EVIDENCE_INCOMPLETE)
        self.assertNotEqual(view.attribution_status, PlanAttributionStatus.CONTRIBUTION_GAP)
        self.assertNotEqual(view.attribution_status, PlanAttributionStatus.PERFORMANCE_GAP)

    def test_mid_year_snapshot_is_not_year_start(self) -> None:
        march = _snap(
            snap_id="s-mar",
            captured_at="2026-03-15T00:00:00+00:00",
            value=10000.0,
        )
        chosen = select_period_start_snapshot([march], as_of=AS_OF)
        self.assertIsNone(chosen)

    def test_ui_plan_and_performance_section(self) -> None:
        ui = Path("components/wealth_goal_center_ui.py").read_text(encoding="utf-8")
        self.assertIn('render_section_title("Plan ve Performans")', ui)
        self.assertIn("PERFORMANCE_UNAVAILABLE_COPY", ui)
        self.assertIn("planning_benchmark_label", ui)
        self.assertNotIn("geride", ui.lower())


class SafetyAndUiTests(unittest.TestCase):
    def test_no_provider_calls(self) -> None:
        for path in CHANGED:
            source = path.read_text(encoding="utf-8").lower()
            for token in PROVIDER_TOKENS:
                with self.subTest(path=str(path), token=token):
                    self.assertNotIn(token.lower(), source)

    def test_no_ledger_writes(self) -> None:
        for path in CHANGED:
            source = path.read_text(encoding="utf-8")
            for token in WRITE_TOKENS:
                with self.subTest(path=str(path), token=token):
                    self.assertNotIn(token, source)

    def test_ui_this_month_section_reuses_session_fx(self) -> None:
        ui = Path("components/wealth_goal_center_ui.py").read_text(encoding="utf-8")
        self.assertIn('render_section_title("Bu Ay")', ui)
        self.assertIn("build_contribution_intelligence", ui)
        self.assertIn("Kur varsayımlarını kaydet", ui)
        self.assertIn("Planlama Kur Varsayımları", ui)
        self.assertNotIn("wealth_os_2031_usdtry", ui)
        self.assertIn("st.caption(USER_ASSUMPTION_NOTE)", ui)
        self.assertIn("CONTRIBUTION_HISTORY_PARTIAL_COPY", ui)
        self.assertIn("CONTRIBUTION_HISTORY_UNAVAILABLE_COPY", ui)
        self.assertIn("format_contribution_actual_label", ui)
        self.assertIn("render_contribution_reconciliation_action", ui)
        self.assertIn("CONTRIBUTION_TRACKING_UNCONFIGURED_COPY", ui)
        self.assertIn("CONTRIBUTION_TRACKING_NOT_TRACKED_COPY", ui)
        self.assertIn("record_tracked_external_cash_flow", ui)
        self.assertIn("Para Girişi", ui)
        self.assertNotIn("60000", ui)
        self.assertIn("Plan ve Performans", ui)


if __name__ == "__main__":
    unittest.main()
