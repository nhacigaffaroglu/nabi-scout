from __future__ import annotations

import ast
import inspect
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from services.wealth_contract import (
    TXN_TYPE_BUY,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_SELL,
    TXN_TYPE_TRANSFER_IN,
    TXN_TYPE_TRANSFER_OUT,
    TXN_TYPE_WITHDRAW,
)
from services.wealth_contribution_intelligence import (
    ContributionEvidenceQuality,
    PerformanceEvidenceQuality,
)
from services.wealth_external_cash_flow import ContributionReconciliation
from services.wealth_history_chart import build_wealth_history_curve
from services.wealth_history_service import (
    HISTORY_STARTED_COPY,
    HistoryAttributionStatus,
    WealthHistoryState,
    build_wealth_history,
)
from services.wealth_performance_engine import snapshot_view_from_row

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
CHANGED = (
    Path("services/wealth_history_service.py"),
    Path("services/wealth_history_chart.py"),
    Path("components/wealth_history_ui.py"),
)


def _snap(
    *,
    snap_id: str,
    captured_at: str,
    value: float,
    coverage: float = 100.0,
    unpriced: int = 0,
    mixed: bool = False,
) -> dict:
    complete = unpriced == 0 and coverage >= 100.0 and not mixed
    return snapshot_view_from_row(
        {
            "id": snap_id,
            "user_id": "planning",
            "portfolio_id": "planning",
            "captured_at": captured_at,
            "base_currency": "USD",
            "priced_market_value": value,
            "total_cost_basis": 0.0,
            "unrealized_pl": 0.0,
            "cash_value": 0.0,
            "invested_value": value,
            "liabilities_total": None,
            "net_wealth_partial": None,
            "priced_position_coverage_pct": coverage,
            "unpriced_position_count": unpriced,
            "mixed_currency_warning": mixed,
            "valuation_payload": {"valuation_complete": complete},
            "created_at": captured_at,
        }
    )


def _txn(txn_type: str, amount: float, *, executed_at: str, currency: str = "USD") -> dict:
    return {
        "id": f"{txn_type}-{amount}-{executed_at}",
        "account_id": ACCOUNT,
        "txn_type": txn_type,
        "amount": amount,
        "currency": currency,
        "executed_at": executed_at,
        "quantity": 0,
    }


def _recon(through: str = "2026-02-01") -> tuple[ContributionReconciliation, ...]:
    return (
        ContributionReconciliation(
            portfolio_id="planning",
            reconciled_through=date.fromisoformat(through[:10]),
        ),
    )


def _history(snaps, txns=(), account_ids=None, reconciled: bool = False, through: str = "2026-02-01"):
    return build_wealth_history(
        snaps,
        transactions=list(txns),
        account_ids=[ACCOUNT] if account_ids is None else account_ids,
        contribution_reconciliations=_recon(through) if reconciled else None,
    )


