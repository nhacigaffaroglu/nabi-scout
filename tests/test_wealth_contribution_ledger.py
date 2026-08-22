from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from services.wealth_contract import (
    TXN_TYPE_BUY,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_FEE,
    TXN_TYPE_SELL,
    TXN_TYPE_WITHDRAW,
    WealthValidationError,
)
from services.wealth_contribution_intelligence import (
    ContributionEvidenceQuality,
    build_contribution_intelligence,
)
from services.wealth_external_cash_flow import (
    ContributionReconciliation,
    contribution_delta_for_transaction,
    contribution_period_evidence,
    mark_contribution_reconciled,
    net_external_contribution,
    normalize_external_flow_type,
    record_external_cash_flow,
)
from services.wealth_goal_models import ContributionPlan, default_contribution_plan
from services.wealth_performance_engine import collect_timed_external_flows
from tests.test_wealth_contribution_intelligence import ACCOUNT, AS_OF, _intel, _recon, _txn, _usd


LEDGER = Path("services/wealth_external_cash_flow.py")
ENGINE = Path("services/wealth_contribution_intelligence.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "openai",
    "SECFinancialClient",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)
BACKFILL_TOKENS = (
    "cost_basis",
    "opening lot",
    "infer deposit",
    "BUY cost",
)


def _window():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 17, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def _wealth(*, portfolio_id="pf-1", account_portfolio="pf-1"):
    wealth = MagicMock()
    wealth.user_id = "user-1"
    wealth.accounts.get_by_id.return_value = {"id": "acc-1", "portfolio_id": account_portfolio}
    wealth.portfolios.list_for_user.return_value = [{"id": portfolio_id}]
    wealth.ensure_cash_asset.return_value = {"id": "cash-try"}
    wealth.post_transaction.return_value = {
        "id": "txn-1",
        "txn_type": TXN_TYPE_DEPOSIT,
        "amount": 60000,
        "currency": "TRY",
    }
    return wealth


class EntryValidationTests(unittest.TestCase):
    def test_deposit_accepted(self) -> None:
        wealth = _wealth()
        row = record_external_cash_flow(
            wealth,
            portfolio_id="pf-1",
            account_id="acc-1",
            flow_type="DEPOSIT",
            amount=60000,
            currency="TRY",
            notes="August",
        )
        self.assertEqual(row["id"], "txn-1")
        kwargs = wealth.post_transaction.call_args.kwargs
        self.assertEqual(kwargs["txn_type"], TXN_TYPE_DEPOSIT)
        self.assertEqual(kwargs["amount"], 60000.0)
        self.assertEqual(kwargs["quantity"], 0)
        self.assertEqual(kwargs["currency"], "TRY")
        self.assertEqual(kwargs["asset_id"], "cash-try")

    def test_withdrawal_accepted(self) -> None:
        wealth = _wealth()
        record_external_cash_flow(
            wealth,
            portfolio_id="pf-1",
            account_id="acc-1",
            flow_type="WITHDRAWAL",
            amount="10000.50",
            currency="try",
        )
        self.assertEqual(wealth.post_transaction.call_args.kwargs["txn_type"], TXN_TYPE_WITHDRAW)
        self.assertEqual(wealth.post_transaction.call_args.kwargs["amount"], 10000.5)

    def test_zero_and_negative_rejected(self) -> None:
        wealth = _wealth()
        with self.assertRaises(WealthValidationError):
            record_external_cash_flow(
                wealth, portfolio_id="pf-1", account_id="acc-1", flow_type="DEPOSIT", amount=0, currency="TRY"
            )
        with self.assertRaises(WealthValidationError):
            record_external_cash_flow(
                wealth, portfolio_id="pf-1", account_id="acc-1", flow_type="DEPOSIT", amount=-1, currency="TRY"
            )

    def test_buy_and_sell_rejected_by_entry_service(self) -> None:
        wealth = _wealth()
        with self.assertRaises(WealthValidationError):
            record_external_cash_flow(
                wealth, portfolio_id="pf-1", account_id="acc-1", flow_type="BUY", amount=10, currency="TRY"
            )
        with self.assertRaises(WealthValidationError):
            normalize_external_flow_type("SELL")

    def test_ownership_and_account_portfolio_mismatch(self) -> None:
        missing_account = _wealth()
        missing_account.accounts.get_by_id.return_value = None
        with self.assertRaises(WealthValidationError):
            record_external_cash_flow(
                missing_account, portfolio_id="pf-1", account_id="acc-1", flow_type="DEPOSIT", amount=1, currency="TRY"
            )
        mismatch = _wealth(account_portfolio="other")
        with self.assertRaises(WealthValidationError):
            record_external_cash_flow(
                mismatch, portfolio_id="pf-1", account_id="acc-1", flow_type="DEPOSIT", amount=1, currency="TRY"
            )
        missing_pf = _wealth()
        missing_pf.portfolios.list_for_user.return_value = []
        with self.assertRaises(WealthValidationError):
            record_external_cash_flow(
                missing_pf, portfolio_id="pf-1", account_id="acc-1", flow_type="DEPOSIT", amount=1, currency="TRY"
            )

    def test_repeated_deposits_are_both_posted(self) -> None:
        wealth = _wealth()
        wealth.post_transaction.side_effect = [{"id": "a"}, {"id": "b"}]
        first = record_external_cash_flow(
            wealth, portfolio_id="pf-1", account_id="acc-1", flow_type="DEPOSIT", amount=60000, currency="TRY"
        )
        second = record_external_cash_flow(
            wealth, portfolio_id="pf-1", account_id="acc-1", flow_type="DEPOSIT", amount=60000, currency="TRY"
        )
        self.assertEqual(first["id"], "a")
        self.assertEqual(second["id"], "b")
        self.assertEqual(wealth.post_transaction.call_count, 2)


