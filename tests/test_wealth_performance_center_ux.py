from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from components.wealth_history_ui import render_wealth_history
from services.wealth_contract import TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW
from services.wealth_external_cash_flow import ContributionReconciliation
from services.wealth_history_service import (
    WealthHistoryState,
    build_wealth_history,
)
from services.wealth_performance_center_presentation import (
    BEST_LABEL,
    INSUFFICIENT_COPY,
    SECTION_TITLE,
    STATUS_MISSING,
    STATUS_QTY_CHANGED,
    WEAKEST_LABEL,
    PerformancePeriod,
    build_performance_center,
    select_period_snapshots,
)
from services.wealth_performance_engine import snapshot_view_from_row

PRES = Path("services/wealth_performance_center_presentation.py")
UI = Path("components/wealth_history_ui.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "alpha_vantage",
    "TwelveData",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "BorsaIstanbul",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    "capture_portfolio_snapshot",
    "save_snapshot",
)
ACCOUNT = "acc-1"


def _pos(symbol: str, price, quantity=1, asset_class="equity", **extra) -> dict:
    row = {
        "symbol": symbol,
        "price": price,
        "quantity": quantity,
        "asset_class": asset_class,
        "is_cash": extra.pop("is_cash", False),
    }
    row.update(extra)
    return row


def _snap(
    snap_id: str,
    captured_at: str,
    value: float,
    *,
    positions=None,
    complete: bool = True,
    unpriced: int = 0,
    coverage: float = 100.0,
    mixed: bool = False,
):
    if not complete:
        unpriced = max(unpriced, 1)
        coverage = min(coverage, 80.0)
    return snapshot_view_from_row(
        {
            "id": snap_id,
            "user_id": "u1",
            "portfolio_id": "pf-1",
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
            "valuation_payload": {
                "valuation_complete": complete,
                "priced_positions": list(positions or []),
            },
            "created_at": captured_at,
        }
    )


def _txn(txn_type: str, amount: float, executed_at: str) -> dict:
    return {
        "id": f"{txn_type}-{amount}-{executed_at}",
        "account_id": ACCOUNT,
        "txn_type": txn_type,
        "amount": amount,
        "currency": "USD",
        "executed_at": executed_at,
        "quantity": 0,
    }


def _recon(through: str = "2026-08-22") -> tuple:
    return (
        ContributionReconciliation(
            portfolio_id="pf-1",
            reconciled_through=date.fromisoformat(through[:10]),
        ),
    )


def _series():
    positions_old = [_pos("AAPL", 100, 2), _pos("MSFT", 50, 1, asset_class="etf")]
    positions_new = [_pos("AAPL", 110, 2), _pos("MSFT", 40, 1, asset_class="etf")]
    return [
        _snap("y", "2025-08-22T06:30:00+00:00", 9000.0, positions=positions_old),
        _snap("m", "2026-07-22T06:30:00+00:00", 9500.0, positions=positions_old),
        _snap("w", "2026-08-15T06:30:00+00:00", 9800.0, positions=positions_old),
        _snap("d", "2026-08-21T06:30:00+00:00", 10000.0, positions=positions_old),
        _snap("e", "2026-08-22T06:30:00+00:00", 10100.0, positions=positions_new),
    ]


def _center(snaps, period, txns=(), reconciled=True):
    return build_performance_center(
        snaps,
        period=period,
        transactions=list(txns),
        account_ids=[ACCOUNT],
        contribution_reconciliations=_recon() if reconciled else None,
        portfolio_id="pf-1",
    )


class _Box:
    def __init__(self, parent):
        self.parent = parent

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def markdown(self, text, **kwargs):
        self.parent.markdowns.append(str(text))

    def write(self, text, **kwargs):
        self.parent.writes.append(str(text))

    def caption(self, text, **kwargs):
        self.parent.captions.append(str(text))

    def metric(self, *args, **kwargs):
        return None

    def info(self, text, **kwargs):
        self.parent.infos.append(str(text))


class DummySt:
    def __init__(self, period: str = PerformancePeriod.ALL.value):
        self.period = period
        self.session_state = {}
        self.markdowns: list[str] = []
        self.writes: list[str] = []
        self.captions: list[str] = []
        self.infos: list[str] = []
        self.tables: list = []

    def markdown(self, text, **kwargs):
        self.markdowns.append(str(text))

    def write(self, text, **kwargs):
        self.writes.append(str(text))

    def caption(self, text, **kwargs):
        self.captions.append(str(text))

    def info(self, text, **kwargs):
        self.infos.append(str(text))

    def success(self, text, **kwargs):
        self.infos.append(str(text))

    def warning(self, text, **kwargs):
        self.infos.append(str(text))

    def radio(self, label, options, **kwargs):
        return self.period

    def columns(self, count):
        return [_Box(self), _Box(self)]

    def expander(self, label, **kwargs):
        self.captions.append(str(label))
        return _Box(self)

    def dataframe(self, data, **kwargs):
        self.tables.append(data)

    def altair_chart(self, *args, **kwargs):
        return None

    def metric(self, *args, **kwargs):
        return None


