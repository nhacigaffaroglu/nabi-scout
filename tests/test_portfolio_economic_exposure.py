from __future__ import annotations

import unittest
from pathlib import Path

from services.fund_intelligence_contract import FundHoldingRow, FundHoldingsSnapshotView
from services.portfolio_allocation_intelligence import AllocationDimension, build_allocation_intelligence
from services.portfolio_economic_exposure import (
    CANONICAL_STATIC_MAPPINGS,
    EXPOSURE_DIMENSION_KEY,
    EconomicExposure,
    EconomicExposureBucket,
    ExposureConfidence,
    ExposureEvidenceSource,
    build_economic_exposure,
    classify_instrument_exposure,
    validate_exposure_weights,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_contract import WealthValidationError
from tests.test_portfolio_allocation_intelligence import _complete_usd_view, _partial_bist_view, _row


ENGINE = Path("services/portfolio_economic_exposure.py")
ALLOCATION = Path("services/portfolio_allocation_intelligence.py")
POLICY_SQL = Path("database/migration_portfolio_allocation_policies.sql")
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
    ".insert(",
    ".upsert(",
    ".delete(",
    ".update(",
)


def _equity(symbol: str, market_value: float = 40.0, **kwargs) -> PositionValuationRow:
    return _row(
        symbol=symbol,
        price_available=True,
        market_value=market_value,
        currency="USD",
        weight_pct=market_value,
        asset_class="equity",
        **kwargs,
    )


def _etf(symbol: str, market_value: float = 60.0) -> PositionValuationRow:
    return _row(
        symbol=symbol,
        price_available=True,
        market_value=market_value,
        currency="USD",
        weight_pct=market_value,
        asset_class="etf",
    )


def _cash(market_value: float = 10.0) -> PositionValuationRow:
    return _row(
        symbol="CASH",
        price_available=True,
        market_value=market_value,
        currency="USD",
        weight_pct=market_value,
        asset_class="cash",
        is_cash=True,
    )


def _sukuk(symbol: str = "SUKUK1", market_value: float = 20.0) -> PositionValuationRow:
    return _row(
        symbol=symbol,
        price_available=True,
        market_value=market_value,
        currency="USD",
        weight_pct=market_value,
        asset_class="sukuk",
    )


def _snapshot(symbol: str, holdings: tuple[FundHoldingRow, ...], coverage: float = 100.0) -> FundHoldingsSnapshotView:
    return FundHoldingsSnapshotView(
        fund_symbol=symbol,
        fund_type="etf",
        as_of="2026-08-18",
        source="persisted",
        coverage_pct=coverage,
        underlying_count=len(holdings),
        holdings=holdings,
        data_quality="good",
        limitation="",
    )


def _mapped(*pairs: tuple[str, float]) -> tuple[EconomicExposure, ...]:
    return tuple(
        EconomicExposure(
            exposure_bucket=bucket,
            weight_pct=weight,
            evidence_source=ExposureEvidenceSource.CANONICAL_STATIC_MAPPING,
            confidence=ExposureConfidence.HIGH,
        )
        for bucket, weight in pairs
    )


class DirectSecurityTests(unittest.TestCase):
    def test_direct_equity_is_equity_fallback(self) -> None:
        view = classify_instrument_exposure(_equity("AAPL"))
        self.assertEqual(view.instrument_class, "equity")
        self.assertEqual(view.economic_exposures[0].exposure_bucket, "equity")
        self.assertEqual(view.economic_exposures[0].evidence_source, ExposureEvidenceSource.ASSET_CLASS_FALLBACK)
        self.assertEqual(view.economic_exposures[0].confidence, ExposureConfidence.HIGH)
        self.assertTrue(view.evidence_complete)

    def test_cash_is_cash(self) -> None:
        view = classify_instrument_exposure(_cash())
        self.assertEqual(view.instrument_class, "cash")
        self.assertEqual(view.economic_exposures[0].exposure_bucket, "cash")

    def test_direct_sukuk_is_sukuk_not_fixed_income(self) -> None:
        view = classify_instrument_exposure(_sukuk())
        self.assertEqual(view.economic_exposures[0].exposure_bucket, "sukuk")
        self.assertNotEqual(view.economic_exposures[0].exposure_bucket, "fixed_income")