class WealthHistoryContractTests(unittest.TestCase):
    def test_zero_snapshots(self) -> None:
        view = _history([])
        self.assertEqual(view.snapshot_count, 0)
        self.assertEqual(view.history_state, WealthHistoryState.ZERO)
        self.assertEqual(view.evidence_quality, PerformanceEvidenceQuality.UNAVAILABLE)
        self.assertIsNone(view.return_pct)
        self.assertFalse(view.bridge_available)

    def test_one_snapshot(self) -> None:
        view = _history(
            [_snap(snap_id="s1", captured_at="2026-08-17T06:30:00+00:00", value=10000.0, unpriced=3, mixed=True, coverage=25.0)]
        )
        self.assertEqual(view.history_state, WealthHistoryState.STARTED)
        self.assertEqual(view.evidence_quality, PerformanceEvidenceQuality.UNAVAILABLE)
        self.assertIsNone(view.return_pct)
        self.assertIsNone(view.investment_gain_loss)
        self.assertIsNone(view.period_start)
        self.assertEqual(view.summary, HISTORY_STARTED_COPY)
        self.assertTrue(view.latest_is_partial)

    def test_no_fake_return_with_one_snapshot(self) -> None:
        view = _history([_snap(snap_id="s1", captured_at="2026-08-17T06:30:00+00:00", value=10000.0)])
        self.assertIsNone(view.return_pct)
        self.assertNotEqual(view.return_pct, Decimal("0"))
        self.assertIsNone(view.investment_gain_loss)

    def test_two_snapshots_dietz(self) -> None:
        view = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=10000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=11000.0),
            ],
            [_txn(TXN_TYPE_DEPOSIT, 0, executed_at="2026-01-15T00:00:00+00:00")],
            reconciled=True,
        )
        self.assertEqual(view.history_state, WealthHistoryState.COMPARABLE)
        self.assertEqual(view.evidence_quality, PerformanceEvidenceQuality.COMPLETE)
        self.assertEqual(view.return_pct, Decimal("10.00"))
        self.assertEqual(view.investment_gain_loss, Decimal("1000.00"))
        self.assertTrue(view.bridge_available)

    def test_three_plus_chronology(self) -> None:
        view = _history(
            [
                _snap(snap_id="s3", captured_at="2026-03-01T00:00:00+00:00", value=12000.0),
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=10000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=11000.0),
            ],
            [_txn(TXN_TYPE_DEPOSIT, 0, executed_at="2026-01-15T00:00:00+00:00")],
        )
        times = [point.captured_at for point in view.curve_points]
        self.assertEqual(
            times,
            [
                "2026-01-01T00:00:00+00:00",
                "2026-02-01T00:00:00+00:00",
                "2026-03-01T00:00:00+00:00",
            ],
        )
        self.assertEqual(view.snapshot_count, 3)
        self.assertEqual(view.start_value, Decimal("10000.00"))
        self.assertEqual(view.end_value, Decimal("12000.00"))

    def test_deposits_counted(self) -> None:
        view = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=1000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=1500.0),
            ],
            [_txn(TXN_TYPE_DEPOSIT, 500, executed_at="2026-01-15T00:00:00+00:00")],
            reconciled=True,
        )
        self.assertEqual(view.net_external_contributions, Decimal("500.00"))
        self.assertEqual(view.investment_gain_loss, Decimal("0.00"))
        self.assertEqual(view.attribution_status, HistoryAttributionStatus.CONTRIBUTION_ONLY)

    def test_withdrawals_negative(self) -> None:
        view = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=1000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=800.0),
            ],
            [_txn(TXN_TYPE_WITHDRAW, 200, executed_at="2026-01-15T00:00:00+00:00")],
            reconciled=True,
        )
        self.assertEqual(view.net_external_contributions, Decimal("-200.00"))
        self.assertEqual(view.investment_gain_loss, Decimal("0.00"))

    def test_transfers_excluded(self) -> None:
        view = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=1000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=1100.0),
            ],
            [
                _txn(TXN_TYPE_DEPOSIT, 0, executed_at="2026-01-02T00:00:00+00:00"),
                _txn(TXN_TYPE_TRANSFER_OUT, 400, executed_at="2026-01-10T00:00:00+00:00"),
                _txn(TXN_TYPE_TRANSFER_IN, 400, executed_at="2026-01-10T00:00:01+00:00"),
            ],
            reconciled=True,
        )
        self.assertEqual(view.net_external_contributions, Decimal("0.00"))
        self.assertEqual(view.investment_gain_loss, Decimal("100.00"))

    def test_dividend_and_buy_excluded(self) -> None:
        view = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=1000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=1600.0),
            ],
            [
                _txn(TXN_TYPE_DEPOSIT, 500, executed_at="2026-01-15T00:00:00+00:00"),
                _txn(TXN_TYPE_DIVIDEND, 80, executed_at="2026-01-16T00:00:00+00:00"),
                _txn(TXN_TYPE_BUY, 400, executed_at="2026-01-17T00:00:00+00:00"),
                _txn(TXN_TYPE_SELL, 50, executed_at="2026-01-18T00:00:00+00:00"),
            ],
            reconciled=True,
        )
        self.assertEqual(view.net_external_contributions, Decimal("500.00"))
        self.assertEqual(view.investment_gain_loss, Decimal("100.00"))
        self.assertEqual(view.attribution_status, HistoryAttributionStatus.BOTH)

    def test_contribution_evidence_partial(self) -> None:
        view = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=10000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=11000.0),
            ],
            [_txn(TXN_TYPE_BUY, 1000, executed_at="2026-01-15T00:00:00+00:00")],
        )
        self.assertEqual(
            view.contribution_evidence_quality, ContributionEvidenceQuality.PARTIAL
        )
        self.assertEqual(
            view.attribution_status, HistoryAttributionStatus.EVIDENCE_INCOMPLETE
        )
        self.assertIsNone(view.investment_gain_loss)
        self.assertIsNone(view.return_pct)
        self.assertFalse(view.bridge_available)

    def test_performance_partial_and_unavailable(self) -> None:
        partial = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=10000.0, unpriced=3, coverage=25.0, mixed=True),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=11000.0, unpriced=3, coverage=25.0, mixed=True),
            ],
            [_txn(TXN_TYPE_DEPOSIT, 0, executed_at="2026-01-15T00:00:00+00:00")],
        )
        self.assertEqual(partial.evidence_quality, PerformanceEvidenceQuality.PARTIAL)
        self.assertIsNone(partial.return_pct)
        self.assertFalse(partial.bridge_available)
        none = _history([])
        self.assertEqual(none.evidence_quality, PerformanceEvidenceQuality.UNAVAILABLE)

    def test_complete_attribution_and_variants(self) -> None:
        both = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=1000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=1600.0),
            ],
            [_txn(TXN_TYPE_DEPOSIT, 500, executed_at="2026-01-15T00:00:00+00:00")],
            reconciled=True,
        )
        self.assertEqual(both.attribution_status, HistoryAttributionStatus.BOTH)
        contrib = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=1000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=1500.0),
            ],
            [_txn(TXN_TYPE_DEPOSIT, 500, executed_at="2026-01-15T00:00:00+00:00")],
            reconciled=True,
        )
        self.assertEqual(contrib.attribution_status, HistoryAttributionStatus.CONTRIBUTION_ONLY)
        perf = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=10000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=11000.0),
            ],
            [_txn(TXN_TYPE_DEPOSIT, 0, executed_at="2026-01-15T00:00:00+00:00")],
            reconciled=True,
        )
        self.assertEqual(perf.attribution_status, HistoryAttributionStatus.PERFORMANCE_ONLY)

    def test_mismatched_coverage_blocks_return(self) -> None:
        view = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=10000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=11000.0, coverage=50.0, unpriced=3, mixed=True),
            ],
            [_txn(TXN_TYPE_DEPOSIT, 0, executed_at="2026-01-15T00:00:00+00:00")],
        )
        self.assertIsNone(view.return_pct)
        self.assertEqual(view.evidence_quality, PerformanceEvidenceQuality.PARTIAL)

    def test_two_partial_snapshots_do_not_manufacture_return(self) -> None:
        view = _history(
            [
                _snap(
                    snap_id="s1",
                    captured_at="2026-08-17T06:30:00+00:00",
                    value=58642.1676,
                    coverage=80.0,
                    unpriced=3,
                    mixed=True,
                ),
                _snap(
                    snap_id="s2",
                    captured_at="2026-08-18T06:30:00+00:00",
                    value=58515.9676,
                    coverage=80.0,
                    unpriced=3,
                    mixed=False,
                ),
            ],
            [_txn(TXN_TYPE_BUY, 0, executed_at="2026-08-17T12:00:00+00:00")],
        )
        self.assertIsNone(view.return_pct)
        self.assertIsNone(view.investment_gain_loss)
        self.assertFalse(view.bridge_available)
        self.assertNotEqual(view.return_pct, Decimal("0"))
        self.assertEqual(view.evidence_quality, PerformanceEvidenceQuality.PARTIAL)

    def test_history_reason_strings_are_turkish(self) -> None:
        view = _history(
            [
                _snap(
                    snap_id="s1",
                    captured_at="2026-08-17T06:30:00+00:00",
                    value=58642.1676,
                    coverage=80.0,
                    unpriced=3,
                    mixed=True,
                ),
                _snap(
                    snap_id="s2",
                    captured_at="2026-08-18T06:30:00+00:00",
                    value=58515.9676,
                    coverage=80.0,
                    unpriced=3,
                    mixed=True,
                ),
            ]
        )
        reasons = " ".join(view.limitations)
        self.assertIn("Karışık para birimli görüntüler tam karşılaştırılamaz.", reasons)
        self.assertIn("Başlangıç veya bitişte fiyatsız pozisyon var.", reasons)
        self.assertIn("Başlangıç veya bitişte fiyatlı pozisyon kapsamı eksik.", reasons)
        ui = Path("components/wealth_history_ui.py").read_text(encoding="utf-8")
        self.assertIn("Getiri % gösterilmiyor", ui)
        self.assertNotIn("Incomplete priced-position coverage", reasons)
        self.assertNotIn("Mixed-currency snapshots", reasons)
        self.assertNotIn("Unpriced positions present", reasons)
        self.assertNotIn("Portfolio performance is not comparable.", reasons)
        engine = Path("services/wealth_performance_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("Mixed-currency snapshots are not fully comparable.", engine)
        self.assertNotIn("Portfolio performance is not comparable.", Path("services/wealth_benchmark_service.py").read_text(encoding="utf-8"))

    def test_wealth_curve_requires_two_points_no_interpolation(self) -> None:
        one = _history([_snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=10000.0)])
        self.assertIsNone(build_wealth_history_curve(one.curve_points))
        two = _history(
            [
                _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=10000.0),
                _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=11000.0),
            ]
        )
        chart = build_wealth_history_curve(two.curve_points)
        self.assertIsNotNone(chart)
        self.assertEqual(len(two.curve_points), 2)


