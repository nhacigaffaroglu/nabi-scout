import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from services.nabi_intelligence_facade import InvestmentIntelligenceView
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_diagnostics_contract import (
    DiagnosticCategory,
    DiagnosticConfidence,
    DiagnosticSeverity,
)
from services.wealth_diagnostics_engine import (
    ASSET_CLASS_HIGH_PCT,
    ASSET_CLASS_WATCH_PCT,
    BENCHMARK_LAG_WATCH_PP,
    CASH_HIGH_PCT,
    CASH_WATCH_PCT,
    EFFECTIVE_COUNT_HIGH,
    EFFECTIVE_COUNT_WATCH,
    SINGLE_POSITION_HIGH_PCT,
    SINGLE_POSITION_WATCH_PCT,
    TOP3_HIGH_PCT,
    TOP3_WATCH_PCT,
    _severity_for_threshold,
    build_benchmark_diagnostics,
    build_cash_diagnostics,
    build_concentration_diagnostics,
    build_diversification_diagnostics,
    build_drawdown_diagnostics,
    build_nabi_context_diagnostics,
    build_pl_structure_diagnostics,
    build_portfolio_diagnostics,
    effective_position_count,
)
from services.wealth_diagnostics_service import WealthDiagnosticsService
from services.wealth_timeline_contract import (
    BenchmarkComparisonView,
    NormalizedSeriesPoint,
    PortfolioHistoryPoint,
    PortfolioLinkedPerformance,
    WealthPerformanceView,
)


def _position(
    *,
    symbol: str,
    weight_pct: float,
    market_value: float,
    unrealized_pl: float = 0.0,
    is_cash: bool = False,
    asset_class: str = "equity",
    nabi=None,
) -> PositionValuationRow:
    return PositionValuationRow(
        position_id=f"p-{symbol}",
        account_id="a1",
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class=asset_class,
        account_name="Broker",
        quantity=1,
        average_cost=market_value,
        valuation_currency="USD",
        price=market_value,
        price_available=True,
        market_value=market_value,
        cost_basis=market_value - unrealized_pl,
        unrealized_pl=unrealized_pl,
        weight_pct=weight_pct,
        is_cash=is_cash,
        included_in_base_totals=True,
        nabi=nabi,
    )


def _view(
    *,
    positions: list[PositionValuationRow],
    health: PortfolioHealthMetrics,
    unpriced: int = 0,
    mixed: bool = False,
    foreign: int = 0,
    unpriced_positions: list | None = None,
    foreign_positions: list | None = None,
) -> PortfolioIntelligenceView:
    priced_total = sum(row.market_value or 0.0 for row in positions)
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=priced_total,
        priced_total_cost_basis=priced_total,
        priced_total_unrealized_pl=0.0,
        priced_position_count=len(positions),
        unpriced_position_count=unpriced,
        foreign_currency_position_count=foreign,
        total_position_count=len(positions) + unpriced,
        mixed_currency_warning=mixed,
        fx_supported=False,
        priced_positions=positions,
        unpriced_positions=unpriced_positions or [],
        foreign_currency_positions=foreign_positions or [],
        asset_class_allocation=[
            AllocationSlice(key="equity", label="equity", market_value=priced_total, weight_pct=100.0)
        ],
        account_allocation=[],
        health=health,
        valuation_errors=[],
        price_provider="fmp",
        unique_price_symbols_fetched=0,
    )


