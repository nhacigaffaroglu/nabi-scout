from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import TestCase
from unittest.mock import MagicMock

from components.wealth_goal_center_ui import (
    format_contribution_actual_label,
    format_contribution_remaining_label,
)
from repositories.wealth_contribution_reconciliation_repository import (
    WealthContributionReconciliationRepository,
)
from services.wealth_contribution_intelligence import (
    CONTRIBUTION_HISTORY_PARTIAL_COPY,
    CONTRIBUTION_HISTORY_UNAVAILABLE_COPY,
    ContributionEvidenceQuality,
)
from services.wealth_contract import TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW
from services.wealth_external_cash_flow import (
    load_contribution_reconciliations,
    mark_contribution_reconciled,
    record_external_cash_flow,
)
from services.wealth_performance_engine import collect_timed_external_flows
from tests.test_wealth_contribution_intelligence import ACCOUNT, AS_OF, _intel, _txn


REPO = Path("repositories/wealth_contribution_reconciliation_repository.py")
UI = Path("components/wealth_goal_center_ui.py")
DECISION_UI = Path("components/portfolio_decision_center_ui.py")
HISTORY_PAGE = Path("pages/10_Wealth.py")
DIETZ = Path("services/wealth_performance_engine.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "openai",
    "SECFinancialClient",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)


class _Result:
    def __init__(self, data: Optional[List[Dict[str, Any]]]) -> None:
        self.data = data


class FakeReconClient:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.write_log: List[str] = []

    def table(self, name: str) -> "FakeReconQuery":
        if name != WealthContributionReconciliationRepository.TABLE:
            raise RuntimeError(f"unexpected table {name}")
        return FakeReconQuery(self)


class FakeReconQuery:
    def __init__(self, store: FakeReconClient) -> None:
        self.store = store
        self.filters: Dict[str, Any] = {}
        self.op = "select"
        self.payload: Optional[Dict[str, Any]] = None

    def select(self, *_a, **_k) -> "FakeReconQuery":
        self.op = "select"
        return self

    def eq(self, key: str, value: Any) -> "FakeReconQuery":
        self.filters[key] = value
        return self

    def limit(self, *_a, **_k) -> "FakeReconQuery":
        return self

    def insert(self, payload: Dict[str, Any]) -> "FakeReconQuery":
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload: Dict[str, Any]) -> "FakeReconQuery":
        self.op = "update"
        self.payload = payload
        return self

    def execute(self) -> _Result:
        matched = [
            row
            for row in self.store.rows
            if all(str(row.get(key)) == str(value) for key, value in self.filters.items())
        ]
        if self.op == "select":
            return _Result(matched[:1])
        if self.op == "insert":
            row = dict(self.payload or {})
            row.setdefault("id", f"recon-{len(self.store.rows) + 1}")
            self.store.rows.append(row)
            self.store.write_log.append("insert")
            return _Result([row])
        updated = []
        for row in self.store.rows:
            if all(str(row.get(key)) == str(value) for key, value in self.filters.items()):
                row.update(self.payload or {})
                updated.append(row)
        self.store.write_log.append("update")
        return _Result(updated)


class RepositoryWatermarkTests(TestCase):
    def test_missing_row_returns_none(self) -> None:
        repo = WealthContributionReconciliationRepository(FakeReconClient())
        self.assertIsNone(repo.get_for_portfolio("user-1", "pf-1"))
        self.assertEqual(load_contribution_reconciliations(FakeReconClient(), "user-1", "pf-1"), ())

    def test_upsert_is_idempotent_and_keeps_later_watermark(self) -> None:
        repo = WealthContributionReconciliationRepository(FakeReconClient())
        first = mark_contribution_reconciled(
            repo, user_id="user-1", portfolio_id="pf-1", reconciled_through=date(2026, 8, 18), tracking_start=date(2026, 1, 1)
        )
        second = mark_contribution_reconciled(
            repo, user_id="user-1", portfolio_id="pf-1", reconciled_through=date(2026, 8, 18), tracking_start=date(2026, 1, 1)
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(repo.client.rows), 1)
        earlier = mark_contribution_reconciled(
            repo, user_id="user-1", portfolio_id="pf-1", reconciled_through=date(2026, 1, 1), tracking_start=date(2026, 1, 1)
        )
        self.assertEqual(earlier["reconciled_through"], "2026-08-18")
        later = mark_contribution_reconciled(
            repo,
            user_id="user-1",
            portfolio_id="pf-1",
            reconciled_through=date(2026, 9, 1),
            tracking_start=date(2026, 1, 1),
            notes="September",
        )
        self.assertEqual(later["reconciled_through"], "2026-09-01")
        self.assertEqual(later["notes"], "September")
        self.assertEqual(later["provenance"], "USER_DEFINED")