class EtfEvidenceTests(unittest.TestCase):
    def test_trusted_mapping_is_used(self) -> None:
        view = classify_instrument_exposure(
            _etf("SPUS"),
            canonical_mappings={"SPUS": _mapped(("equity", 100.0))},
        )
        self.assertEqual(view.economic_exposures[0].exposure_bucket, "equity")
        self.assertEqual(
            view.economic_exposures[0].evidence_source,
            ExposureEvidenceSource.CANONICAL_STATIC_MAPPING,
        )

    def test_etf_without_evidence_is_unknown(self) -> None:
        for symbol in ("SPUS", "SPSK", "SPRE", "SPWO"):
            view = classify_instrument_exposure(_etf(symbol))
            with self.subTest(symbol=symbol):
                self.assertEqual(view.economic_exposures[0].exposure_bucket, "unknown")
                self.assertEqual(view.economic_exposures[0].evidence_source, ExposureEvidenceSource.UNKNOWN)
                self.assertFalse(view.evidence_complete)

    def test_no_ticker_name_guessing_in_engine_or_default_map(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        self.assertEqual(CANONICAL_STATIC_MAPPINGS, {})
        self.assertNotIn("S&P 500", source)
        self.assertNotIn("contains REIT", source)
        self.assertNotIn("therefore sukuk", source)
        self.assertNotIn('"SPUS":', source.split("CANONICAL_STATIC_MAPPINGS")[1][:200])


class WeightAndAggregationTests(unittest.TestCase):
    def test_multi_exposure_aggregates_without_double_count(self) -> None:
        mapping = {"SPUS": _mapped(("equity", 70.0), ("cash", 30.0))}
        view = build_economic_exposure(
            _view_from_rows([_equity("AAPL", 40), _etf("SPUS", 60)]),
            canonical_mappings=mapping,
        )
        by_id = {row.bucket_id: row for row in view.buckets}
        self.assertAlmostEqual(by_id["equity"].observable_market_value or 0, 82.0, places=2)
        self.assertAlmostEqual(by_id["cash"].observable_market_value or 0, 18.0, places=2)
        self.assertEqual(by_id["equity"].contributing_symbols, ("AAPL", "SPUS"))
        self.assertNotIn("SPUS", by_id["unknown"].contributing_symbols)

    def test_negative_exposure_rejected(self) -> None:
        with self.assertRaises(WealthValidationError):
            validate_exposure_weights(
                _mapped(("equity", -1.0), ("cash", 101.0)),
                complete=True,
            )

    def test_complete_weights_must_sum_to_100(self) -> None:
        with self.assertRaises(WealthValidationError):
            validate_exposure_weights(_mapped(("equity", 70.0)), complete=True)
        validate_exposure_weights(_mapped(("equity", 70.0), ("cash", 30.0)), complete=True)

    def test_partial_exposure_explicitly_incomplete(self) -> None:
        validate_exposure_weights(_mapped(("equity", 60.0)), complete=False)
        snapshot = _snapshot(
            "SPUS",
            (
                FundHoldingRow("AAPL", "Apple", 60.0, "equity", None, None),
            ),
            coverage=60.0,
        )
        view = classify_instrument_exposure(_etf("SPUS"), fund_snapshots={"SPUS": snapshot})
        self.assertFalse(view.evidence_complete)
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertAlmostEqual(buckets["equity"], 60.0)
        self.assertAlmostEqual(buckets["unknown"], 40.0)
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", view.limitations)

    def test_lookthrough_does_not_normalize_incomplete_coverage(self) -> None:
        snapshot = _snapshot(
            "SPUS",
            (
                FundHoldingRow("AAPL", "Apple", 90.0, "equity", None, None),
                FundHoldingRow("CASH", "Cash", 5.0, "cash", None, None),
            ),
            coverage=95.0,
        )
        view = classify_instrument_exposure(_etf("SPUS"), fund_snapshots={"SPUS": snapshot})
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertAlmostEqual(buckets["equity"], 90.0)
        self.assertAlmostEqual(buckets["cash"], 5.0)
        self.assertAlmostEqual(buckets["unknown"], 5.0)
        self.assertNotIn("94.74", str(buckets["equity"]))

    def test_lookthrough_cash_fixed_income_sukuk_and_explicit_reit(self) -> None:
        snapshot = _snapshot(
            "MIX",
            (
                FundHoldingRow("AAPL", "Apple", 40.0, "equity", None, None),
                FundHoldingRow("CASH", "Cash", 10.0, "cash", None, None),
                FundHoldingRow("BOND1", "Bond", 20.0, "bond", None, None),
                FundHoldingRow("SUK1", "Sukuk", 15.0, "sukuk", None, None),
                FundHoldingRow("O", "Realty Income REIT", 15.0, "reit", None, None),
            ),
        )
        view = classify_instrument_exposure(_etf("MIX"), fund_snapshots={"MIX": snapshot})
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertAlmostEqual(buckets["equity"], 40.0)
        self.assertAlmostEqual(buckets["cash"], 10.0)
        self.assertAlmostEqual(buckets["fixed_income"], 20.0)
        self.assertAlmostEqual(buckets["sukuk"], 15.0)
        self.assertAlmostEqual(buckets["real_estate"], 15.0)
        self.assertNotEqual(buckets["sukuk"], buckets["fixed_income"])

    def test_reit_name_without_explicit_type_is_not_real_estate(self) -> None:
        snapshot = _snapshot(
            "SPRE",
            (
                FundHoldingRow("O", "Realty Income REIT", 80.0, None, None, None),
            ),
            coverage=80.0,
        )
        view = classify_instrument_exposure(_etf("SPRE"), fund_snapshots={"SPRE": snapshot})
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertNotIn("real_estate", buckets)
        self.assertIn("unknown", buckets)

    def test_unknown_holding_ticker_without_type_is_not_guessed(self) -> None:
        snapshot = _snapshot(
            "SPSK",
            (
                FundHoldingRow("UNKNOWNBOND", "SP Funds Sukuk Holding", 50.0, None, None, None),
            ),
            coverage=50.0,
        )
        view = classify_instrument_exposure(_etf("SPSK"), fund_snapshots={"SPSK": snapshot})
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertEqual(set(buckets), {"unknown"})
        self.assertAlmostEqual(buckets["unknown"], 100.0)

    def test_unknown_market_value_preserved(self) -> None:
        view = build_economic_exposure(_view_from_rows([_etf("SPWO", 25), _equity("AAPL", 75)]))
        unknown = next(row for row in view.buckets if row.bucket_id == "unknown")
        self.assertAlmostEqual(unknown.observable_market_value or 0, 25.0)
        self.assertIn("SPWO", unknown.contributing_symbols)
        self.assertIn("UNKNOWN_EXPOSURE_PRESERVED", unknown.limitations)

    def test_unpriced_known_equity_is_not_zero_weight(self) -> None:
        view = build_economic_exposure(_partial_bist_view())
        equity = next(row for row in view.buckets if row.bucket_id == "equity")
        self.assertNotEqual(equity.observable_weight_pct, 0)
        self.assertTrue({"BIMAS", "ASELS", "TUPRS"} <= set(equity.unpriced_symbols))
        bimas = next(row for row in view.instruments if row.symbol == "BIMAS")
        self.assertEqual(bimas.economic_exposures[0].exposure_bucket, "equity")
        self.assertFalse(bimas.valuation_available)
        self.assertIsNone(bimas.observable_market_value)

    def test_valuation_and_classification_coverage_are_separate(self) -> None:
        view = build_economic_exposure(_view_from_rows([_equity("AAPL", 50), _etf("SPRE", 50)]))
        self.assertGreater(view.valuation_coverage_pct, 99.0)
        self.assertLess(view.exposure_classification_coverage_pct, 60.0)
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", view.limitations)
        self.assertNotIn("VALUATION_INCOMPLETE", view.limitations)

    def test_user_confirmed_override_has_precedence(self) -> None:
        view = classify_instrument_exposure(
            _etf("SPSK"),
            canonical_mappings={"SPSK": _mapped(("sukuk", 100.0))},
            user_overrides={"SPSK": _mapped(("fixed_income", 100.0))},
        )
        self.assertEqual(view.economic_exposures[0].exposure_bucket, "fixed_income")
        self.assertEqual(view.economic_exposures[0].evidence_source, ExposureEvidenceSource.USER_CONFIRMED)

    def test_deterministic_ordering(self) -> None:
        first = build_economic_exposure(_complete_usd_view())
        second = build_economic_exposure(_complete_usd_view())
        self.assertEqual([row.symbol for row in first.instruments], [row.symbol for row in second.instruments])
        self.assertEqual(
            [row.bucket_id for row in first.buckets],
            [item.value for item in EconomicExposureBucket],
        )


class SafetyAndCompatibilityTests(unittest.TestCase):
    def test_no_provider_or_write_tokens(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token, source)
        for token in WRITE_TOKENS:
            self.assertNotIn(token, source)
        build_economic_exposure(_complete_usd_view())

    def test_allocation_engine_does_not_import_exposure_module(self) -> None:
        allocation = ALLOCATION.read_text(encoding="utf-8")
        self.assertNotIn("portfolio_economic_exposure", allocation)
        view = build_allocation_intelligence(_complete_usd_view())
        self.assertTrue(view.asset_class_buckets)
        self.assertEqual(AllocationDimension.ASSET_CLASS.value, "ASSET_CLASS")
        self.assertEqual(AllocationDimension.ECONOMIC_EXPOSURE.value, EXPOSURE_DIMENSION_KEY)

    def test_target_policy_schema_dimension_check_extended_by_additive_migration(self) -> None:
        sql = POLICY_SQL.read_text(encoding="utf-8")
        self.assertIn("dimension in ('ASSET_CLASS', 'MARKET')", sql)
        self.assertNotIn("ECONOMIC_EXPOSURE", sql)
        migration = Path("database/migration_portfolio_allocation_policies_economic_exposure.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("PRE-DEPLOY MIGRATION REQUIRED", migration)
        self.assertIn("portfolio_allocation_policies_dimension_check", migration)
        self.assertIn("ASSET_CLASS", migration)
        self.assertIn("MARKET", migration)
        self.assertIn("ECONOMIC_EXPOSURE", migration)
        self.assertNotIn("drop table", migration.lower())
        self.assertNotIn("truncate", migration.lower())


def _view_from_rows(priced: list[PositionValuationRow]) -> PortfolioIntelligenceView:
    total = sum(float(row.market_value or 0) for row in priced)
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=total,
        priced_total_cost_basis=total,
        priced_total_unrealized_pl=0,
        priced_position_count=len(priced),
        unpriced_position_count=0,
        foreign_currency_position_count=0,
        total_position_count=len(priced),
        mixed_currency_warning=False,
        fx_supported=True,
        priced_positions=priced,
        unpriced_positions=[],
        foreign_currency_positions=[],
        asset_class_allocation=[AllocationSlice("equity", "equity", total, 100.0)],
        account_allocation=[],
        health=PortfolioHealthMetrics(50, 80, 80, 0, 100, 100),
        valuation_errors=[],
        price_provider="cache",
        unique_price_symbols_fetched=0,
    )


if __name__ == "__main__":
    unittest.main()
