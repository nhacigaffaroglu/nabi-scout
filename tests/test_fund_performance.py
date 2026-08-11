import importlib
import unittest
from datetime import date, timedelta

from services.fund_analysis_contract import (
    LABEL_VOLATILITY_HIGH,
    LABEL_VOLATILITY_LOW,
    PRICE_RETURN_DISCLAIMER,
    STALE_OBSERVATION_WARNING,
)
from services.fund_performance_service import (
    FULL_CONFIDENCE_1Y_CLOSES,
    MIN_1M_CLOSES,
    MIN_1Y_CLOSES,
    MIN_DRAWDOWN_OBSERVATIONS,
    MIN_VOLATILITY_RETURNS,
    compute_fund_performance_metrics,
    compute_fund_risk_metrics,
    normalize_price_points,
)


def build_raw_series(
    closes: list[float],
    *,
    symbol: str = "TEST",
    start: date = date(2024, 1, 2),
    step_days: int = 1,
) -> list[dict]:
    rows = []
    current = start
    for close in closes:
        rows.append({"date": current.isoformat(), "price": close, "volume": 1000})
        current += timedelta(days=step_days)
    return rows


class FundPerformanceServiceTests(unittest.TestCase):
    def test_normalize_sorted_series(self) -> None:
        rows = [
            {"date": "2024-01-03", "price": 102},
            {"date": "2024-01-01", "price": 100},
            {"date": "2024-01-02", "price": 101},
        ]
        series = normalize_price_points("TEST", rows, source="fixture")
        self.assertEqual(len(series.points), 3)
        self.assertEqual(series.points[0].close, 100.0)
        self.assertEqual(series.points[-1].close, 102.0)

    def test_malformed_date_skipped(self) -> None:
        series = normalize_price_points(
            "TEST",
            [{"date": "bad", "price": 10}, {"date": "2024-01-01", "price": 11}],
        )
        self.assertEqual(len(series.points), 1)

    def test_duplicate_date_dedupe(self) -> None:
        series = normalize_price_points(
            "TEST",
            [
                {"date": "2024-01-01", "price": 10},
                {"date": "2024-01-01", "price": 12},
            ],
        )
        self.assertEqual(len(series.points), 1)
        self.assertEqual(series.points[0].close, 12.0)

    def test_missing_and_non_positive_prices_skipped(self) -> None:
        series = normalize_price_points(
            "TEST",
            [
                {"date": "2024-01-01", "price": None},
                {"date": "2024-01-02", "price": 0},
                {"date": "2024-01-03", "price": -1},
                {"date": "2024-01-04", "price": 10},
            ],
        )
        self.assertEqual(len(series.points), 1)

    def test_1m_exact_return(self) -> None:
        closes = [100.0] * 20 + [110.0]
        series = normalize_price_points("TEST", build_raw_series(closes))
        metrics = compute_fund_performance_metrics(
            series,
            as_of=series.points[-1].date,
        )
        self.assertEqual(metrics.return_1m_pct, 10.0)

    def test_1m_insufficient_history_omitted(self) -> None:
        closes = [100.0] * (MIN_1M_CLOSES - 1)
        series = normalize_price_points("TEST", build_raw_series(closes))
        metrics = compute_fund_performance_metrics(
            series,
            as_of=series.points[-1].date,
        )
        self.assertIsNone(metrics.return_1m_pct)

    def test_ytd_exact(self) -> None:
        rows = [
            {"date": "2024-12-31", "price": 100.0},
            {"date": "2025-01-02", "price": 101.0},
            {"date": "2025-01-03", "price": 102.0},
            {"date": "2025-01-04", "price": 103.0},
            {"date": "2025-01-05", "price": 104.0},
            {"date": "2025-01-06", "price": 110.0},
        ]
        series = normalize_price_points("TEST", rows)
        metrics = compute_fund_performance_metrics(series, as_of=date(2025, 1, 6))
        self.assertEqual(metrics.return_ytd_pct, 10.0)

    def test_ytd_insufficient_omitted(self) -> None:
        rows = [
            {"date": "2025-01-02", "price": 100.0},
            {"date": "2025-01-03", "price": 101.0},
        ]
        series = normalize_price_points("TEST", rows)
        metrics = compute_fund_performance_metrics(series, as_of=date(2025, 1, 3))
        self.assertIsNone(metrics.return_ytd_pct)

    def test_1y_exact(self) -> None:
        closes = [100.0] * (MIN_1Y_CLOSES - 1) + [120.0]
        series = normalize_price_points("TEST", build_raw_series(closes))
        metrics = compute_fund_performance_metrics(
            series,
            as_of=series.points[-1].date,
        )
        self.assertEqual(metrics.return_1y_pct, 20.0)

    def test_1y_degraded_threshold(self) -> None:
        closes = [100.0] * (MIN_1Y_CLOSES - 1) + [105.0]
        series = normalize_price_points("TEST", build_raw_series(closes))
        metrics = compute_fund_performance_metrics(
            series,
            as_of=series.points[-1].date,
        )
        self.assertIsNotNone(metrics.return_1y_pct)
        self.assertFalse(metrics.return_1y_full_confidence)

    def test_1y_full_confidence(self) -> None:
        closes = [100.0] * (FULL_CONFIDENCE_1Y_CLOSES - 1) + [105.0]
        series = normalize_price_points("TEST", build_raw_series(closes))
        metrics = compute_fund_performance_metrics(
            series,
            as_of=series.points[-1].date,
        )
        self.assertTrue(metrics.return_1y_full_confidence)

    def test_1y_insufficient_omitted(self) -> None:
        closes = [100.0] * (MIN_1Y_CLOSES - 1)
        series = normalize_price_points("TEST", build_raw_series(closes))
        metrics = compute_fund_performance_metrics(
            series,
            as_of=series.points[-1].date,
        )
        self.assertIsNone(metrics.return_1y_pct)

    def test_annualized_volatility_exact_fixture(self) -> None:
        closes = [100.0]
        for index in range(1, MIN_VOLATILITY_RETURNS + 1):
            closes.append(100.0 + (index % 3))
        series = normalize_price_points("TEST", build_raw_series(closes))
        risk = compute_fund_risk_metrics(series)
        self.assertIsNotNone(risk.annualized_volatility_pct)
        self.assertGreater(risk.annualized_volatility_pct, 0.0)

    def test_volatility_insufficient_omitted(self) -> None:
        closes = [100.0 + (index % 2) for index in range(MIN_VOLATILITY_RETURNS)]
        series = normalize_price_points("TEST", build_raw_series(closes))
        risk = compute_fund_risk_metrics(series)
        self.assertIsNone(risk.annualized_volatility_pct)

    def test_max_drawdown_exact_fixture(self) -> None:
        closes = [100.0] * 10 + [90.0, 85.0, 95.0] + [95.0] * 20
        series = normalize_price_points("TEST", build_raw_series(closes))
        risk = compute_fund_risk_metrics(series)
        self.assertEqual(risk.max_drawdown_pct, -15.0)

    def test_drawdown_insufficient_omitted(self) -> None:
        closes = [100.0 - index for index in range(MIN_DRAWDOWN_OBSERVATIONS - 1)]
        series = normalize_price_points("TEST", build_raw_series(closes))
        risk = compute_fund_risk_metrics(series)
        self.assertIsNone(risk.max_drawdown_pct)

    def test_monotonic_rising_series_drawdown_zero(self) -> None:
        closes = [100.0 + index for index in range(MIN_DRAWDOWN_OBSERVATIONS)]
        series = normalize_price_points("TEST", build_raw_series(closes))
        risk = compute_fund_risk_metrics(series)
        self.assertEqual(risk.max_drawdown_pct, 0.0)

    def test_stale_last_observation(self) -> None:
        rows = build_raw_series([100.0, 101.0, 102.0], start=date(2024, 1, 1))
        series = normalize_price_points("TEST", rows)
        metrics = compute_fund_performance_metrics(series, as_of=date(2024, 1, 20))
        self.assertTrue(metrics.is_stale)
        self.assertIn(STALE_OBSERVATION_WARNING, metrics.warnings)

    def test_recent_weekend_safe_not_stale(self) -> None:
        rows = build_raw_series([100.0, 101.0], start=date(2025, 8, 8))
        series = normalize_price_points("TEST", rows)
        metrics = compute_fund_performance_metrics(series, as_of=date(2025, 8, 11))
        self.assertFalse(metrics.is_stale)

    def test_malformed_payload_safe(self) -> None:
        series = normalize_price_points("TEST", [{"bad": True}, "nope"])
        metrics = compute_fund_performance_metrics(series)
        risk = compute_fund_risk_metrics(series)
        self.assertIsNone(metrics.return_1m_pct)
        self.assertIsNone(risk.max_drawdown_pct)

    def test_empty_series_safe(self) -> None:
        series = normalize_price_points("TEST", [])
        metrics = compute_fund_performance_metrics(series)
        self.assertEqual(metrics.observation_count, 0)
        self.assertIsNone(metrics.return_1y_pct)

    def test_no_total_return_wording_in_contract(self) -> None:
        from services.fund_analysis_contract import PERFORMANCE_SECTION_TITLE

        self.assertIn("fiyat", PERFORMANCE_SECTION_TITLE.lower())
        self.assertIn("temettü", PRICE_RETURN_DISCLAIMER.lower())

    def test_equity_like_volatility_labels(self) -> None:
        closes = [100.0]
        for index in range(1, MIN_VOLATILITY_RETURNS + 20):
            closes.append(100.0 + (index % 7) * 2)
        series = normalize_price_points("TEST", build_raw_series(closes))
        risk = compute_fund_risk_metrics(series, asset_class="Equity")
        self.assertIn(
            risk.volatility_label,
            {LABEL_VOLATILITY_LOW, LABEL_VOLATILITY_HIGH, "Orta oynaklık"},
        )

    def test_fixed_income_asset_class_suppresses_equity_volatility_label(self) -> None:
        closes = [100.0]
        for index in range(1, MIN_VOLATILITY_RETURNS + 20):
            closes.append(100.0 + (index % 7) * 2)
        series = normalize_price_points("TEST", build_raw_series(closes))
        risk = compute_fund_risk_metrics(series, asset_class="Fixed Income Sukuk")
        self.assertIsNotNone(risk.annualized_volatility_pct)
        self.assertIsNone(risk.volatility_label)
        self.assertIsNone(risk.drawdown_label)

    def test_provider_agnostic_service_imports_no_fmp(self) -> None:
        module = importlib.import_module("services.fund_performance_service")
        source = open(module.__file__, encoding="utf-8").read()
        self.assertNotIn("fmp_client", source)
        self.assertNotIn("FMPClient", source)


if __name__ == "__main__":
    unittest.main()