class CashFlowSemanticsTests(unittest.TestCase):
    def test_deposit_positive_withdrawal_reduces_net(self) -> None:
        start, end = _window()
        deposits, withdrawals, net = net_external_contribution(
            [
                _txn(TXN_TYPE_DEPOSIT, 50000),
                _txn(TXN_TYPE_WITHDRAW, 10000, executed_at="2026-08-12T12:00:00+00:00"),
            ],
            account_ids={ACCOUNT},
            currency="TRY",
            period_start=start,
            period_end=end,
        )
        self.assertEqual(deposits, Decimal("50000"))
        self.assertEqual(withdrawals, Decimal("10000"))
        self.assertEqual(net, Decimal("40000"))

    def test_investment_and_income_contribute_zero(self) -> None:
        for txn_type, amount in (
            (TXN_TYPE_BUY, 25000),
            (TXN_TYPE_SELL, 18000),
            (TXN_TYPE_DIVIDEND, 8000),
            (TXN_TYPE_FEE, 50),
        ):
            delta = contribution_delta_for_transaction(
                _txn(txn_type, amount, currency="TRY"),
                plan_currency="TRY",
            )
            with self.subTest(txn_type=txn_type):
                self.assertEqual(delta, Decimal("0"))
        self.assertEqual(
            contribution_delta_for_transaction(_txn(TXN_TYPE_DEPOSIT, 100), plan_currency="TRY"),
            Decimal("100"),
        )
        self.assertEqual(
            contribution_delta_for_transaction(_txn(TXN_TYPE_WITHDRAW, 40), plan_currency="TRY"),
            Decimal("-40"),
        )

    def test_try_and_usd_never_summed_and_no_fx(self) -> None:
        start, end = _window()
        _deposits, _withdrawals, net = net_external_contribution(
            [
                _txn(TXN_TYPE_DEPOSIT, 60000, currency="TRY"),
                _txn(TXN_TYPE_DEPOSIT, 1000, currency="USD"),
            ],
            account_ids={ACCOUNT},
            currency="TRY",
            period_start=start,
            period_end=end,
        )
        self.assertEqual(net, Decimal("60000"))
        self.assertNotIn("fx", LEDGER.read_text(encoding="utf-8").lower())

    def test_stored_sign_patterns_do_not_double_negative(self) -> None:
        start, end = _window()
        _d, _w, net = net_external_contribution(
            [
                _txn(TXN_TYPE_DEPOSIT, 100, executed_at="2026-08-10T12:00:00+00:00"),
                _txn(TXN_TYPE_WITHDRAW, 30, executed_at="2026-08-11T12:00:00+00:00"),
            ],
            account_ids={ACCOUNT},
            currency="TRY",
            period_start=start,
            period_end=end,
        )
        self.assertEqual(net, Decimal("70"))

    def test_modified_dietz_adapter_receives_only_external_flows(self) -> None:
        start, end = _window()
        flows = collect_timed_external_flows(
            [
                _txn(TXN_TYPE_DEPOSIT, 50),
                _txn(TXN_TYPE_BUY, 50, currency="TRY"),
                _txn(TXN_TYPE_WITHDRAW, 10, executed_at="2026-08-12T12:00:00+00:00"),
            ],
            account_ids={ACCOUNT},
            base_currency="TRY",
            period_start=start,
            period_end=end,
        )
        signed = [row.signed_amount for row in flows]
        self.assertEqual(signed, [50.0, -10.0])