class EvidenceAndUiTests(TestCase):
    def test_buy_only_without_recon_is_partial_not_zero(self) -> None:
        view = _intel([_txn("buy", 50000, currency="USD")])
        self.assertEqual(view.monthly_evidence_quality, ContributionEvidenceQuality.PARTIAL)
        self.assertIsNone(view.actual_monthly_net_contribution)
        self.assertIsNone(view.monthly_remaining)
        label = format_contribution_actual_label(
            view.monthly_evidence_quality,
            view.actual_monthly_net_contribution,
            view.currency,
        )
        remaining = format_contribution_remaining_label(
            view.monthly_evidence_quality, view.monthly_remaining, view.currency
        )
        self.assertEqual(label, CONTRIBUTION_HISTORY_PARTIAL_COPY)
        self.assertEqual(remaining, "—")
        self.assertNotIn("0.00 TRY", label)
        self.assertNotIn("0 TL", label)

    def test_no_history_is_unavailable(self) -> None:
        view = _intel([])
        self.assertEqual(view.monthly_evidence_quality, ContributionEvidenceQuality.UNAVAILABLE)
        self.assertIsNone(view.actual_monthly_net_contribution)
        label = format_contribution_actual_label(
            view.monthly_evidence_quality,
            view.actual_monthly_net_contribution,
            view.currency,
        )
        self.assertEqual(label, CONTRIBUTION_HISTORY_UNAVAILABLE_COPY)
        self.assertNotIn("0.00", label)

    def test_reconciled_zero_is_confirmed_zero(self) -> None:
        view = _intel([], reconciled=True)
        self.assertEqual(view.monthly_evidence_quality, ContributionEvidenceQuality.COMPLETE)
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("0.00"))
        self.assertEqual(view.monthly_remaining, Decimal("60000.00"))
        label = format_contribution_actual_label(
            view.monthly_evidence_quality,
            view.actual_monthly_net_contribution,
            view.currency,
        )
        self.assertEqual(label, "0.00 TRY")

    def test_reconciled_try_net_and_usd_excluded(self) -> None:
        view = _intel(
            [
                _txn(TXN_TYPE_DEPOSIT, 40000),
                _txn(TXN_TYPE_WITHDRAW, 5000, executed_at="2026-08-12T12:00:00+00:00"),
                _txn(TXN_TYPE_DEPOSIT, 1000, currency="USD"),
            ],
            reconciled=True,
        )
        self.assertEqual(view.actual_monthly_net_contribution, Decimal("35000.00"))
        self.assertEqual(view.monthly_remaining, Decimal("25000.00"))

    def test_deposit_without_recon_is_partial(self) -> None:
        view = _intel([_txn(TXN_TYPE_DEPOSIT, 40000)])
        self.assertEqual(view.monthly_evidence_quality, ContributionEvidenceQuality.PARTIAL)
        self.assertIsNone(view.actual_monthly_net_contribution)
        self.assertIsNone(view.monthly_remaining)

    def test_deposit_does_not_auto_reconcile(self) -> None:
        wealth = MagicMock()
        wealth.user_id = "user-1"
        wealth.accounts.get_by_id.return_value = {"id": "acc-1", "portfolio_id": "pf-1"}
        wealth.portfolios.list_for_user.return_value = [{"id": "pf-1"}]
        wealth.ensure_cash_asset.return_value = {"id": "cash-try"}
        wealth.post_transaction.return_value = {"id": "txn-1"}
        record_external_cash_flow(
            wealth,
            portfolio_id="pf-1",
            account_id="acc-1",
            flow_type="DEPOSIT",
            amount=60000,
            currency="TRY",
        )
        wealth.post_transaction.assert_called_once()
        from inspect import getsource

        self.assertNotIn("mark_contribution_reconciled", getsource(record_external_cash_flow))


class WiringAndSafetyTests(TestCase):
    def test_history_and_decision_callers_pass_reconciliation(self) -> None:
        self.assertIn("contribution_reconciliations_for_wealth", HISTORY_PAGE.read_text(encoding="utf-8"))
        self.assertIn(
            "contribution_reconciliations_for_wealth",
            DECISION_UI.read_text(encoding="utf-8"),
        )
        self.assertIn("contribution_reconciliations_for_wealth", UI.read_text(encoding="utf-8"))
        self.assertIn("CONTRIBUTION_RECONCILE_ACTION_LABEL", UI.read_text(encoding="utf-8"))

    def test_dietz_ignores_reconciliation_rows(self) -> None:
        source = DIETZ.read_text(encoding="utf-8")
        self.assertNotIn("wealth_contribution_reconciliations", source)
        self.assertNotIn("ContributionReconciliation", source)
        start = __import__("datetime").datetime(2026, 8, 1, tzinfo=__import__("datetime").timezone.utc)
        end = __import__("datetime").datetime(2026, 8, 17, 23, 59, 59, tzinfo=__import__("datetime").timezone.utc)
        flows = collect_timed_external_flows(
            [
                _txn(TXN_TYPE_DEPOSIT, 50),
                _txn("buy", 50),
                _txn(TXN_TYPE_WITHDRAW, 10, executed_at="2026-08-12T12:00:00+00:00"),
            ],
            account_ids={ACCOUNT},
            base_currency="TRY",
            period_start=start,
            period_end=end,
        )
        self.assertEqual([row.signed_amount for row in flows], [50.0, -10.0])

    def test_no_provider_or_buy_backfill(self) -> None:
        for path in (REPO, UI, DECISION_UI, Path("services/wealth_external_cash_flow.py")):
            source = path.read_text(encoding="utf-8")
            lower = source.lower()
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token.lower(), lower)
            self.assertNotIn("infer deposit", lower)
            self.assertNotIn("buy cost", lower)


if __name__ == "__main__":
    import unittest

    unittest.main()
