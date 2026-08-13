import inspect
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_core_service import WealthCoreService
from services.wealth_performance_engine import (
    _txn_in_period,
    aggregate_cash_flows,
    build_performance_period,
    snapshot_view_from_row,
)
from services.wealth_contract import WealthValidationError
from services.wealth_snapshot_serializer import (
    build_valuation_payload,
    snapshot_row_from_intelligence_view,
)
from services.wealth_timeline_contract import PortfolioSnapshotView
from services.wealth_timeline_service import WealthTimelineService


def _sample_intelligence_view(**overrides) -> PortfolioIntelligenceView:
    base = PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=10000.0,
        priced_total_cost_basis=9000.0,
        priced_total_unrealized_pl=1000.0,
        priced_position_count=2,
        unpriced_position_count=0,
        foreign_currency_position_count=0,
        total_position_count=2,
        mixed_currency_warning=False,
        fx_supported=False,
        priced_positions=[
            PositionValuationRow(
                position_id="p1",
                account_id="a1",
                asset_id="as1",
                symbol="AAPL",
                asset_class="equity",
                account_name="Broker",
                quantity=10,
                average_cost=100,
                valuation_currency="USD",
                price=110,
                price_available=True,
                market_value=1100,
                cost_basis=1000,
                unrealized_pl=100,
                weight_pct=11.0,
                is_cash=False,
                included_in_base_totals=True,
            ),
            PositionValuationRow(
                position_id="p2",
                account_id="a1",
                asset_id="as2",
                symbol="CASH",
                asset_class="cash",
                account_name="Cash",
                quantity=8900,
                average_cost=1,
                valuation_currency="USD",
                price=1,
                price_available=True,
                market_value=8900,
                cost_basis=8900,
                unrealized_pl=0,
                weight_pct=89.0,
                is_cash=True,
                included_in_base_totals=True,
            ),
        ],
        unpriced_positions=[],
        foreign_currency_positions=[],
        asset_class_allocation=[
            AllocationSlice(key="equity", label="equity", market_value=1100, weight_pct=11),
            AllocationSlice(key="cash", label="cash", market_value=8900, weight_pct=89),
        ],
        account_allocation=[
            AllocationSlice(key="a1", label="Broker", market_value=1100, weight_pct=11),
        ],
        health=PortfolioHealthMetrics(
            largest_position_weight_pct=89.0,
            top3_concentration_pct=100.0,
            largest_asset_class_concentration_pct=89.0,
            cash_pct=89.0,
            invested_pct=11.0,
            priced_position_coverage_pct=100.0,
        ),
        valuation_errors=[],
        price_provider="fmp",
        unique_price_symbols_fetched=1,
    )
    for key, value in overrides.items():
        object.__setattr__(base, key, value)
    return base


class WealthSnapshotSerializerTests(unittest.TestCase):
    def test_snapshot_payload_excludes_nabi_and_provider(self) -> None:
        view = _sample_intelligence_view()
        payload = build_valuation_payload(view)
        serialized = str(payload)
        self.assertNotIn("nabi", serialized.lower())
        self.assertNotIn("provider", serialized.lower())
        self.assertEqual(payload["priced_total_market_value"], 10000.0)
        self.assertEqual(len(payload["priced_positions"]), 2)

    def test_snapshot_row_from_intelligence_view(self) -> None:
        view = _sample_intelligence_view()
        row = snapshot_row_from_intelligence_view(
            user_id="user-a",
            portfolio_id="pf-1",
            captured_at="2026-08-13T12:00:00+00:00",
            view=view,
            liabilities_total=500.0,
        )
        self.assertEqual(row["priced_market_value"], 10000.0)
        self.assertAlmostEqual(row["cash_value"], 8900.0)
        self.assertAlmostEqual(row["invested_value"], 1100.0)
        self.assertAlmostEqual(row["net_wealth_partial"], 9500.0)


