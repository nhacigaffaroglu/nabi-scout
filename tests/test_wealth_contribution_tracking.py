from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from components.wealth_goal_center_ui import (
    format_contribution_actual_label,
    format_contribution_remaining_label,
)
from services.wealth_contract import TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW, WealthValidationError
from services.wealth_contribution_intelligence import (
    CONTRIBUTION_TRACKING_NOT_TRACKED_COPY,
    CONTRIBUTION_TRACKING_UNCONFIGURED_COPY,
    ContributionEvidenceQuality,
)
from services.wealth_external_cash_flow import (
    CONTRIBUTION_ENTRY_BEFORE_START_COPY,
    CONTRIBUTION_RECON_BEFORE_START_COPY,
    CONTRIBUTION_TRACKING_LOCKED_COPY,
    ContributionTrackingScope,
    mark_contribution_reconciled,
    record_external_cash_flow,
    record_tracked_external_cash_flow,
    set_contribution_tracking_start,
)
from services.wealth_goal_models import ContributionPlan
from services.wealth_performance_engine import collect_timed_external_flows
from services.portfolio_decision_intelligence import build_portfolio_decision
from tests.test_portfolio_decision_intelligence import _complete_usd_view
from tests.test_wealth_contribution_intelligence import ACCOUNT, AS_OF, _intel, _txn


UI = Path("components/wealth_goal_center_ui.py")
LEDGER = Path("services/wealth_external_cash_flow.py")
DIETZ = Path("services/wealth_performance_engine.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "openai",
    "SECFinancialClient",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)
START = date(2026, 8, 1)
MID = date(2026, 8, 18)


def _wealth():
    wealth = MagicMock()
    wealth.user_id = "user-1"
    wealth.accounts.get_by_id.return_value = {"id": "acc-1", "portfolio_id": "pf-1"}
    wealth.portfolios.list_for_user.return_value = [
        {"id": "pf-1", "contribution_tracking_start_date": START.isoformat()}
    ]
    wealth.ensure_cash_asset.return_value = {"id": "cash-try"}
    wealth.post_transaction.return_value = {
        "id": "txn-99",
        "txn_type": TXN_TYPE_DEPOSIT,
        "amount": 40000,
        "currency": "TRY",
    }
    return wealth