class SafetyAndUiTests(unittest.TestCase):
    def test_no_provider_calls(self) -> None:
        for path in CHANGED:
            source = path.read_text(encoding="utf-8").lower()
            for token in PROVIDER_TOKENS:
                with self.subTest(path=str(path), token=token):
                    self.assertNotIn(token.lower(), source)

    def test_no_ledger_writes(self) -> None:
        for path in (
            Path("services/wealth_history_service.py"),
            Path("components/wealth_history_ui.py"),
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("post_transaction", source)
            self.assertNotIn("register_asset", source)
            self.assertNotIn(".delete(", source)

    def test_build_wealth_history_accepts_contribution_reconciliations(self) -> None:
        sig = inspect.signature(build_wealth_history)
        self.assertIn("contribution_reconciliations", sig.parameters)
        self.assertIsNone(sig.parameters["contribution_reconciliations"].default)
        omitted = build_wealth_history([])
        self.assertEqual(omitted.snapshot_count, 0)
        snaps = [
            _snap(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=10000.0),
            _snap(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=11000.0),
        ]
        try:
            view = build_wealth_history(
                snaps,
                transactions=[],
                account_ids=[ACCOUNT],
                contribution_reconciliations=_recon("2026-02-01"),
                portfolio_id="planning",
            )
        except TypeError as exc:
            self.fail(f"page-shaped call raised TypeError: {exc}")
        self.assertEqual(view.history_state, WealthHistoryState.COMPARABLE)
        self.assertEqual(view.contribution_evidence_quality, ContributionEvidenceQuality.COMPLETE)

    def test_wealth_page_imports_canonical_history_signature(self) -> None:
        page_path = Path("pages/10_Wealth.py")
        source = page_path.read_text(encoding="utf-8")
        self.assertIn(
            "from services.wealth_history_service import build_wealth_history",
            source,
        )
        tree = ast.parse(source, filename=str(page_path))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_wealth_history"
        ]
        self.assertEqual(len(calls), 1)
        keywords = {kw.arg for kw in calls[0].keywords}
        self.assertIn("contribution_reconciliations", keywords)
        self.assertIn("portfolio_id", keywords)
        compile(source, str(page_path), "exec")
        page_fn = inspect.signature(build_wealth_history)
        for name in keywords:
            self.assertIn(name, page_fn.parameters)

    def test_ui_and_schedule(self) -> None:
        page = Path("pages/10_Wealth.py").read_text(encoding="utf-8")
        self.assertIn("render_wealth_history", page)
        self.assertIn("contribution_reconciliations_for_wealth", page)
        self.assertIn("Servet Geçmişi", Path("components/wealth_history_ui.py").read_text(encoding="utf-8"))
        self.assertNotIn("st.line_chart", page)
        workflow = Path(".github/workflows/daily_wealth_snapshot.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "30 6 * * *"', workflow)
        self.assertNotIn("FMP_API_KEY", workflow)
        self.assertNotIn("SEC_CONTACT_EMAIL", workflow)
        capture = Path("services/wealth_snapshot_capture_service.py").read_text(encoding="utf-8")
        self.assertIn("ALREADY_CAPTURED", capture)
        self.assertIn("Europe/Istanbul", Path("scripts/run_daily_wealth_snapshot.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