class WealthDiagnosticsEngineTests(unittest.TestCase):
    def test_single_position_concentration_high(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=45.0, market_value=4500)],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=45.0,
                top3_concentration_pct=45.0,
                largest_asset_class_concentration_pct=45.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        codes = [item.code for item in build_concentration_diagnostics(view)]
        self.assertIn("CONCENTRATION_SINGLE_HIGH", codes)

    def test_single_position_concentration_watch(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=30.0, market_value=3000)],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=30.0,
                top3_concentration_pct=30.0,
                largest_asset_class_concentration_pct=30.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        codes = [item.code for item in build_concentration_diagnostics(view)]
        self.assertIn("CONCENTRATION_SINGLE_WATCH", codes)
        self.assertNotIn("CONCENTRATION_SINGLE_HIGH", codes)

    def test_top3_and_asset_class_concentration(self) -> None:
        view = _view(
            positions=[
                _position(symbol="A", weight_pct=30.0, market_value=3000),
                _position(symbol="B", weight_pct=28.0, market_value=2800),
                _position(symbol="C", weight_pct=27.0, market_value=2700),
            ],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=30.0,
                top3_concentration_pct=85.0,
                largest_asset_class_concentration_pct=85.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        codes = [item.code for item in build_concentration_diagnostics(view)]
        self.assertIn("CONCENTRATION_TOP3_HIGH", codes)
        self.assertIn("CONCENTRATION_ASSET_CLASS_HIGH", codes)

    def test_effective_position_count_math(self) -> None:
        view = _view(
            positions=[
                _position(symbol="A", weight_pct=50.0, market_value=5000),
                _position(symbol="B", weight_pct=50.0, market_value=5000),
            ],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=50.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        self.assertAlmostEqual(effective_position_count(view), 2.0)

    def test_cash_exposure_high(self) -> None:
        view = _view(
            positions=[_position(symbol="CASH", weight_pct=85.0, market_value=8500, is_cash=True, asset_class="cash")],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=85.0,
                top3_concentration_pct=85.0,
                largest_asset_class_concentration_pct=85.0,
                cash_pct=85.0,
                invested_pct=15.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        codes = [item.code for item in build_diversification_diagnostics(view)]
        self.assertIn("DIVERSIFICATION_EFFECTIVE_LOW", codes)
        result = build_portfolio_diagnostics(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=view,
        )
        cash_codes = [
            item.code
            for item in result.diagnostics
            if item.category == DiagnosticCategory.CASH
        ]
        self.assertIn("CASH_WEIGHT_HIGH", cash_codes)

    def test_pl_structure_counts(self) -> None:
        view = _view(
            positions=[
                _position(symbol="WIN", weight_pct=40.0, market_value=4000, unrealized_pl=200),
                _position(symbol="LOSS", weight_pct=35.0, market_value=3500, unrealized_pl=-150),
                _position(symbol="FLAT", weight_pct=25.0, market_value=2500, unrealized_pl=0),
            ],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=40.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        diagnostics = build_pl_structure_diagnostics(view)
        structure = next(item for item in diagnostics if item.code == "PERFORMANCE_PL_STRUCTURE")
        self.assertEqual(structure.evidence["profitable_position_count"], 1)
        self.assertEqual(structure.evidence["losing_position_count"], 1)
        self.assertEqual(structure.evidence["flat_position_count"], 1)

    def test_performance_index_drawdown(self) -> None:
        diagnostics = build_drawdown_diagnostics(
            history_points=[],
            performance_index_points=[
                ("t1", 100.0),
                ("t2", 110.0),
                ("t3", 88.0),
            ],
            comparable_performance=True,
        )
        drawdown = next(item for item in diagnostics if item.code == "DRAWDOWN_PERFORMANCE")
        self.assertLess(drawdown.evidence["max_observed_drawdown_pct"], 0.0)

    def test_raw_snapshot_drawdown_labeled(self) -> None:
        diagnostics = build_drawdown_diagnostics(
            history_points=[
                PortfolioHistoryPoint(
                    captured_at="t1",
                    priced_market_value=1000.0,
                    base_currency="USD",
                    is_partial=False,
                    partial_reasons=[],
                ),
                PortfolioHistoryPoint(
                    captured_at="t2",
                    priced_market_value=900.0,
                    base_currency="USD",
                    is_partial=False,
                    partial_reasons=[],
                ),
            ],
            performance_index_points=None,
            comparable_performance=False,
        )
        raw = next(item for item in diagnostics if item.code == "DRAWDOWN_RAW_SNAPSHOT")
        self.assertEqual(raw.evidence["drawdown_kind"], "raw_recorded_value")

    def test_benchmark_lag_diagnostic(self) -> None:
        benchmark = BenchmarkComparisonView(
            benchmark_symbol="SPY",
            portfolio_normalized=[],
            portfolio_return_pct=0.0,
            benchmark_return_pct=12.0,
            relative_return_pct=-12.0,
            performance_comparable=True,
            warnings=[],
            provider_fetch_count=1,
        )
        codes = [item.code for item in build_benchmark_diagnostics(benchmark)]
        self.assertIn("BENCHMARK_LAG", codes)

    def test_benchmark_unavailable_no_fabrication(self) -> None:
        self.assertEqual(build_benchmark_diagnostics(None), [])
        unavailable = BenchmarkComparisonView(
            benchmark_symbol="SPY",
            portfolio_normalized=[],
            portfolio_return_pct=None,
            benchmark_return_pct=None,
            relative_return_pct=None,
            performance_comparable=False,
            warnings=["missing"],
            provider_fetch_count=0,
        )
        self.assertEqual(build_benchmark_diagnostics(unavailable), [])

    def test_missing_price_data_quality(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=75.0,
            ),
            unpriced=1,
            unpriced_positions=[_position(symbol="MSFT", weight_pct=0.0, market_value=0.0)],
        )
        result = build_portfolio_diagnostics(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=view,
        )
        codes = [item.code for item in result.diagnostics]
        self.assertIn("DATA_PRICE_COVERAGE", codes)
        self.assertFalse(result.data_quality_ok)
        self.assertNotIn("CONCENTRATION_SINGLE_HIGH", codes)

    def test_mixed_currency_suppresses_high_confidence_concentration(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=50.0, market_value=5000)],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=50.0,
                top3_concentration_pct=50.0,
                largest_asset_class_concentration_pct=50.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
            mixed=True,
        )
        self.assertEqual(build_concentration_diagnostics(view), [])
        result = build_portfolio_diagnostics(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=view,
        )
        self.assertIn("DATA_MIXED_CURRENCY", [item.code for item in result.diagnostics])

    def test_truncated_history_data_quality(self) -> None:
        result = build_portfolio_diagnostics(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=_view(
                positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
                health=PortfolioHealthMetrics(
                    largest_position_weight_pct=100.0,
                    top3_concentration_pct=100.0,
                    largest_asset_class_concentration_pct=100.0,
                    cash_pct=0.0,
                    invested_pct=100.0,
                    priced_position_coverage_pct=100.0,
                ),
            ),
            transaction_history_complete=False,
        )
        self.assertIn("DATA_TXN_HISTORY_TRUNCATED", [item.code for item in result.diagnostics])

    def test_insufficient_snapshots(self) -> None:
        perf = WealthPerformanceView(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            history_points=[
                PortfolioHistoryPoint(
                    captured_at="t1",
                    priced_market_value=1000.0,
                    base_currency="USD",
                    is_partial=False,
                    partial_reasons=[],
                )
            ],
            linked_performance=None,
        )
        result = build_portfolio_diagnostics(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=_view(
                positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
                health=PortfolioHealthMetrics(
                    largest_position_weight_pct=100.0,
                    top3_concentration_pct=100.0,
                    largest_asset_class_concentration_pct=100.0,
                    cash_pct=0.0,
                    invested_pct=100.0,
                    priced_position_coverage_pct=100.0,
                ),
            ),
            performance_view=perf,
        )
        self.assertIn("DATA_INSUFFICIENT_SNAPSHOTS", [item.code for item in result.diagnostics])

    def test_nabi_context_separate_from_financial(self) -> None:
        nabi = InvestmentIntelligenceView(
            symbol="AAPL",
            market="NASDAQ",
            company_name="Apple",
            decision="WATCH",
            nabi_score=70.0,
            participation_status=None,
            participation_score=None,
            research_status="ready",
            candidate_id="c1",
            has_candidate=True,
            has_participation_snapshot=False,
        )
        view = _view(
            positions=[
                _position(symbol="AAPL", weight_pct=60.0, market_value=6000, nabi=nabi),
                _position(symbol="MSFT", weight_pct=40.0, market_value=4000, nabi=None),
            ],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=60.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        financial_before = len(build_concentration_diagnostics(view))
        nabi_diag = build_nabi_context_diagnostics(view)
        financial_after = len(build_concentration_diagnostics(view))
        self.assertEqual(financial_before, financial_after)
        self.assertTrue(any(item.code == "NABI_COVERAGE" for item in nabi_diag))

    def test_severity_ordering(self) -> None:
        view = _view(
            positions=[
                _position(symbol="CASH", weight_pct=85.0, market_value=8500, is_cash=True, asset_class="cash"),
                _position(symbol="AAPL", weight_pct=15.0, market_value=1500),
            ],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=85.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=85.0,
                cash_pct=85.0,
                invested_pct=15.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        result = build_portfolio_diagnostics(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=view,
        )
        severities = [item.severity for item in result.diagnostics]
        self.assertEqual(severities, sorted(severities, key=lambda s: ["HIGH", "WATCH", "INFO"].index(s.value)))

    def test_stable_diagnostic_codes(self) -> None:
        self.assertEqual(SINGLE_POSITION_HIGH_PCT, 40.0)
        self.assertEqual(SINGLE_POSITION_WATCH_PCT, 25.0)
        self.assertEqual(CASH_HIGH_PCT, 80.0)
        self.assertEqual(ASSET_CLASS_HIGH_PCT, 80.0)
        self.assertEqual(BENCHMARK_LAG_WATCH_PP, -10.0)


class WealthDiagnosticsValidationGateTests(unittest.TestCase):
    """Phase 5 final validation gate regression tests."""

    def _full_health(self, **overrides) -> PortfolioHealthMetrics:
        defaults = dict(
            largest_position_weight_pct=25.0,
            top3_concentration_pct=65.0,
            largest_asset_class_concentration_pct=65.0,
            cash_pct=50.0,
            invested_pct=50.0,
            priced_position_coverage_pct=100.0,
        )
        defaults.update(overrides)
        return PortfolioHealthMetrics(**defaults)

    def _nabi(self, *, decision: str = "WATCH", score: float = 70.0) -> InvestmentIntelligenceView:
        return InvestmentIntelligenceView(
            symbol="X",
            market="NASDAQ",
            company_name="X",
            decision=decision,
            nabi_score=score,
            participation_status=None,
            participation_score=None,
            research_status="ready",
            candidate_id="c1",
            has_candidate=True,
            has_participation_snapshot=False,
        )

    def _financial_diagnostics(self, result):
        return [
            item
            for item in result.diagnostics
            if item.category != DiagnosticCategory.NABI_CONTEXT
        ]

    def test_all_diagnostics_have_structured_evidence(self) -> None:
        view = _view(
            positions=[
                _position(symbol="A", weight_pct=45.0, market_value=4500, unrealized_pl=-100),
                _position(symbol="B", weight_pct=30.0, market_value=3000, unrealized_pl=50),
                _position(symbol="C", weight_pct=25.0, market_value=2500),
            ],
            health=self._full_health(
                largest_position_weight_pct=45.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        benchmark = BenchmarkComparisonView(
            benchmark_symbol="SPY",
            portfolio_normalized=[],
            portfolio_return_pct=0.0,
            benchmark_return_pct=12.0,
            relative_return_pct=-12.0,
            performance_comparable=True,
            warnings=[],
            provider_fetch_count=1,
        )
        result = build_portfolio_diagnostics(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=view,
            performance_view=WealthPerformanceView(
                portfolio_id="pf-1",
                portfolio_name="Main",
                base_currency="USD",
                history_points=[
                    PortfolioHistoryPoint(
                        captured_at="t1",
                        priced_market_value=1000.0,
                        base_currency="USD",
                        is_partial=False,
                        partial_reasons=[],
                    ),
                    PortfolioHistoryPoint(
                        captured_at="t2",
                        priced_market_value=900.0,
                        base_currency="USD",
                        is_partial=False,
                        partial_reasons=[],
                    ),
                ],
                linked_performance=PortfolioLinkedPerformance(
                    period_start_at="t1",
                    period_end_at="t2",
                    base_currency="USD",
                    subperiod_count=1,
                    linked_return_pct=-10.0,
                    performance_comparable=True,
                    warnings=[],
                    subperiods=[],
                ),
            ),
            benchmark_view=benchmark,
            performance_index_points=[("t1", 100.0), ("t2", 90.0)],
        )
        for diagnostic in result.diagnostics:
            self.assertIsInstance(diagnostic.evidence, dict)
            self.assertTrue(diagnostic.evidence, f"{diagnostic.code} lacks evidence")
            self.assertTrue(diagnostic.code)
            self.assertTrue(diagnostic.source)
            self.assertIsNotNone(diagnostic.confidence)

    def test_concentration_partial_data_no_high_confidence_claim(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=self._full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=50.0,
            ),
            unpriced=1,
            unpriced_positions=[_position(symbol="MSFT", weight_pct=0.0, market_value=0.0)],
        )
        self.assertEqual(build_concentration_diagnostics(view), [])

    def test_concentration_single_position_boundaries(self) -> None:
        for pct, expected in [
            (24.99, None),
            (25.0, DiagnosticSeverity.WATCH),
            (39.99, DiagnosticSeverity.WATCH),
            (40.0, DiagnosticSeverity.HIGH),
        ]:
            severity = _severity_for_threshold(
                pct,
                watch=SINGLE_POSITION_WATCH_PCT,
                high=SINGLE_POSITION_HIGH_PCT,
            )
            self.assertEqual(severity, expected, pct)

    def test_concentration_top3_boundaries(self) -> None:
        for pct, expected in [
            (64.99, None),
            (65.0, DiagnosticSeverity.WATCH),
            (79.99, DiagnosticSeverity.WATCH),
            (80.0, DiagnosticSeverity.HIGH),
        ]:
            severity = _severity_for_threshold(
                pct,
                watch=TOP3_WATCH_PCT,
                high=TOP3_HIGH_PCT,
            )
            self.assertEqual(severity, expected, pct)

    def test_concentration_asset_class_boundaries(self) -> None:
        for pct, expected in [
            (64.99, None),
            (65.0, DiagnosticSeverity.WATCH),
            (79.99, DiagnosticSeverity.WATCH),
            (80.0, DiagnosticSeverity.HIGH),
        ]:
            severity = _severity_for_threshold(
                pct,
                watch=ASSET_CLASS_WATCH_PCT,
                high=ASSET_CLASS_HIGH_PCT,
            )
            self.assertEqual(severity, expected, pct)

    def test_effective_position_count_values(self) -> None:
        cases = [
            (1, 1.0),
            (2, 2.0),
            (4, 4.0),
            (10, 10.0),
        ]
        for count, expected in cases:
            weight = 100.0 / count
            positions = [
                _position(
                    symbol=f"S{i}",
                    weight_pct=weight,
                    market_value=weight * 100,
                )
                for i in range(count)
            ]
            view = _view(
                positions=positions,
                health=self._full_health(
                    largest_position_weight_pct=weight,
                    top3_concentration_pct=min(100.0, weight * 3),
                    largest_asset_class_concentration_pct=100.0,
                    cash_pct=0.0,
                    invested_pct=100.0,
                ),
            )
            self.assertAlmostEqual(effective_position_count(view), expected, places=4)

        skewed = _view(
            positions=[
                _position(symbol="BIG", weight_pct=90.0, market_value=9000),
                _position(symbol="SMALL", weight_pct=10.0, market_value=1000),
            ],
            health=self._full_health(
                largest_position_weight_pct=90.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        self.assertAlmostEqual(effective_position_count(skewed), 1.0 / 0.82, places=4)

    def test_effective_count_diversification_boundaries(self) -> None:
        two_equal = _view(
            positions=[
                _position(symbol="A", weight_pct=50.0, market_value=5000),
                _position(symbol="B", weight_pct=50.0, market_value=5000),
            ],
            health=self._full_health(
                largest_position_weight_pct=50.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        two_diag = build_diversification_diagnostics(two_equal)
        self.assertEqual(len(two_diag), 1)
        self.assertEqual(two_diag[0].severity, DiagnosticSeverity.WATCH)
        self.assertEqual(two_diag[0].code, "DIVERSIFICATION_EFFECTIVE_MODERATE")

        four_equal = _view(
            positions=[
                _position(symbol=f"S{i}", weight_pct=25.0, market_value=2500)
                for i in range(4)
            ],
            health=self._full_health(
                largest_position_weight_pct=25.0,
                top3_concentration_pct=75.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        self.assertEqual(build_diversification_diagnostics(four_equal), [])

        single = _view(
            positions=[_position(symbol="ONLY", weight_pct=100.0, market_value=10000)],
            health=self._full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        single_diag = build_diversification_diagnostics(single)
        self.assertEqual(single_diag[0].severity, DiagnosticSeverity.HIGH)
        self.assertLess(single_diag[0].metric_value, EFFECTIVE_COUNT_HIGH)
        self.assertGreaterEqual(two_diag[0].metric_value, EFFECTIVE_COUNT_HIGH)
        self.assertLess(two_diag[0].metric_value, EFFECTIVE_COUNT_WATCH)

    def test_cash_threshold_boundaries(self) -> None:
        for pct, code in [
            (49.99, None),
            (50.0, "CASH_WEIGHT_ELEVATED"),
            (79.99, "CASH_WEIGHT_ELEVATED"),
            (80.0, "CASH_WEIGHT_HIGH"),
        ]:
            view = _view(
                positions=[
                    _position(
                        symbol="CASH",
                        weight_pct=pct,
                        market_value=pct * 100,
                        is_cash=True,
                        asset_class="cash",
                    ),
                    _position(
                        symbol="EQ",
                        weight_pct=100.0 - pct,
                        market_value=(100.0 - pct) * 100,
                    ),
                ],
                health=self._full_health(
                    largest_position_weight_pct=max(pct, 100.0 - pct),
                    top3_concentration_pct=100.0,
                    largest_asset_class_concentration_pct=max(pct, 100.0 - pct),
                    cash_pct=pct,
                    invested_pct=100.0 - pct,
                ),
            )
            codes = [item.code for item in build_cash_diagnostics(view)]
            if code is None:
                self.assertEqual(codes, [], pct)
            else:
                self.assertIn(code, codes, pct)

    def test_pl_breadth_vs_mv_at_loss_not_conflated(self) -> None:
        view = _view(
            positions=[
                _position(symbol="LOSER", weight_pct=90.0, market_value=9000, unrealized_pl=-500),
                _position(symbol="W1", weight_pct=1.0, market_value=100, unrealized_pl=10),
                _position(symbol="W2", weight_pct=1.0, market_value=100, unrealized_pl=10),
                _position(symbol="W3", weight_pct=1.0, market_value=100, unrealized_pl=10),
                _position(symbol="W4", weight_pct=1.0, market_value=100, unrealized_pl=10),
                _position(symbol="W5", weight_pct=1.0, market_value=100, unrealized_pl=10),
                _position(symbol="W6", weight_pct=1.0, market_value=100, unrealized_pl=10),
                _position(symbol="W7", weight_pct=1.0, market_value=100, unrealized_pl=10),
                _position(symbol="W8", weight_pct=1.0, market_value=100, unrealized_pl=10),
                _position(symbol="W9", weight_pct=1.0, market_value=100, unrealized_pl=10),
                _position(symbol="W10", weight_pct=1.0, market_value=100, unrealized_pl=10),
            ],
            health=self._full_health(
                largest_position_weight_pct=90.0,
                top3_concentration_pct=92.0,
                largest_asset_class_concentration_pct=90.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        breadth = next(
            item for item in build_pl_structure_diagnostics(view) if item.code == "UNREALIZED_LOSS_BREADTH"
        )
        self.assertAlmostEqual(breadth.evidence["loss_position_pct"], 9.09, places=1)
        self.assertAlmostEqual(breadth.evidence["loss_market_value_pct"], 90.0, places=1)
        self.assertEqual(breadth.evidence["largest_gain_loss_unit"], "USD")

    def test_performance_drawdown_formulas_and_timestamps(self) -> None:
        cases = [
            (
                [("p1", 100.0), ("p2", 120.0), ("p3", 90.0)],
                -25.0,
                -25.0,
                "p2",
                "p3",
            ),
            (
                [("p1", 100.0), ("p2", 80.0), ("p3", 120.0)],
                0.0,
                -20.0,
                "p1",
                "p2",
            ),
            (
                [("p1", 100.0), ("p2", 120.0), ("p3", 60.0), ("p4", 90.0)],
                -25.0,
                -50.0,
                "p2",
                "p3",
            ),
        ]
        for points, current, maximum, peak_at, trough_at in cases:
            diag = build_drawdown_diagnostics(
                history_points=[],
                performance_index_points=points,
                comparable_performance=True,
            )
            perf = next(item for item in diag if item.code == "DRAWDOWN_PERFORMANCE")
            self.assertAlmostEqual(perf.evidence["current_drawdown_pct"], current, places=4)
            self.assertAlmostEqual(perf.evidence["max_observed_drawdown_pct"], maximum, places=4)
            self.assertEqual(perf.evidence["peak_at"], peak_at)
            self.assertEqual(perf.evidence["trough_at"], trough_at)

    def test_no_performance_drawdown_when_not_comparable(self) -> None:
        diag = build_drawdown_diagnostics(
            history_points=[],
            performance_index_points=[("t1", 100.0), ("t2", 90.0)],
            comparable_performance=False,
        )
        self.assertFalse(any(item.code == "DRAWDOWN_PERFORMANCE" for item in diag))

    def test_benchmark_lag_boundary(self) -> None:
        for relative, expect_lag in [(-9.99, False), (-10.0, True), (-15.0, True)]:
            benchmark = BenchmarkComparisonView(
                benchmark_symbol="SPY",
                portfolio_normalized=[],
                portfolio_return_pct=relative,
                benchmark_return_pct=0.0,
                relative_return_pct=relative,
                performance_comparable=True,
                warnings=[],
                provider_fetch_count=1,
            )
            codes = [item.code for item in build_benchmark_diagnostics(benchmark)]
            self.assertEqual("BENCHMARK_LAG" in codes, expect_lag, relative)
            if expect_lag:
                lag = next(item for item in build_benchmark_diagnostics(benchmark) if item.code == "BENCHMARK_LAG")
                self.assertEqual(lag.severity, DiagnosticSeverity.WATCH)

    def test_nabi_invariance_financial_diagnostics(self) -> None:
        base_positions = [
            _position(symbol="AAPL", weight_pct=60.0, market_value=6000, unrealized_pl=-50),
            _position(symbol="MSFT", weight_pct=40.0, market_value=4000, unrealized_pl=20),
        ]
        health = self._full_health(
            largest_position_weight_pct=60.0,
            top3_concentration_pct=100.0,
            largest_asset_class_concentration_pct=100.0,
            cash_pct=0.0,
            invested_pct=100.0,
        )

        def _build(positions):
            return build_portfolio_diagnostics(
                portfolio_id="pf-1",
                generated_at="2026-08-13T00:00:00+00:00",
                portfolio_view=_view(positions=positions, health=health),
            )

        no_nabi = _build(base_positions)
        high_nabi = _build(
            [
                _position(
                    symbol="AAPL",
                    weight_pct=60.0,
                    market_value=6000,
                    unrealized_pl=-50,
                    nabi=self._nabi(decision="BUY", score=95.0),
                ),
                _position(
                    symbol="MSFT",
                    weight_pct=40.0,
                    market_value=4000,
                    unrealized_pl=20,
                    nabi=self._nabi(decision="BUY", score=92.0),
                ),
            ]
        )
        low_nabi = _build(
            [
                _position(
                    symbol="AAPL",
                    weight_pct=60.0,
                    market_value=6000,
                    unrealized_pl=-50,
                    nabi=self._nabi(decision="AVOID", score=20.0),
                ),
                _position(
                    symbol="MSFT",
                    weight_pct=40.0,
                    market_value=4000,
                    unrealized_pl=20,
                    nabi=self._nabi(decision="AVOID", score=15.0),
                ),
            ]
        )

        def _key(item):
            return (
                item.code,
                item.severity,
                item.confidence,
                item.metric_value,
                tuple(sorted(item.evidence.items())),
            )

        fin_no = [_key(item) for item in self._financial_diagnostics(no_nabi)]
        fin_high = [_key(item) for item in self._financial_diagnostics(high_nabi)]
        fin_low = [_key(item) for item in self._financial_diagnostics(low_nabi)]
        self.assertEqual(fin_no, fin_high)
        self.assertEqual(fin_no, fin_low)
        self.assertTrue(any(item.code == "NABI_COVERAGE" for item in high_nabi.diagnostics))
        self.assertTrue(any(item.code == "NABI_COVERAGE" for item in low_nabi.diagnostics))

    def test_json_serialization_stable(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=self._full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        kwargs = dict(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=view,
        )
        first = json.dumps(build_portfolio_diagnostics(**kwargs).to_dict(), sort_keys=True)
        second = json.dumps(build_portfolio_diagnostics(**kwargs).to_dict(), sort_keys=True)
        self.assertEqual(first, second)
        json.loads(first)

    def test_severity_ordering_stable_across_runs(self) -> None:
        view = _view(
            positions=[
                _position(symbol="CASH", weight_pct=85.0, market_value=8500, is_cash=True, asset_class="cash"),
                _position(symbol="AAPL", weight_pct=15.0, market_value=1500),
            ],
            health=self._full_health(
                largest_position_weight_pct=85.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=85.0,
                cash_pct=85.0,
                invested_pct=15.0,
            ),
        )
        kwargs = dict(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=view,
        )
        codes_a = [item.code for item in build_portfolio_diagnostics(**kwargs).diagnostics]
        codes_b = [item.code for item in build_portfolio_diagnostics(**kwargs).diagnostics]
        self.assertEqual(codes_a, codes_b)

    def test_foreign_currency_suppresses_concentration(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=self._full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
            foreign=1,
            foreign_positions=[_position(symbol="EUR", weight_pct=0.0, market_value=0.0)],
        )
        self.assertEqual(build_concentration_diagnostics(view), [])


class WealthDiagnosticsServiceTests(unittest.TestCase):
    def test_service_reuses_supplied_views_without_fmp(self) -> None:
        wealth = MagicMock()
        wealth.user_id = "user-a"
        wealth.list_accounts.return_value = [{"id": "acc-1", "portfolio_id": "pf-1"}]
        wealth.transactions.list_for_user.return_value = []

        service = WealthDiagnosticsService(wealth)
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        perf = WealthPerformanceView(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            history_points=[],
            linked_performance=None,
        )
        result = service.build_diagnostics_view(
            {"id": "pf-1"},
            view,
            performance_view=perf,
            benchmark_view=None,
            transaction_history_complete=True,
        )
        self.assertEqual(result.portfolio_id, "pf-1")
        self.assertFalse(result.benchmark_available)


class WealthDiagnosticsFirewallTests(unittest.TestCase):
    def test_engine_has_no_provider_or_nabi_imports(self) -> None:
        import services.wealth_diagnostics_engine as engine_module

        source = inspect.getsource(engine_module)
        lowered = source.lower()
        self.assertNotIn("nabi_score", lowered)
        self.assertNotIn("participation_engine", lowered)
        self.assertNotIn("scanner", lowered)
        self.assertNotIn("fmp_client", lowered)
        self.assertNotIn("supabase", lowered)

    def test_no_db_writes_in_service(self) -> None:
        source = inspect.getsource(WealthDiagnosticsService)
        lowered = source.lower()
        self.assertNotIn(".insert(", lowered)
        self.assertNotIn(".update(", lowered)
        self.assertNotIn(".delete(", lowered)


class WealthDiagnosticsUiTests(unittest.TestCase):
    @staticmethod
    def _wealth_page_source() -> str:
        return Path("pages/10_Wealth.py").read_text(encoding="utf-8")

    @staticmethod
    def _render_card_source() -> str:
        source = WealthDiagnosticsUiTests._wealth_page_source()
        start = source.index("def _render_diagnostic_card")
        end = source.index("\nst.title", start)
        return source[start:end]

    @staticmethod
    def _analysis_block() -> str:
        return WealthDiagnosticsUiTests._wealth_page_source().split("with tab_analysis:")[1]

    def test_analiz_tab_present(self) -> None:
        source = self._wealth_page_source()
        self.assertIn('"Analiz"', source)
        self.assertIn("tab_analysis", source)

    def test_no_adviser_language_in_phase5_sections(self) -> None:
        lowered = self._analysis_block().lower()
        banned = [
            "öneriyorum",
            "tavsiye",
            "should buy",
            "should sell",
            "recommend buying",
            "recommend selling",
        ]
        for phrase in banned:
            self.assertNotIn(phrase, lowered)

    def test_default_card_hides_machine_readable_internals(self) -> None:
        render_source = self._render_card_source()
        default_body = render_source.split('with st.expander("Teknik ayrıntılar")')[0]
        self.assertNotIn("st.json(diagnostic.evidence)", default_body)
        self.assertNotIn("Kaynak:", default_body)
        self.assertNotIn("Güven:", default_body)
        self.assertNotIn("Kod:", default_body)

    def test_technical_expander_exposes_contract_fields(self) -> None:
        render_source = self._render_card_source()
        technical_block = render_source.split('with st.expander("Teknik ayrıntılar")')[1]
        for marker in [
            "diagnostic.code",
            "diagnostic.category.value",
            "diagnostic.severity.value",
            "diagnostic.confidence.value",
            "diagnostic.source",
            "diagnostic.metric_value",
            "diagnostic.threshold",
            "st.json(diagnostic.evidence)",
        ]:
            self.assertIn(marker, technical_block, marker)

    def test_nabi_firewall_caption_visible(self) -> None:
        analysis = self._analysis_block()
        self.assertIn(
            "NABI verileri portföy değerleme veya getiri hesaplarını değiştirmez.",
            analysis,
        )

    def test_analiz_does_not_load_benchmark_for_diagnostics(self) -> None:
        analysis = self._analysis_block()
        self.assertIn("benchmark_view=None", analysis)
        self.assertNotIn("WealthBenchmarkService", analysis)

    def test_top3_presentation_adapts_without_changing_contract(self) -> None:
        source = self._wealth_page_source()
        self.assertIn("_display_diagnostic_title", source)
        self.assertIn("CONCENTRATION_TOP3_HIGH", source)
        self.assertIn("diagnostic.title", source)

    def test_portfolio_diagnostic_contract_unchanged(self) -> None:
        import services.wealth_diagnostics_contract as contract_module

        source = inspect.getsource(contract_module.PortfolioDiagnostic)
        for field in [
            "code:",
            "category:",
            "severity:",
            "title:",
            "summary:",
            "evidence:",
            "metric_value:",
            "threshold:",
            "affected_symbols:",
            "confidence:",
            "source:",
            "def to_dict",
        ]:
            self.assertIn(field, source, field)

    def test_to_dict_output_unchanged(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        payload = json.dumps(
            build_portfolio_diagnostics(
                portfolio_id="pf-1",
                generated_at="2026-08-13T00:00:00+00:00",
                portfolio_view=view,
            ).to_dict(),
            sort_keys=True,
        )
        parsed = json.loads(payload)
        self.assertEqual(parsed["portfolio_id"], "pf-1")
        self.assertTrue(parsed["diagnostics"])
        first = parsed["diagnostics"][0]
        self.assertIn("code", first)
        self.assertIn("evidence", first)
        self.assertIn("confidence", first)

    def test_evidence_payload_unchanged_by_ui_layer(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=45.0, market_value=4500)],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=45.0,
                top3_concentration_pct=45.0,
                largest_asset_class_concentration_pct=45.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        diagnostic = build_concentration_diagnostics(view)[0]
        self.assertEqual(diagnostic.code, "CONCENTRATION_SINGLE_HIGH")
        self.assertIn("largest_position_pct", diagnostic.evidence)
        self.assertIn("symbol", diagnostic.evidence)

    def test_diagnostic_ordering_unchanged(self) -> None:
        view = _view(
            positions=[
                _position(symbol="CASH", weight_pct=85.0, market_value=8500, is_cash=True, asset_class="cash"),
                _position(symbol="AAPL", weight_pct=15.0, market_value=1500),
            ],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=85.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=85.0,
                cash_pct=85.0,
                invested_pct=15.0,
                priced_position_coverage_pct=100.0,
            ),
        )
        kwargs = dict(
            portfolio_id="pf-1",
            generated_at="2026-08-13T00:00:00+00:00",
            portfolio_view=view,
        )
        codes = [item.code for item in build_portfolio_diagnostics(**kwargs).diagnostics]
        self.assertEqual(codes, [item.code for item in build_portfolio_diagnostics(**kwargs).diagnostics])

    def test_diagnostics_engine_source_unchanged_for_ui_cleanup(self) -> None:
        engine_path = Path("services/wealth_diagnostics_engine.py")
        service_path = Path("services/wealth_diagnostics_service.py")
        contract_path = Path("services/wealth_diagnostics_contract.py")
        for path in (engine_path, service_path, contract_path):
            lowered = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("import streamlit", lowered, path.name)
            self.assertNotIn("st.expander", lowered, path.name)
            self.assertNotIn("st.json", lowered, path.name)


if __name__ == "__main__":
    unittest.main()
