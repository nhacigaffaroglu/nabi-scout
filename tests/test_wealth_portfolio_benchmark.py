import inspect
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

from services.wealth_benchmark_service import (
    WealthBenchmarkService,
    align_price_for_snapshot,
    align_price_on_or_before,
    alignment_cutoff_date,
)
from services.fund_analysis_contract import PricePoint, PriceSeries
from services.fund_performance_service import normalize_price_points
from services.wealth_performance_engine import (
    TimedCashFlow,
    aggregate_cash_flows,
    build_performance_period,
    collect_timed_external_flows,
    modified_dietz_denominator,
    snapshot_view_from_row,
)
from services.wealth_portfolio_return_engine import (
    build_linked_performance,
    build_portfolio_index_series,
    chain_linked_return_pct,
    compute_subperiod_return_decimal,
    compute_subperiod_return_for_period,
)
from services.wealth_comparison_chart import (
    BENCHMARK_SERIES_LABEL,
    PORTFOLIO_SERIES_LABEL,
    build_benchmark_comparison_altair_chart,
    build_benchmark_comparison_chart_frame,
)
from services.wealth_timeline_contract import (
    NormalizedSeriesPoint,
    PortfolioLinkedPerformance,
    PortfolioSnapshotView,
)
from services.wealth_timeline_service import WealthTimelineService