class EvidenceAndPlanTests(unittest.TestCase):
    def test_partial_without_reconciliation(self) -> None:
        start, end = _window()
        quality = contribution_period_evidence(
            [_txn(TXN_TYPE_DEPOSIT, 10000)],
            account_ids={ACCOUNT},
            plan_currency="TRY",
            start=start,
            end=end,
        )
        self.assertEqual(quality, "PARTIAL")
        view = _intel([_txn(TXN_TYPE_DEPOSIT, 10000)])
        self.assertEqual(view.monthly_evidence_quality, ContributionEvidenceQuality.PARTIAL)
        self.assertIsNone(view.actual_monthly_net_contribution)

    def test_reconciled_zero_and_numeric(self) -> None:
        zero = _intel([], reconciled=True)
        self.assertEqual(zero.monthly_evidence_quality, ContributionEvidenceQuality.COMPLETE)
        self.assertEqual(zero.actual_monthly_net_contribution, Decimal("0.00"))
        funded = _intel([_txn(TXN_TYPE_DEPOSIT, 40000)], reconciled=True)
        self.assertEqual(funded.actual_monthly_net_contribution, Decimal("40000.00"))
        self.assertEqual(funded.actual_ytd_net_contribution, Decimal("40000.00"))

    def test_monthly_and_ytd_windows(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 10000, executed_at="2026-03-01T12:00:00+00:00"),
                _txn(TXN_TYPE_DEPOSIT, 40000),
            ],
            reconciled=True,
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("40000.00"))
        self.assertEqual(view.actual_ytd_net_contribution, Decimal("50000.00"))
        self.assertEqual(view.planned_monthly_contribution, default_contribution_plan().starting_monthly)

    def test_contribution_plan_reused_not_hardcoded(self) -> None:
        plan = ContributionPlan(Decimal("12345"), "TRY", Decimal("0.1"))
        view = build_contribution_intelligence(
            as_of_date=AS_OF,
            current=_usd("10000", complete=False, unvalued=("BIMAS",)),
            transactions=[],
            account_ids=[ACCOUNT],
            plan=plan,
            contribution_reconciliations=_recon(),
        )
        self.assertEqual(view.planned_monthly_contribution, Decimal("12345.00"))
        self.assertNotIn("60000", LEDGER.read_text(encoding="utf-8"))

    def test_reconciliation_is_not_implied_by_deposit(self) -> None:
        repo = MagicMock()
        mark_contribution_reconciled(
            repo,
            user_id="user-1",
            portfolio_id="pf-1",
            reconciled_through=AS_OF,
            tracking_start=date(2026, 1, 1),
        )
        repo.upsert.assert_called_once()
        source = LEDGER.read_text(encoding="utf-8")
        self.assertNotIn("mark_contribution_reconciled", ENGINE.read_text(encoding="utf-8"))
        self.assertIn("USER_DEFINED", source)

    def test_no_provider_backfill_or_write_tokens_in_read_helpers(self) -> None:
        source = LEDGER.read_text(encoding="utf-8")
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token, source)
        for token in BACKFILL_TOKENS:
            self.assertNotIn(token, source)
        self.assertNotIn(".delete(", source)


if __name__ == "__main__":
    unittest.main()