def _blob(dummy: DummySt) -> str:
    return "\n".join(dummy.markdowns + dummy.writes + dummy.captions + dummy.infos)


def _patch(dummy: DummySt):
    return (
        patch("components.wealth_history_ui.st", dummy),
        patch("components.nabi_design_system._st", return_value=dummy),
    )


class PeriodSelectionTests(unittest.TestCase):
    def test_daily_weekly_monthly_yearly_all(self) -> None:
        snaps = _series()
        daily = select_period_snapshots(snaps, PerformancePeriod.DAILY)
        weekly = select_period_snapshots(snaps, PerformancePeriod.WEEKLY)
        monthly = select_period_snapshots(snaps, PerformancePeriod.MONTHLY)
        yearly = select_period_snapshots(snaps, PerformancePeriod.YEARLY)
        all_rows = select_period_snapshots(snaps, PerformancePeriod.ALL)
        self.assertEqual(daily[0].id, "d")
        self.assertEqual(daily[1].id, "e")
        self.assertEqual(weekly[0].id, "w")
        self.assertEqual(monthly[0].id, "m")
        self.assertEqual(yearly[0].id, "y")
        self.assertEqual(all_rows[0].id, "y")
        self.assertEqual(all_rows[1].id, "e")

    def test_insufficient_history(self) -> None:
        snaps = [
            _snap("a", "2026-08-21T06:30:00+00:00", 10000.0),
            _snap("b", "2026-08-22T06:30:00+00:00", 10100.0),
        ]
        center = _center(snaps, PerformancePeriod.YEARLY)
        self.assertFalse(center.sufficient)
        self.assertEqual(center.insufficient_reason, INSUFFICIENT_COPY)
        self.assertIsNone(center.history)
        self.assertEqual(center.best, ())


class PortfolioDietzTests(unittest.TestCase):
    def test_dietz_reused_and_external_flow_separated(self) -> None:
        snaps = [
            _snap("s1", "2026-01-01T00:00:00+00:00", 1000.0, positions=[_pos("AAPL", 100)]),
            _snap("s2", "2026-02-01T00:00:00+00:00", 1500.0, positions=[_pos("AAPL", 100)]),
        ]
        txns = [_txn(TXN_TYPE_DEPOSIT, 500, "2026-01-15T00:00:00+00:00")]
        history = build_wealth_history(
            snaps,
            transactions=txns,
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon("2026-02-01"),
            portfolio_id="pf-1",
        )
        center = build_performance_center(
            snaps,
            period=PerformancePeriod.ALL,
            transactions=txns,
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon("2026-02-01"),
            portfolio_id="pf-1",
        )
        self.assertEqual(center.history.return_pct, history.return_pct)
        self.assertEqual(center.history.net_external_contributions, Decimal("500.00"))
        self.assertEqual(center.history.investment_gain_loss, Decimal("0.00"))
        self.assertEqual(center.history.start_value, history.start_value)

    def test_withdraw_separated(self) -> None:
        snaps = [
            _snap("s1", "2026-01-01T00:00:00+00:00", 1000.0, positions=[_pos("AAPL", 100)]),
            _snap("s2", "2026-02-01T00:00:00+00:00", 800.0, positions=[_pos("AAPL", 80)]),
        ]
        center = build_performance_center(
            snaps,
            period=PerformancePeriod.ALL,
            transactions=[_txn(TXN_TYPE_WITHDRAW, 200, "2026-01-15T00:00:00+00:00")],
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon("2026-02-01"),
            portfolio_id="pf-1",
        )
        self.assertEqual(center.history.net_external_contributions, Decimal("-200.00"))
        self.assertEqual(center.history.investment_gain_loss, Decimal("0.00"))