class TrackingBoundaryTests(TestCase):
    def test_unconfigured_has_no_authoritative_actual(self) -> None:
        view = _intel([], tracking_start=None)
        self.assertEqual(view.monthly_tracking_scope, ContributionTrackingScope.UNCONFIGURED)
        self.assertIsNone(view.actual_monthly_net_contribution)
        self.assertIsNone(view.monthly_remaining)
        self.assertEqual(view.planned_ytd_contribution, Decimal("0.00"))
        label = format_contribution_actual_label(
            view.monthly_evidence_quality,
            view.actual_monthly_net_contribution,
            view.currency,
            scope=view.monthly_tracking_scope,
        )
        self.assertEqual(label, CONTRIBUTION_TRACKING_UNCONFIGURED_COPY)
        self.assertNotIn("0.00 TRY", label)
        remaining = format_contribution_remaining_label(
            view.monthly_evidence_quality,
            view.monthly_remaining,
            view.currency,
            scope=view.monthly_tracking_scope,
        )
        self.assertEqual(remaining, "—")

    def test_period_before_tracking_start_is_not_zero(self) -> None:
        view = _intel([], as_of=date(2026, 7, 31), tracking_start=START, reconciled=True)
        self.assertEqual(view.monthly_tracking_scope, ContributionTrackingScope.NOT_TRACKED)
        self.assertIsNone(view.actual_monthly_net_contribution)
        self.assertIsNone(view.monthly_remaining)
        self.assertEqual(view.planned_ytd_contribution, Decimal("0.00"))
        label = format_contribution_actual_label(
            view.monthly_evidence_quality,
            view.actual_monthly_net_contribution,
            view.currency,
            scope=view.monthly_tracking_scope,
        )
        self.assertEqual(label, CONTRIBUTION_TRACKING_NOT_TRACKED_COPY)
        self.assertNotIn("0.00", label)

    def test_crossing_period_starts_at_tracking_boundary(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 10000, executed_at="2026-08-10T12:00:00+00:00"),
                _txn(TXN_TYPE_DEPOSIT, 40000, executed_at="2026-08-20T12:00:00+00:00"),
            ],
            as_of=date(2026, 8, 31),
            tracking_start=MID,
            reconciled=True,
        )
        self.assertEqual(view.monthly_tracking_scope, ContributionTrackingScope.TRACKED)
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))
        self.assertIsNotNone(view.monthly_tracking_note)
        self.assertEqual(view.planned_monthly_contribution, Decimal("60000.00"))
        self.assertEqual(view.monthly_evidence_quality, ContributionEvidenceQuality.COMPLETE)

    def test_same_month_pre_start_buy_is_outside_tracked_window(self) -> None:
        complete = _intel(
            [_txn("buy", 50000, currency="USD", executed_at="2026-08-10T12:00:00+00:00")],
            as_of=date(2026, 8, 31),
            tracking_start=MID,
            reconciled=True,
        )
        self.assertEqual(complete.actual_monthly_net_contribution, Decimal("0.00"))
        unrecon = _intel(
            [_txn("buy", 50000, currency="USD", executed_at="2026-08-10T12:00:00+00:00")],
            as_of=date(2026, 8, 31),
            tracking_start=MID,
        )
        self.assertEqual(unrecon.monthly_evidence_quality, ContributionEvidenceQuality.UNAVAILABLE)
        self.assertIsNone(unrecon.actual_monthly_net_contribution)

    def test_period_after_start_uses_normal_recon_semantics(self) -> None:
        tracked = _intel(
            [_txn(TXN_TYPE_DEPOSIT, 40000, executed_at="2026-09-10T12:00:00+00:00")],
            as_of=date(2026, 9, 15),
            tracking_start=START,
        )
        self.assertEqual(tracked.monthly_evidence_quality, ContributionEvidenceQuality.PARTIAL)
        self.assertIsNone(tracked.actual_monthly_net_contribution)
        zero = _intel([], as_of=date(2026, 9, 15), tracking_start=START, reconciled=True)
        self.assertEqual(zero.actual_monthly_net_contribution, Decimal("0.00"))
        self.assertEqual(
            format_contribution_actual_label(
                zero.monthly_evidence_quality,
                zero.actual_monthly_net_contribution,
                zero.currency,
                scope=zero.monthly_tracking_scope,
            ),
            "0.00 TRY",
        )

    def test_ytd_starts_at_tracking_boundary(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 10000, executed_at="2026-03-01T12:00:00+00:00"),
                _txn(TXN_TYPE_DEPOSIT, 40000, executed_at="2026-08-10T12:00:00+00:00"),
            ],
            as_of=date(2026, 10, 15),
            tracking_start=START,
            reconciled=True,
        )
        self.assertEqual(view.actual_ytd_net_contribution, Decimal("40000.00"))
        self.assertEqual(view.planned_ytd_contribution, Decimal("180000.00"))
        self.assertEqual(view.ytd_remaining, Decimal("140000.00"))

    def test_no_pre_boundary_shortfall(self) -> None:
        view = _intel([], as_of=date(2026, 8, 17), tracking_start=START, reconciled=True)
        self.assertEqual(view.planned_ytd_contribution, Decimal("60000.00"))
        self.assertNotEqual(view.planned_ytd_contribution, Decimal("480000.00"))
        self.assertEqual(view.ytd_remaining, Decimal("60000.00"))