def _snapshot(
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


class ModifiedDietzAuditTests(unittest.TestCase):
    def _period_bounds(self) -> tuple[datetime, datetime]:
        return (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

    def test_early_deposit_differs_from_late_deposit(self) -> None:
        start = _snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=1000.0,
        )
        end = _snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=2100.0,
        )
        early_txns = [
            {
                "id": "t1",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 1000,
                "currency": "USD",
                "executed_at": "2026-01-01T00:01:00+00:00",
            }
        ]
        late_txns = [
            {
                "id": "t1",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 1000,
                "currency": "USD",
                "executed_at": "2026-02-01T00:00:00+00:00",
            }
        ]
        early_period = build_performance_period(
            start=start,
            end=end,
            transactions=early_txns,
            account_ids={"acc-1"},
        )
        late_period = build_performance_period(
            start=start,
            end=end,
            transactions=late_txns,
            account_ids={"acc-1"},
        )
        early = compute_subperiod_return_for_period(
            early_period,
            transactions=early_txns,
            account_ids={"acc-1"},
        )
        late = compute_subperiod_return_for_period(
            late_period,
            transactions=late_txns,
            account_ids={"acc-1"},
        )
        assert early is not None and late is not None
        self.assertAlmostEqual(early * 100.0, 5.0, places=3)
        self.assertAlmostEqual(late * 100.0, 10.0, places=3)
        self.assertNotAlmostEqual(early, late)

    def test_flow_at_t1_excluded_flow_at_t2_included_with_zero_weight(self) -> None:
        period_start, period_end = self._period_bounds()
        flows_at_t2 = collect_timed_external_flows(
            [
                {
                    "id": "t1",
                    "account_id": "acc-1",
                    "txn_type": "deposit",
                    "amount": 1000,
                    "currency": "USD",
                    "executed_at": "2026-02-01T00:00:00+00:00",
                }
            ],
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=period_start,
            period_end=period_end,
        )
        self.assertEqual(len(flows_at_t2), 1)
        denominator = modified_dietz_denominator(
            start_value=1000.0,
            timed_flows=flows_at_t2,
            period_start=period_start,
            period_end=period_end,
        )
        self.assertAlmostEqual(denominator, 1000.0)

        flows_at_t1 = collect_timed_external_flows(
            [
                {
                    "id": "t1",
                    "account_id": "acc-1",
                    "txn_type": "deposit",
                    "amount": 1000,
                    "currency": "USD",
                    "executed_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=period_start,
            period_end=period_end,
        )
        self.assertEqual(len(flows_at_t1), 0)

    def test_multiple_deposits_and_withdrawals(self) -> None:
        period_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        period_end = datetime(2026, 1, 11, tzinfo=timezone.utc)
        flows = collect_timed_external_flows(
            [
                {
                    "id": "d1",
                    "account_id": "acc-1",
                    "txn_type": "deposit",
                    "amount": 100,
                    "currency": "USD",
                    "executed_at": "2026-01-02T00:00:00+00:00",
                },
                {
                    "id": "d2",
                    "account_id": "acc-1",
                    "txn_type": "deposit",
                    "amount": 200,
                    "currency": "USD",
                    "executed_at": "2026-01-08T00:00:00+00:00",
                },
                {
                    "id": "w1",
                    "account_id": "acc-1",
                    "txn_type": "withdraw",
                    "amount": 50,
                    "currency": "USD",
                    "executed_at": "2026-01-05T00:00:00+00:00",
                },
            ],
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=period_start,
            period_end=period_end,
        )
        net = sum(flow.signed_amount for flow in flows)
        self.assertAlmostEqual(net, 250.0)
        denominator = modified_dietz_denominator(
            start_value=1000.0,
            timed_flows=flows,
            period_start=period_start,
            period_end=period_end,
        )
        assert denominator is not None
        self.assertGreater(denominator, 1000.0)

    def test_zero_start_value_without_flows_returns_none(self) -> None:
        result = compute_subperiod_return_decimal(
            start_value=0.0,
            end_value=100.0,
            net_external_flow=0.0,
        )
        self.assertIsNone(result)

    def test_negative_denominator_fail_closed(self) -> None:
        period_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        period_end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        flows = [
            TimedCashFlow(
                executed_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
                signed_amount=-2000.0,
            )
        ]
        denominator = modified_dietz_denominator(
            start_value=1000.0,
            timed_flows=flows,
            period_start=period_start,
            period_end=period_end,
        )
        assert denominator is not None
        self.assertLessEqual(denominator, 0.0)
        result = compute_subperiod_return_decimal(
            start_value=1000.0,
            end_value=500.0,
            net_external_flow=-2000.0,
            timed_flows=flows,
            period_start=period_start,
            period_end=period_end,
        )
        self.assertIsNone(result)


class PortfolioReturnEngineTests(unittest.TestCase):
    def test_deposit_does_not_inflate_return(self) -> None:
        start = _snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=1000.0,
        )
        end = _snapshot(
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
        subperiod = compute_subperiod_return_for_period(
            period,
            transactions=txns,
            account_ids={"acc-1"},
        )
        assert subperiod is not None
        naive_return_pct = ((period.end_priced_value / period.start_priced_value) - 1.0) * 100.0
        self.assertAlmostEqual(naive_return_pct, 60.0)
        self.assertAlmostEqual(period.investment_gain, 100.0)
        self.assertNotAlmostEqual(subperiod * 100.0, naive_return_pct)
        self.assertIsNone(period.simple_period_return_pct)

    def test_withdrawal_does_not_create_fake_loss(self) -> None:
        start = _snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=2000.0,
        )
        end = _snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=1600.0,
        )
        txns = [
            {
                "id": "t1",
                "account_id": "acc-1",
                "txn_type": "withdraw",
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
        subperiod = compute_subperiod_return_for_period(
            period,
            transactions=txns,
            account_ids={"acc-1"},
        )
        assert subperiod is not None
        naive_return_pct = ((period.end_priced_value / period.start_priced_value) - 1.0) * 100.0
        self.assertAlmostEqual(naive_return_pct, -20.0)
        self.assertAlmostEqual(period.investment_gain, 100.0)
        self.assertGreater(subperiod, 0.0)

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

    def test_dividend_and_fee_semantics(self) -> None:
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
        _, _, dividend, fee, _ = aggregate_cash_flows(
            txns,
            account_ids={"acc-1"},
            base_currency="USD",
            period_start=start,
            period_end=end,
        )
        self.assertEqual(dividend, 50.0)
        self.assertEqual(fee, 10.0)

    def test_reversal_as_of_semantics(self) -> None:
        start = _snapshot(
            snap_id="s1",
            captured_at="2026-01-01T00:00:00+00:00",
            value=1000.0,
        )
        end = _snapshot(
            snap_id="s2",
            captured_at="2026-02-01T00:00:00+00:00",
            value=1100.0,
        )
        txns = [
            {
                "id": "t1",
                "account_id": "acc-1",
                "txn_type": "deposit",
                "amount": 1000,
                "currency": "USD",
                "executed_at": "2026-01-10T00:00:00+00:00",
            },
            {
                "id": "t2",
                "account_id": "acc-1",
                "txn_type": "withdraw",
                "amount": 1000,
                "currency": "USD",
                "executed_at": "2026-03-01T00:00:00+00:00",
                "reversal_of_id": "t1",
            },
        ]
        period = build_performance_period(
            start=start,
            end=end,
            transactions=txns,
            account_ids={"acc-1"},
        )
        self.assertAlmostEqual(period.net_external_flow, 1000.0)

    def test_txn_in_period_boundaries(self) -> None:
        from services.wealth_performance_engine import _txn_in_period

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        self.assertFalse(_txn_in_period(start, period_start=start, period_end=end))
        self.assertTrue(
            _txn_in_period(
                datetime(2026, 1, 2, tzinfo=timezone.utc),
                period_start=start,
                period_end=end,
            )
        )
        self.assertTrue(_txn_in_period(end, period_start=start, period_end=end))

    def test_chained_multi_subperiod_return(self) -> None:
        snaps = [
            _snapshot(
                snap_id="s1",
                captured_at="2026-01-01T00:00:00+00:00",
                value=1000.0,
            ),
            _snapshot(
                snap_id="s2",
                captured_at="2026-02-01T00:00:00+00:00",
                value=1100.0,
            ),
            _snapshot(
                snap_id="s3",
                captured_at="2026-03-01T00:00:00+00:00",
                value=1210.0,
            ),
        ]
        linked = build_linked_performance(
            snapshots_chronological=snaps,
            transactions=[],
            account_ids={"acc-1"},
            transaction_history_complete=True,
        )
        assert linked is not None
        self.assertTrue(linked.performance_comparable)
        self.assertAlmostEqual(linked.linked_return_pct, 21.0)

    def test_chain_link_identities(self) -> None:
        self.assertAlmostEqual(chain_linked_return_pct([0.10, 0.10]), 21.0)
        self.assertAlmostEqual(chain_linked_return_pct([0.10, -0.10]), -1.0)
        self.assertAlmostEqual(chain_linked_return_pct([-0.50, 1.00]), 0.0)

    def test_invalid_subperiod_fails_entire_chain(self) -> None:
        snaps = [
            _snapshot(
                snap_id="s1",
                captured_at="2026-01-01T00:00:00+00:00",
                value=1000.0,
            ),
            _snapshot(
                snap_id="s2",
                captured_at="2026-02-01T00:00:00+00:00",
                value=1100.0,
                coverage=50.0,
                unpriced=1,
            ),
            _snapshot(
                snap_id="s3",
                captured_at="2026-03-01T00:00:00+00:00",
                value=1210.0,
            ),
        ]
        linked = build_linked_performance(
            snapshots_chronological=snaps,
            transactions=[],
            account_ids={"acc-1"},
            transaction_history_complete=True,
        )
        assert linked is not None
        self.assertFalse(linked.performance_comparable)
        self.assertIsNone(linked.linked_return_pct)

    def test_normalized_index_matches_linked_return(self) -> None:
        snaps = [
            _snapshot(
                snap_id="s1",
                captured_at="2026-01-01T00:00:00+00:00",
                value=1000.0,
            ),
            _snapshot(
                snap_id="s2",
                captured_at="2026-02-01T00:00:00+00:00",
                value=1100.0,
            ),
            _snapshot(
                snap_id="s3",
                captured_at="2026-03-01T00:00:00+00:00",
                value=1210.0,
            ),
        ]
        linked = build_linked_performance(
            snapshots_chronological=snaps,
            transactions=[],
            account_ids={"acc-1"},
            transaction_history_complete=True,
        )
        assert linked is not None and linked.linked_return_pct is not None
        index_series = build_portfolio_index_series(
            snapshots_chronological=snaps,
            linked=linked,
            transactions=[],
            account_ids={"acc-1"},
        )
        self.assertAlmostEqual(index_series[0][1], 100.0)
        self.assertAlmostEqual(index_series[-1][1], 121.0)
        self.assertAlmostEqual(
            linked.linked_return_pct,
            (index_series[-1][1] / index_series[0][1] - 1.0) * 100.0,
        )

    def test_partial_snapshot_not_comparable(self) -> None:
        snaps = [
            _snapshot(
                snap_id="s1",
                captured_at="2026-01-01T00:00:00+00:00",
                value=1000.0,
                coverage=50.0,
                unpriced=1,
            ),
            _snapshot(
                snap_id="s2",
                captured_at="2026-02-01T00:00:00+00:00",
                value=1100.0,
            ),
        ]
        linked = build_linked_performance(
            snapshots_chronological=snaps,
            transactions=[],
            account_ids={"acc-1"},
            transaction_history_complete=True,
        )
        assert linked is not None
        self.assertFalse(linked.performance_comparable)

    def test_mixed_currency_not_comparable(self) -> None:
        snaps = [
            _snapshot(
                snap_id="s1",
                captured_at="2026-01-01T00:00:00+00:00",
                value=1000.0,
                mixed=True,
            ),
            _snapshot(
                snap_id="s2",
                captured_at="2026-02-01T00:00:00+00:00",
                value=1100.0,
            ),
        ]
        linked = build_linked_performance(
            snapshots_chronological=snaps,
            transactions=[],
            account_ids={"acc-1"},
            transaction_history_complete=True,
        )
        assert linked is not None
        self.assertFalse(linked.performance_comparable)

    def test_truncated_history_not_comparable(self) -> None:
        snaps = [
            _snapshot(
                snap_id="s1",
                captured_at="2026-01-01T00:00:00+00:00",
                value=1000.0,
            ),
            _snapshot(
                snap_id="s2",
                captured_at="2026-02-01T00:00:00+00:00",
                value=1100.0,
            ),
        ]
        linked = build_linked_performance(
            snapshots_chronological=snaps,
            transactions=[],
            account_ids={"acc-1"},
            transaction_history_complete=False,
        )
        assert linked is not None
        self.assertFalse(linked.performance_comparable)


class BenchmarkServiceTests(unittest.TestCase):
    def _series(self, rows: list[tuple[str, float]]) -> PriceSeries:
        return PriceSeries(
            symbol="SPY",
            points=tuple(PricePoint(date=date.fromisoformat(d), close=p) for d, p in rows),
            source="fixture",
            last_observation_date=date.fromisoformat(rows[-1][0]),
            warnings=tuple(),
        )

    def test_pre_market_close_snapshot_avoids_same_day_close(self) -> None:
        series = self._series(
            [
                ("2026-01-14", 100.0),
                ("2026-01-15", 110.0),
            ]
        )
        pre_close = align_price_for_snapshot(
            series,
            "2026-01-15T14:00:00+00:00",
        )
        post_close = align_price_for_snapshot(
            series,
            "2026-01-15T22:00:00+00:00",
        )
        self.assertAlmostEqual(pre_close, 100.0)
        self.assertAlmostEqual(post_close, 110.0)

    def test_weekend_snapshot_uses_prior_trading_day(self) -> None:
        series = self._series(
            [
                ("2026-01-16", 100.0),
            ]
        )
        aligned = align_price_for_snapshot(
            series,
            "2026-01-17T12:00:00+00:00",
        )
        self.assertAlmostEqual(aligned, 100.0)

    def test_alignment_cutoff_utc_midnight(self) -> None:
        midnight = datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(alignment_cutoff_date(midnight), date(2026, 1, 14))

    def test_unsorted_provider_data_normalized(self) -> None:
        rows = normalize_price_points(
            "SPY",
            [
                {"date": "2026-01-03", "price": 103},
                {"date": "2026-01-01", "price": 100},
                {"date": "2026-01-02", "price": 101},
            ],
        )
        self.assertEqual(rows.points[0].close, 100.0)
        self.assertEqual(rows.points[-1].close, 103.0)

    def test_duplicate_provider_dates_deduped(self) -> None:
        rows = normalize_price_points(
            "SPY",
            [
                {"date": "2026-01-01", "price": 100},
                {"date": "2026-01-01", "price": 105},
            ],
        )
        self.assertEqual(len(rows.points), 1)
        self.assertEqual(rows.points[0].close, 105.0)

    def test_align_on_or_before_no_lookahead(self) -> None:
        series = self._series(
            [
                ("2026-01-01", 100.0),
                ("2026-01-02", 101.0),
                ("2026-01-05", 102.0),
            ]
        )
        self.assertAlmostEqual(
            align_price_on_or_before(series, date(2026, 1, 3)),
            101.0,
        )
        self.assertIsNone(align_price_on_or_before(series, date(2025, 12, 31)))

    def test_benchmark_normalization_to_100(self) -> None:
        fmp = MagicMock()
        fmp.historical_price_eod_light.return_value = [
            {"date": "2026-01-01", "price": 400.0},
            {"date": "2026-02-01", "price": 440.0},
        ]
        service = WealthBenchmarkService(fmp)
        linked = PortfolioLinkedPerformance(
            period_start_at="2026-01-01T00:00:00+00:00",
            period_end_at="2026-02-01T00:00:00+00:00",
            base_currency="USD",
            subperiod_count=1,
            linked_return_pct=10.0,
            performance_comparable=True,
            warnings=[],
            subperiods=[],
        )
        snaps = [
            _snapshot(
                snap_id="s1",
                captured_at="2026-01-01T22:00:00+00:00",
                value=1000.0,
            ),
            _snapshot(
                snap_id="s2",
                captured_at="2026-02-01T22:00:00+00:00",
                value=1100.0,
            ),
        ]
        portfolio_index = build_portfolio_index_series(
            snapshots_chronological=snaps,
            linked=linked,
            transactions=[],
            account_ids={"acc-1"},
        )
        view = service.build_spy_comparison(
            snapshot_dates=[snap.captured_at for snap in snaps],
            portfolio_index_series=portfolio_index,
            portfolio_return_pct=10.0,
            performance_comparable=True,
            base_currency="USD",
        )
        self.assertTrue(view.performance_comparable)
        self.assertAlmostEqual(view.portfolio_normalized[0].benchmark_index, 100.0)
        self.assertAlmostEqual(view.portfolio_normalized[1].benchmark_index, 110.0)
        self.assertAlmostEqual(view.benchmark_return_pct, 10.0)
        self.assertAlmostEqual(view.relative_return_pct, 0.0)
        self.assertEqual(service.fetch_count, 1)

    def test_missing_benchmark_price_not_comparable(self) -> None:
        fmp = MagicMock()
        fmp.historical_price_eod_light.return_value = [
            {"date": "2026-02-01", "price": 440.0},
        ]
        service = WealthBenchmarkService(fmp)
        view = service.build_spy_comparison(
            snapshot_dates=[
                "2026-01-01T22:00:00+00:00",
                "2026-02-01T22:00:00+00:00",
            ],
            portfolio_index_series=[
                ("2026-01-01T22:00:00+00:00", 100.0),
                ("2026-02-01T22:00:00+00:00", 110.0),
            ],
            portfolio_return_pct=10.0,
            performance_comparable=True,
            base_currency="USD",
        )
        self.assertFalse(view.performance_comparable)

    def test_provider_failure_graceful(self) -> None:
        from services.fmp_client import FMPError

        fmp = MagicMock()
        fmp.historical_price_eod_light.side_effect = FMPError("down")
        service = WealthBenchmarkService(fmp)
        view = service.build_spy_comparison(
            snapshot_dates=[
                "2026-01-01T22:00:00+00:00",
                "2026-02-01T22:00:00+00:00",
            ],
            portfolio_index_series=[
                ("2026-01-01T22:00:00+00:00", 100.0),
                ("2026-02-01T22:00:00+00:00", 110.0),
            ],
            portfolio_return_pct=10.0,
            performance_comparable=True,
            base_currency="USD",
        )
        self.assertFalse(view.performance_comparable)
        self.assertTrue(view.warnings)

    def test_provider_call_dedupe(self) -> None:
        fmp = MagicMock()
        fmp.historical_price_eod_light.return_value = [
            {"date": "2026-01-01", "price": 400.0},
            {"date": "2026-02-01", "price": 440.0},
        ]
        service = WealthBenchmarkService(fmp)
        service.fetch_historical_range("SPY", date(2026, 1, 1), date(2026, 2, 1))
        service.fetch_historical_range("SPY", date(2026, 1, 1), date(2026, 2, 1))
        self.assertEqual(service.fetch_count, 1)
        self.assertEqual(fmp.historical_price_eod_light.call_count, 1)


class WealthPerformanceIntegrationTests(unittest.TestCase):
    def test_portfolio_history_read_zero_provider_calls(self) -> None:
        wealth = MagicMock()
        wealth.user_id = "user-a"
        wealth.list_liabilities.return_value = []
        wealth.list_accounts.return_value = [{"id": "acc-1", "portfolio_id": "pf-1"}]
        wealth.transactions.list_for_user.return_value = []
        wealth.portfolios.list_for_user.return_value = [{"id": "pf-1"}]

        timeline = WealthTimelineService(wealth)
        timeline.snapshots = MagicMock()
        timeline.snapshots.list_for_portfolio.return_value = [
            {
                "id": "s2",
                "user_id": "user-a",
                "portfolio_id": "pf-1",
                "captured_at": "2026-02-01T00:00:00+00:00",
                "base_currency": "USD",
                "priced_market_value": 1100.0,
                "total_cost_basis": 1100.0,
                "unrealized_pl": 0,
                "cash_value": 0,
                "invested_value": 1100.0,
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
                "priced_market_value": 1000.0,
                "total_cost_basis": 1000.0,
                "unrealized_pl": 0,
                "cash_value": 0,
                "invested_value": 1000.0,
                "liabilities_total": None,
                "net_wealth_partial": None,
                "priced_position_coverage_pct": 100.0,
                "unpriced_position_count": 0,
                "mixed_currency_warning": False,
                "valuation_payload": {},
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        ]

        fmp = MagicMock()
        view = timeline.build_performance_view({"id": "pf-1", "name": "Main", "base_currency": "USD"})
        self.assertEqual(len(view.history_points), 2)
        self.assertIsNotNone(view.linked_performance)
        fmp.historical_price_eod_light.assert_not_called()

    def test_benchmark_modules_do_not_import_nabi(self) -> None:
        import services.wealth_benchmark_service as benchmark_module
        import services.wealth_portfolio_return_engine as return_module

        for module in (benchmark_module, return_module):
            source = inspect.getsource(module)
            lowered = source.lower()
            self.assertNotIn("nabi_score", lowered)
            self.assertNotIn("participation", lowered)
            self.assertNotIn("decision", lowered)


class BenchmarkComparisonChartTests(unittest.TestCase):
    def _points(
        self,
        portfolio_values: list[float],
        benchmark_values: list[float],
    ) -> list[NormalizedSeriesPoint]:
        timestamps = [
            "2026-08-01T10:00:00+00:00",
            "2026-08-13T15:00:00+00:00",
        ][: len(portfolio_values)]
        return [
            NormalizedSeriesPoint(
                label_date=timestamps[index],
                portfolio_index=portfolio_values[index],
                benchmark_index=benchmark_values[index],
            )
            for index in range(len(portfolio_values))
        ]

    def test_flat_comparison_chart_values_near_100(self) -> None:
        frame = build_benchmark_comparison_chart_frame(
            self._points([100.0, 100.0], [100.0, 100.0]),
        )
        self.assertListEqual(list(frame.columns), ["timestamp", "Portföy", "SPY"])
        self.assertTrue(frame["Portföy"].between(95, 105).all())
        self.assertTrue(frame["SPY"].between(95, 105).all())
        self.assertFalse(frame["timestamp"].dtype == object)

    def test_positive_movement_chart_values(self) -> None:
        frame = build_benchmark_comparison_chart_frame(
            self._points([100.0, 105.0], [100.0, 102.0]),
        )
        self.assertAlmostEqual(frame["Portföy"].iloc[-1], 105.0)
        self.assertAlmostEqual(frame["SPY"].iloc[-1], 102.0)

    def test_negative_movement_chart_values(self) -> None:
        frame = build_benchmark_comparison_chart_frame(
            self._points([100.0, 95.0], [100.0, 98.0]),
        )
        self.assertAlmostEqual(frame["Portföy"].iloc[-1], 95.0)
        self.assertAlmostEqual(frame["SPY"].iloc[-1], 98.0)

    def test_timestamp_is_x_dimension_not_y_value(self) -> None:
        frame = build_benchmark_comparison_chart_frame(
            self._points([100.0, 105.0], [100.0, 102.0]),
        )
        self.assertIn("timestamp", frame.columns)
        self.assertNotIn("timestamp", [PORTFOLIO_SERIES_LABEL, BENCHMARK_SERIES_LABEL])
        chart = build_benchmark_comparison_altair_chart(frame)
        spec = chart.to_dict()
        self.assertEqual(spec["encoding"]["x"]["field"], "timestamp")
        self.assertEqual(spec["encoding"]["y"]["field"], "Normalize endeks")
        self.assertFalse(spec["encoding"]["y"]["scale"].get("zero", True))

    def test_display_series_labels(self) -> None:
        frame = build_benchmark_comparison_chart_frame(
            self._points([100.0, 100.0], [100.0, 100.0]),
        )
        self.assertEqual(PORTFOLIO_SERIES_LABEL, "Portföy")
        self.assertEqual(BENCHMARK_SERIES_LABEL, "SPY")
        chart = build_benchmark_comparison_altair_chart(frame)
        color_scale = chart.to_dict()["encoding"]["color"]["scale"]
        self.assertEqual(color_scale["domain"], ["Portföy", "SPY"])

    def test_missing_normalized_values_fail_closed(self) -> None:
        points = [
            NormalizedSeriesPoint(
                label_date="2026-08-01T10:00:00+00:00",
                portfolio_index=None,
                benchmark_index=100.0,
            )
        ]
        with self.assertRaises(ValueError):
            build_benchmark_comparison_chart_frame(points)


if __name__ == "__main__":
    unittest.main()