class WealthPerformanceEngineTests(unittest.TestCase):
    def _snapshot(
        self,
        *,
        snap_id: str,
        captured_at: str,
        value: float,
        coverage: float = 100.0,
        unpriced: int = 0,
        mixed: bool = False,
        currency: str = "USD",
    ) -> PortfolioSnapshotView:
        return snapshot_view_from_row(
            {
                "id": snap_id,
                "user_id": "user-a",
                "portfolio_id": "pf-1",
                "captured_at": captured_at,
                "base_currency": currency,
                "priced_market_value": value,
                "total_cost_basis": value,
                "unrealized_pl": 0,
                "cash_value": 0,
                "invested_value": value,
                "liabilities_total": None,
                "net_wealth_partial": None,
                "priced_position_coverage_pct": coverage,
                "unpriced_position_count": unpriced,
                "mixed_currency_warning": mixed,
                "valuation_payload": {},
                "created_at": captured_at,
            }
        )

    def test_investment_gain_identity(self) -> None:
        start = self._snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
        )
        end = self._snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=11500.0,
        )
        txns = [
            {
                "id": "t1",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 1000,
                "currency": "USD",
                "executed_at": "2026-01-15T00:00:00+00:00",
            }
        ]
        period = build_performance_period(
            start=start,
            end=end,
            transactions=txns,
            account_ids={"acc-1"},
        )
        self.assertAlmostEqual(period.net_external_flow, 1000.0)
        self.assertAlmostEqual(period.investment_gain, 500.0)
        self.assertAlmostEqual(
            period.end_priced_value - period.start_priced_value - period.net_external_flow,
            period.investment_gain,
        )

    def test_buy_sell_not_external_flow(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        txns = [
            {
                "id": "t1",
                "account_id": "acc-1",
                "txn_type": "buy",
                "amount": 5000,
                "currency": "USD",
                "executed_at": "2026-01-10T00:00:00+00:00",
            },
            {
                "id": "t2",
                "account_id": "acc-1",
                "txn_type": "sell",
                "amount": 2000,
                "currency": "USD",
                "executed_at": "2026-01-20T00:00:00+00:00",
            },
        ]
        inflows, outflows, dividend, fee, _ = aggregate_cash_flows(
            txns,
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=start,
            period_end=end,
        )
        self.assertEqual(inflows, 0.0)
        self.assertEqual(outflows, 0.0)
        self.assertEqual(dividend, 0.0)
        self.assertEqual(fee, 0.0)

    def test_reversed_deposit_not_counted(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        txns = [
            {
                "id": "t1",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 1000,
                "currency": "USD",
                "executed_at": "2026-01-05T00:00:00+00:00",
            },
            {
                "id": "t2",
                "account_id": "acc-1",
                "txn_type": "withdraw",
                "amount": 1000,
                "currency": "USD",
                "executed_at": "2026-01-06T00:00:00+00:00",
                "reversal_of_id": "t1",
            },
        ]
        inflows, outflows, _, _, _ = aggregate_cash_flows(
            txns,
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=start,
            period_end=end,
        )
        self.assertAlmostEqual(inflows - outflows, 0.0)

    def test_dividend_and_fee_classification(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        txns = [
            {
                "id": "t1",
                "account_id": "acc-1",
                "txn_type": "dividend",
                "amount": 50,
                "currency": "USD",
                "executed_at": "2026-01-10T00:00:00+00:00",
            },
            {
                "id": "t2",
                "account_id": "acc-1",
                "txn_type": "fee",
                "amount": 10,
                "currency": "USD",
                "executed_at": "2026-01-12T00:00:00+00:00",
            },
        ]
        inflows, outflows, dividend, fee, _ = aggregate_cash_flows(
            txns,
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=start,
            period_end=end,
        )
        self.assertEqual(inflows, 0.0)
        self.assertEqual(outflows, 0.0)
        self.assertEqual(dividend, 50.0)
        self.assertEqual(fee, 10.0)

    def test_partial_snapshots_not_comparable(self) -> None:
        start = self._snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
            coverage=50.0,
            unpriced=1,
        )
        end = self._snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=11000.0,
            coverage=100.0,
        )
        period = build_performance_period(
            start=start,
            end=end,
            transactions=[],
            account_ids={"acc-1"},
        )
        self.assertFalse(period.performance_comparable)
        self.assertIsNone(period.simple_period_return_pct)

    def test_mixed_currency_snapshots_not_comparable(self) -> None:
        start = self._snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
            mixed=True,
        )
        end = self._snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=11000.0,
        )
        period = build_performance_period(
            start=start,
            end=end,
            transactions=[],
            account_ids={"acc-1"},
        )
        self.assertFalse(period.performance_comparable)

    def test_currency_mismatch_not_comparable(self) -> None:
        start = self._snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
            currency="USD",
        )
        end = self._snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=11000.0,
            currency="EUR",
        )
        period = build_performance_period(
            start=start,
            end=end,
            transactions=[],
            account_ids={"acc-1"},
        )
        self.assertFalse(period.performance_comparable)

    def test_complete_snapshots_are_comparable_without_flows(self) -> None:
        start = self._snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=10000.0,
        )
        end = self._snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=11000.0,
        )
        period = build_performance_period(
            start=start,
            end=end,
            transactions=[],
            account_ids={"acc-1"},
        )
        self.assertTrue(period.performance_comparable)
        self.assertAlmostEqual(period.simple_period_return_pct, 10.0)

    def test_external_flow_blocks_simple_return(self) -> None:
        start = self._snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=1000.0,
        )
        end = self._snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=1600.0,
        )
        txns = [
            {
                "id": "t1",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 500,
                "currency": "USD",
                "executed_at": "2026-01-15T00:00:00+00:00",
            }
        ]
        period = build_performance_period(
            start=start,
            end=end,
            transactions=txns,
            account_ids={"acc-1"},
        )
        self.assertAlmostEqual(period.net_external_flow, 500.0)
        self.assertAlmostEqual(period.investment_gain, 100.0)
        self.assertIsNone(period.simple_period_return_pct)

    def test_accounting_scenarios(self) -> None:
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 1, tzinfo=timezone.utc)
        scenarios = [
            ("deposit_only", [{"id": "d1", "account_id": "acc-1", "txn_type": "deposit", "amount": 500, "currency": "USD", "executed_at": "2026-01-15T00:00:00+00:00"}], 500.0, 0.0, 100.0),
            ("withdraw_only", [{"id": "w1", "account_id": "acc-1", "txn_type": "withdraw", "amount": 200, "currency": "USD", "executed_at": "2026-01-15T00:00:00+00:00"}], -200.0, 0.0, 100.0),
            ("deposit_and_withdraw", [{"id": "d1", "account_id": "acc-1", "txn_type": "deposit", "amount": 500, "currency": "USD", "executed_at": "2026-01-10T00:00:00+00:00"}, {"id": "w1", "account_id": "acc-1", "txn_type": "withdraw", "amount": 200, "currency": "USD", "executed_at": "2026-01-20T00:00:00+00:00"}], 300.0, 0.0, 100.0),
        ]
        for name, txns, net_flow, div, gain in scenarios:
            with self.subTest(name=name):
                start = self._snapshot(snap_id="s1", captured_at="2026-01-01T00:00:00+00:00", value=1000.0)
                end = self._snapshot(snap_id="s2", captured_at="2026-02-01T00:00:00+00:00", value=1000.0 + net_flow + gain)
                period = build_performance_period(start=start, end=end, transactions=txns, account_ids={"acc-1"})
                self.assertAlmostEqual(period.net_external_flow, net_flow)
                self.assertAlmostEqual(period.investment_gain, gain)

    def test_period_boundary_exact_semantics(self) -> None:
        t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(_txn_in_period(t1, period_start=t1, period_end=t2))
        self.assertTrue(
            _txn_in_period(
                t1 + timedelta(microseconds=1),
                period_start=t1,
                period_end=t2,
            )
        )
        self.assertTrue(_txn_in_period(t2, period_start=t1, period_end=t2))
        self.assertFalse(
            _txn_in_period(
                t2 + timedelta(microseconds=1),
                period_start=t1,
                period_end=t2,
            )
        )

        txns = [
            {
                "id": "at_t1",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 100,
                "currency": "USD",
                "executed_at": t1.isoformat(),
            },
            {
                "id": "after_t1",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 200,
                "currency": "USD",
                "executed_at": (t1 + timedelta(seconds=1)).isoformat(),
            },
            {
                "id": "at_t2",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 300,
                "currency": "USD",
                "executed_at": t2.isoformat(),
            },
            {
                "id": "after_t2",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 400,
                "currency": "USD",
                "executed_at": (t2 + timedelta(seconds=1)).isoformat(),
            },
        ]
        inflows, _, _, _, _ = aggregate_cash_flows(
            txns,
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=t1,
            period_end=t2,
        )
        self.assertAlmostEqual(inflows, 500.0)

    def test_reversal_after_period_end_still_counts_deposit(self) -> None:
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 1, tzinfo=timezone.utc)
        txns = [
            {
                "id": "dep",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 500,
                "currency": "USD",
                "executed_at": "2026-01-15T00:00:00+00:00",
            },
            {
                "id": "rev",
                "account_id": "acc-1",
                "txn_type": "withdraw",
                "amount": 500,
                "currency": "USD",
                "executed_at": "2026-03-01T00:00:00+00:00",
                "reversal_of_id": "dep",
            },
        ]
        inflows, outflows, _, _, _ = aggregate_cash_flows(
            txns,
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=t1,
            period_end=t2,
        )
        self.assertAlmostEqual(inflows, 500.0)
        self.assertAlmostEqual(outflows, 0.0)

    def test_reversal_inside_period_for_preperiod_deposit(self) -> None:
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 1, tzinfo=timezone.utc)
        txns = [
            {
                "id": "dep",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 500,
                "currency": "USD",
                "executed_at": "2025-12-15T00:00:00+00:00",
            },
            {
                "id": "rev",
                "account_id": "acc-1",
                "txn_type": "withdraw",
                "amount": 500,
                "currency": "USD",
                "executed_at": "2026-01-15T00:00:00+00:00",
                "reversal_of_id": "dep",
            },
        ]
        inflows, outflows, _, _, _ = aggregate_cash_flows(
            txns,
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=t1,
            period_end=t2,
        )
        self.assertAlmostEqual(inflows, 0.0)
        self.assertAlmostEqual(outflows, 500.0)

    def test_truncated_history_not_comparable(self) -> None:
        start = self._snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=1000.0,
        )
        end = self._snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=1100.0,
        )
        period = build_performance_period(
            start=start,
            end=end,
            transactions=[],
            account_ids={"acc-1"},
            transaction_history_complete=False,
        )
        self.assertFalse(period.performance_comparable)
        self.assertTrue(any("truncated" in w.lower() for w in period.warnings))


class WealthTimelineServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.wealth = WealthCoreService(MagicMock(), "user-a")
        self.service = WealthTimelineService(self.wealth)

    def test_save_snapshot_uses_existing_view_without_refetch(self) -> None:
        view = _sample_intelligence_view()
        self.wealth.list_liabilities = MagicMock(return_value=[])
        self.wealth.portfolios.list_for_user = MagicMock(
            return_value=[{"id": "pf-1", "user_id": "user-a"}]
        )
        self.service.snapshots.insert = MagicMock(
            return_value={
                "id": "snap-1",
                "user_id": "user-a",
                "portfolio_id": "pf-1",
                "captured_at": "2026-08-13T12:00:00+00:00",
                "base_currency": "USD",
                "priced_market_value": 10000.0,
                "total_cost_basis": 9000.0,
                "unrealized_pl": 1000.0,
                "cash_value": 8900.0,
                "invested_value": 1100.0,
                "liabilities_total": 0,
                "net_wealth_partial": 10000.0,
                "priced_position_coverage_pct": 100.0,
                "unpriced_position_count": 0,
                "mixed_currency_warning": False,
                "valuation_payload": {},
                "created_at": "2026-08-13T12:00:00+00:00",
            }
        )
        saved = self.service.save_snapshot_from_view(
            {"id": "pf-1", "name": "Main", "base_currency": "USD"},
            view,
        )
        self.assertEqual(saved.priced_market_value, 10000.0)
        self.service.snapshots.insert.assert_called_once()
        payload = self.service.snapshots.insert.call_args.args[0]
        self.assertEqual(payload["user_id"], "user-a")
        self.assertEqual(payload["priced_market_value"], 10000.0)

    def test_save_snapshot_rejects_foreign_portfolio(self) -> None:
        view = _sample_intelligence_view()
        self.wealth.portfolios.list_for_user = MagicMock(return_value=[])
        with self.assertRaises(WealthValidationError):
            self.service.save_snapshot_from_view(
                {"id": "pf-1", "name": "Main", "base_currency": "USD"},
                view,
            )

    def test_timeline_history_has_no_provider_calls(self) -> None:
        self.service.snapshots.list_for_portfolio = MagicMock(return_value=[])
        self.wealth.list_accounts = MagicMock(return_value=[])
        timeline = self.service.build_timeline_view(
            {"id": "pf-1", "name": "Main", "base_currency": "USD"}
        )
        self.service.snapshots.list_for_portfolio.assert_called_once()
        self.assertEqual(timeline.snapshots, [])

    def test_timeline_service_has_no_price_provider_import(self) -> None:
        source = Path("services/wealth_timeline_service.py").read_text(encoding="utf-8")
        self.assertNotIn("WealthPriceService", source)
        self.assertNotIn("FMPClient", source)
        self.assertNotIn("portfolio_intelligence_service", source)

    def test_build_timeline_compare_latest_two(self) -> None:
        rows = [
            {
                "id": "s2",
                "user_id": "user-a",
                "portfolio_id": "pf-1",
                "captured_at": "2026-02-01T00:00:00+00:00",
                "base_currency": "USD",
                "priced_market_value": 11000.0,
                "total_cost_basis": 10000.0,
                "unrealized_pl": 1000.0,
                "cash_value": 0,
                "invested_value": 11000.0,
                "liabilities_total": None,
                "net_wealth_partial": None,
                "priced_position_coverage_pct": 100.0,
                "unpriced_position_count": 0,
                "mixed_currency_warning": False,
                "valuation_payload": {},
                "created_at": "2026-02-01T00:00:00+00:00",
            },
            {
                "id": "s1",
                "user_id": "user-a",
                "portfolio_id": "pf-1",
                "captured_at": "2026-01-01T00:00:00+00:00",
                "base_currency": "USD",
                "priced_market_value": 10000.0,
                "total_cost_basis": 9000.0,
                "unrealized_pl": 1000.0,
                "cash_value": 0,
                "invested_value": 10000.0,
                "liabilities_total": None,
                "net_wealth_partial": None,
                "priced_position_coverage_pct": 100.0,
                "unpriced_position_count": 0,
                "mixed_currency_warning": False,
                "valuation_payload": {},
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        ]
        self.service.snapshots.list_for_portfolio = MagicMock(return_value=rows)
        self.wealth.list_accounts = MagicMock(
            return_value=[{"id": "acc-1", "portfolio_id": "pf-1"}]
        )
        self.wealth.transactions.list_for_user = MagicMock(return_value=[])
        timeline = self.service.build_timeline_view(
            {"id": "pf-1", "name": "Main", "base_currency": "USD"}
        )
        self.assertIsNotNone(timeline.latest_period)
        self.assertAlmostEqual(timeline.latest_period.investment_gain, 1000.0)


class WealthTimelineFirewallTests(unittest.TestCase):
    MODULES = (
        "services.wealth_timeline_contract",
        "services.wealth_snapshot_serializer",
        "services.wealth_performance_engine",
        "services.wealth_timeline_service",
    )
    FORBIDDEN = (
        "nabi_score",
        "decision_engine",
        "get_investment_intelligence",
        "participation",
        "scanner_v",
    )

    def test_performance_modules_have_no_nabi_dependency(self) -> None:
        for module_name in self.MODULES:
            module = __import__(module_name, fromlist=["*"])
            source = inspect.getsource(module)
            with self.subTest(module=module_name):
                for token in self.FORBIDDEN:
                    self.assertNotIn(token, source)

    def test_timeline_modules_do_not_write(self) -> None:
        for module_name in self.MODULES:
            path = Path(module_name.replace(".", "/") + ".py")
            source = path.read_text(encoding="utf-8")
            with self.subTest(module=module_name):
                self.assertNotIn(".update(", source)
                self.assertNotIn(".delete(", source)
                if module_name.endswith("_repository"):
                    continue
                self.assertNotIn(".upsert(", source)


class WealthTimelineMigrationTests(unittest.TestCase):
    MIGRATION_PATH = Path("database/migration_wealth_timeline_phase3.sql")

    def test_migration_exists(self) -> None:
        self.assertTrue(self.MIGRATION_PATH.is_file())

    def test_append_only_rls(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        self.assertIn("wealth_portfolio_snapshots", sql)
        self.assertIn("auth.uid() = user_id", sql)
        self.assertIn("for select", sql)
        self.assertIn("for insert", sql)
        self.assertNotIn("for update", sql)
        self.assertNotIn("for delete", sql)
        self.assertNotIn("to anon", sql)

    def test_composite_portfolio_owner_fkey(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        self.assertIn("wealth_portfolio_snapshots_portfolio_owner_fkey", sql)
        self.assertIn(
            "foreign key (user_id, portfolio_id)",
            sql,
        )
        self.assertIn(
            "references public.wealth_portfolios (user_id, id)",
            sql,
        )

    def test_cross_user_portfolio_fk_blocks_mismatch(self) -> None:
        phase1 = Path("database/migration_wealth_core_phase1.sql").read_text(
            encoding="utf-8"
        ).lower()
        phase3 = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        self.assertIn("wealth_portfolios_user_id_id_uidx", phase1)
        self.assertIn("wealth_portfolio_snapshots_portfolio_owner_fkey", phase3)

    def test_does_not_touch_nabi_tables(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        for token in (
            "investment_candidates",
            "scan_runs",
            "participation_assessment_snapshots",
        ):
            self.assertNotIn(token, sql)


class WealthTimelineUiTests(unittest.TestCase):
    PAGE = Path("pages/10_Wealth.py")

    def test_explicit_snapshot_button_only(self) -> None:
        source = self.PAGE.read_text(encoding="utf-8")
        self.assertIn("Anlık görüntü kaydet", source)
        self.assertEqual(source.count("save_snapshot_from_view"), 1)
        button_idx = source.index("Anlık görüntü kaydet")
        save_idx = source.index("save_snapshot_from_view")
        self.assertLess(button_idx, save_idx)


if __name__ == "__main__":
    unittest.main()