class TrackedEntryTests(TestCase):
    def test_deposit_and_withdraw_after_start(self) -> None:
        wealth = _wealth()
        deposit = record_tracked_external_cash_flow(
            wealth,
            portfolio_id="pf-1",
            account_id="acc-1",
            flow_type="DEPOSIT",
            amount=40000,
            currency="TRY",
            occurred_at="2026-08-20T12:00:00+00:00",
            tracking_start=START,
        )
        self.assertEqual(deposit["id"], "txn-99")
        kwargs = wealth.post_transaction.call_args.kwargs
        self.assertEqual(kwargs["txn_type"], TXN_TYPE_DEPOSIT)
        self.assertEqual(kwargs["amount"], 40000.0)
        self.assertEqual(kwargs["quantity"], 0)
        record_tracked_external_cash_flow(
            wealth,
            portfolio_id="pf-1",
            account_id="acc-1",
            flow_type="WITHDRAWAL",
            amount="15000",
            currency="TRY",
            occurred_at="2026-08-21T12:00:00+00:00",
            tracking_start=START,
        )
        self.assertEqual(wealth.post_transaction.call_args.kwargs["txn_type"], TXN_TYPE_WITHDRAW)
        self.assertEqual(wealth.post_transaction.call_args.kwargs["amount"], 15000.0)

    def test_entry_before_start_rejected(self) -> None:
        wealth = _wealth()
        with self.assertRaises(WealthValidationError) as ctx:
            record_tracked_external_cash_flow(
                wealth,
                portfolio_id="pf-1",
                account_id="acc-1",
                flow_type="DEPOSIT",
                amount=40000,
                currency="TRY",
                occurred_at="2026-07-31T12:00:00+00:00",
                tracking_start=START,
            )
        self.assertIn("başlangıcından önce", str(ctx.exception))
        wealth.post_transaction.assert_not_called()

    def test_unconfigured_entry_rejected(self) -> None:
        with self.assertRaises(WealthValidationError):
            record_tracked_external_cash_flow(
                _wealth(),
                portfolio_id="pf-1",
                account_id="acc-1",
                flow_type="DEPOSIT",
                amount=1,
                currency="TRY",
                occurred_at="2026-08-20T12:00:00+00:00",
                tracking_start=None,
            )

    def test_deposit_does_not_auto_reconcile(self) -> None:
        from inspect import getsource

        self.assertNotIn("mark_contribution_reconciled", getsource(record_tracked_external_cash_flow))
        self.assertNotIn("mark_contribution_reconciled", getsource(record_external_cash_flow))


class ReconciliationGuardTests(TestCase):
    def test_recon_requires_tracking_start(self) -> None:
        repo = MagicMock()
        with self.assertRaises(WealthValidationError) as ctx:
            mark_contribution_reconciled(
                repo, user_id="u", portfolio_id="pf-1", reconciled_through=AS_OF
            )
        self.assertIn("henüz belirlenmedi", str(ctx.exception))
        repo.upsert.assert_not_called()

    def test_recon_before_tracking_start_rejected(self) -> None:
        repo = MagicMock()
        with self.assertRaises(WealthValidationError):
            mark_contribution_reconciled(
                repo,
                user_id="u",
                portfolio_id="pf-1",
                reconciled_through=date(2026, 7, 1),
                tracking_start=START,
            )
        repo.upsert.assert_not_called()
        self.assertIn("önce", CONTRIBUTION_RECON_BEFORE_START_COPY)

    def test_tracking_start_locks_after_recon(self) -> None:
        from services.wealth_external_cash_flow import ContributionReconciliation

        wealth = _wealth()
        with self.assertRaises(WealthValidationError) as locked:
            set_contribution_tracking_start(
                wealth,
                portfolio_id="pf-1",
                tracking_start=date(2026, 9, 1),
                reconciliations=(
                    ContributionReconciliation(portfolio_id="pf-1", reconciled_through=AS_OF),
                ),
            )
        self.assertEqual(str(locked.exception), CONTRIBUTION_TRACKING_LOCKED_COPY)
        wealth.portfolios.set_contribution_tracking_start_date.assert_not_called()

    def test_first_tracking_start_is_allowed(self) -> None:
        wealth = _wealth()
        wealth.portfolios.list_for_user.return_value = [{"id": "pf-1"}]
        wealth.portfolios.set_contribution_tracking_start_date.return_value = {
            "id": "pf-1",
            "contribution_tracking_start_date": START.isoformat(),
        }
        row = set_contribution_tracking_start(
            wealth, portfolio_id="pf-1", tracking_start=START
        )
        self.assertEqual(row["contribution_tracking_start_date"], START.isoformat())
        wealth.portfolios.set_contribution_tracking_start_date.assert_called_once()