class ProductAndRankTests(unittest.TestCase):
    def test_product_price_return_and_rank(self) -> None:
        snaps = [
            _snap(
                "s1",
                "2026-01-01T00:00:00+00:00",
                10000.0,
                positions=[
                    _pos("AAPL", 100, 1),
                    _pos("MSFT", 50, 1),
                    _pos("WATCH", 20, 1),
                    _pos("GONE", 10, 1),
                ],
            ),
            _snap(
                "s2",
                "2026-02-01T00:00:00+00:00",
                11000.0,
                positions=[
                    _pos("AAPL", 110, 1),
                    _pos("MSFT", 40, 1),
                    _pos("WATCH", 22, 3),
                    _pos("NEW", 15, 1),
                ],
            ),
        ]
        center = _center(snaps, PerformancePeriod.ALL)
        by_symbol = {row.symbol: row for row in center.products}
        self.assertEqual(by_symbol["AAPL"].period_return, Decimal("0.1"))
        self.assertTrue(by_symbol["AAPL"].comparable)
        self.assertEqual(by_symbol["MSFT"].period_return, Decimal("-0.2"))
        self.assertFalse(by_symbol["WATCH"].comparable)
        self.assertEqual(by_symbol["WATCH"].status, STATUS_QTY_CHANGED)
        self.assertIsNone(by_symbol["WATCH"].period_return)
        self.assertEqual(by_symbol["GONE"].status, STATUS_MISSING)
        self.assertEqual(by_symbol["NEW"].status, STATUS_MISSING)
        self.assertEqual([row.symbol for row in center.best], ["AAPL", "MSFT"])
        self.assertEqual(center.weakest[0].symbol, "MSFT")
        self.assertNotIn("WATCH", [row.symbol for row in center.best])
        self.assertNotIn("GONE", [row.symbol for row in center.best])

    def test_asset_class_grouping(self) -> None:
        snaps = [
            _snap(
                "s1",
                "2026-01-01T00:00:00+00:00",
                10000.0,
                positions=[_pos("AAPL", 100, asset_class="equity"), _pos("SPUS", 50, asset_class="etf")],
            ),
            _snap(
                "s2",
                "2026-02-01T00:00:00+00:00",
                11000.0,
                positions=[_pos("AAPL", 120, asset_class="equity"), _pos("SPUS", 55, asset_class="etf")],
            ),
        ]
        center = _center(snaps, PerformancePeriod.ALL)
        names = [row.asset_class for row in center.asset_classes]
        self.assertEqual(names, ["equity", "etf"])
        equity = next(row for row in center.asset_classes if row.asset_class == "equity")
        self.assertEqual(equity.comparable_count, 1)
        self.assertEqual(equity.average_price_return, Decimal("0.2"))

    def test_partial_snapshot_blocks_dietz_and_rank(self) -> None:
        snaps = [
            _snap("s1", "2026-01-01T00:00:00+00:00", 10000.0, complete=False, positions=[_pos("AAPL", 100)]),
            _snap("s2", "2026-02-01T00:00:00+00:00", 11000.0, complete=False, positions=[_pos("AAPL", 110)]),
        ]
        center = _center(snaps, PerformancePeriod.ALL)
        self.assertFalse(center.sufficient)
        self.assertFalse(center.pair_comparable)
        self.assertIsNone(center.history.return_pct)
        self.assertEqual(center.best, ())
        self.assertTrue(all(not row.comparable for row in center.products))
        self.assertNotEqual(center.history.history_state, WealthHistoryState.COMPARABLE)


class RenderAndSafetyTests(unittest.TestCase):
    def test_ui_renders_center_labels(self) -> None:
        snaps = _series()
        history = build_wealth_history(
            snaps,
            transactions=[],
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon(),
            portfolio_id="pf-1",
        )
        dummy = DummySt(PerformancePeriod.ALL.value)
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_wealth_history(
                history,
                snapshots=snaps,
                transactions=[],
                account_ids=[ACCOUNT],
                contribution_reconciliations=_recon(),
                portfolio_id="pf-1",
            )
        text = _blob(dummy)
        self.assertIn(SECTION_TITLE, text)
        self.assertIn(BEST_LABEL, text)
        self.assertIn(WEAKEST_LABEL, text)
        self.assertIn("Servet Geçmişi", text)
        self.assertTrue(dummy.tables)
        self.assertIn("AAPL", str(dummy.tables[0]))

    def test_ui_insufficient_copy(self) -> None:
        snaps = [
            _snap("a", "2026-08-21T06:30:00+00:00", 10000.0, positions=[_pos("AAPL", 100)]),
            _snap("b", "2026-08-22T06:30:00+00:00", 10100.0, positions=[_pos("AAPL", 110)]),
        ]
        history = build_wealth_history(snaps, account_ids=[ACCOUNT])
        dummy = DummySt(PerformancePeriod.YEARLY.value)
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_wealth_history(history, snapshots=snaps, account_ids=[ACCOUNT])
        self.assertTrue(any(INSUFFICIENT_COPY in row for row in dummy.infos))

    def test_no_execution_writes_or_providers(self) -> None:
        dummy = DummySt()
        wealth = MagicMock()
        snaps = _series()
        history = build_wealth_history(
            snaps,
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon(),
            portfolio_id="pf-1",
        )
        with _patch(dummy)[0], _patch(dummy)[1], patch(
            "services.current_market_data.fetch_fx_rate",
            side_effect=AssertionError("provider"),
        ), patch(
            "services.current_market_data.fetch_equity_quote",
            side_effect=AssertionError("provider"),
        ):
            render_wealth_history(
                history,
                snapshots=snaps,
                account_ids=[ACCOUNT],
                contribution_reconciliations=_recon(),
                portfolio_id="pf-1",
            )
        wealth.post_transaction.assert_not_called()
        text = _blob(dummy).lower()
        self.assertNotIn("buy", text)
        self.assertNotIn("execute", text)
        for path in (PRES, UI):
            source = path.read_text(encoding="utf-8")
            lower = source.lower()
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token.lower(), lower)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
        self.assertIn("build_wealth_history", PRES.read_text(encoding="utf-8"))
        self.assertIn("compute_subperiod_return_for_period", Path("services/wealth_history_service.py").read_text(encoding="utf-8"))
        self.assertNotIn("def modified_dietz", PRES.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