class NetAndCurrencyTests(TestCase):
    def test_net_and_foreign_currency(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 50000, executed_at="2026-08-20T12:00:00+00:00"),
                _txn(TXN_TYPE_WITHDRAW, 10000, executed_at="2026-08-21T12:00:00+00:00"),
                _txn(TXN_TYPE_DEPOSIT, 1000, currency="USD", executed_at="2026-08-22T12:00:00+00:00"),
            ],
            as_of=date(2026, 8, 31),
            tracking_start=START,
            reconciled=True,
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))

    def test_historical_buy_excluded(self) -> None:
        view = _intel(
            [_txn("buy", 50000, currency="USD")],
            tracking_start=START,
            reconciled=True,
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("0.00"))


class DecisionAndDietzTests(TestCase):
    def test_unconfigured_has_no_shortfall_from_actuals(self) -> None:
        view = build_portfolio_decision(
            _complete_usd_view(),
            as_of_date=AS_OF,
            transactions=[_txn("buy", 1, currency="USD")],
            account_ids=[ACCOUNT],
            plan=ContributionPlan(Decimal("20000"), "USD", Decimal("0")),
            contribution_tracking_start=None,
        )
        action = next(row for row in view.actions if row.id == "contribution_evidence_incomplete")
        self.assertIsNone(action.context["actual_monthly_net_contribution"])
        self.assertEqual(action.context["tracking_scope"], "UNCONFIGURED")
        self.assertNotIn("contribution_plan_below_required", [row.id for row in view.actions])

    def test_pre_start_period_has_no_shortfall_action(self) -> None:
        view = build_portfolio_decision(
            _complete_usd_view(),
            as_of_date=date(2026, 7, 31),
            transactions=[_txn("buy", 1, currency="USD")],
            account_ids=[ACCOUNT],
            plan=ContributionPlan(Decimal("20000"), "USD", Decimal("0")),
            contribution_tracking_start=START,
        )
        self.assertNotIn("contribution_evidence_incomplete", [row.id for row in view.actions])
        self.assertNotIn("contribution_plan_below_required", [row.id for row in view.actions])

    def test_dietz_unchanged_and_no_backfill(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 8, 17, 23, 59, 59, tzinfo=timezone.utc)
        flows = collect_timed_external_flows(
            [
                _txn(TXN_TYPE_DEPOSIT, 50, executed_at="2026-03-01T12:00:00+00:00"),
                _txn("buy", 50),
            ],
            account_ids={ACCOUNT},
            base_currency="TRY",
            period_start=start,
            period_end=end,
        )
        self.assertEqual([row.signed_amount for row in flows], [50.0])
        self.assertNotIn("wealth_contribution_tracking", DIETZ.read_text(encoding="utf-8"))
        self.assertNotIn("infer deposit", LEDGER.read_text(encoding="utf-8").lower())
        self.assertIn("record_tracked_external_cash_flow", UI.read_text(encoding="utf-8"))
        self.assertIn("Para Girişi", UI.read_text(encoding="utf-8"))
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token.lower(), LEDGER.read_text(encoding="utf-8").lower())
        self.assertIn(CONTRIBUTION_ENTRY_BEFORE_START_COPY, LEDGER.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import unittest

    unittest.main()
