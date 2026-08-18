from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from services.portfolio_allocation_intelligence import (
    ALLOCATION_DRIFT_TOLERANCE_PCT,
    AllocationCompleteness,
    AllocationDimension,
    AllocationPolicy,
    AllocationPolicyStatus,
    AllocationProvenance,
    AllocationTarget,
    DriftStatus,
    RoutingStatus,
    build_allocation_intelligence,
)
from services.portfolio_decision_intelligence import CONCENTRATION_REVIEW_THRESHOLD_PCT
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.wealth_contract import WealthValidationError
from services.wealth_goal_models import ConversionAssumption

ACCOUNT = "acc-1"
ENGINE = Path("services/portfolio_allocation_intelligence.py")
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
TRADE_TOKENS = ("buy aapl", "sell tsla", "buy 17", "satın al", "sat tsla")


def _row(
    *,
    symbol: str,
    price_available: bool,
    market_value,
    currency: str,
    weight_pct=None,
    asset_class: str = "equity",
    **kwargs,
) -> PositionValuationRow:
    defaults = dict(
        position_id=f"p-{symbol}",
        account_id=ACCOUNT,
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class=asset_class,
        account_name="Broker",
        quantity=1,
        average_cost=10,
        valuation_currency=currency,
        price=110 if price_available else None,
        price_available=price_available,
        market_value=market_value,
        cost_basis=10,
        unrealized_pl=100 if price_available else None,
        weight_pct=weight_pct,
        is_cash=asset_class == "cash",
        included_in_base_totals=price_available and currency == "USD",
    )
    defaults.update(kwargs)
    return PositionValuationRow(**defaults)


def _view(
    *,
    priced: list[PositionValuationRow],
    unpriced: list[PositionValuationRow] | None = None,
    foreign: list[PositionValuationRow] | None = None,
    mixed: bool = False,
) -> PortfolioIntelligenceView:
    unpriced = unpriced or []
    foreign = foreign or []
    priced_mv = sum(float(row.market_value or 0.0) for row in priced)
    total = len(priced) + len(unpriced) + len(foreign)
    coverage = (len(priced) / total) * 100.0 if total else 100.0
    weights = sorted(
        [float(row.weight_pct or 0.0) for row in priced if row.weight_pct is not None],
        reverse=True,
    )
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=priced_mv,
        priced_total_cost_basis=sum(float(row.cost_basis) for row in priced),
        priced_total_unrealized_pl=sum(float(row.unrealized_pl or 0.0) for row in priced),
        priced_position_count=len(priced),
        unpriced_position_count=len(unpriced) + len(foreign),
        foreign_currency_position_count=len(foreign),
        total_position_count=total,
        mixed_currency_warning=mixed or bool(foreign),
        fx_supported=False,
        priced_positions=priced,
        unpriced_positions=unpriced,
        foreign_currency_positions=foreign,
        asset_class_allocation=[AllocationSlice("equity", "equity", priced_mv, 100.0)],
        account_allocation=[AllocationSlice(ACCOUNT, "Broker", priced_mv, 100.0)],
        health=PortfolioHealthMetrics(
            weights[0] if weights else 0.0,
            sum(weights[:3]),
            100.0,
            0.0,
            100.0,
            coverage,
        ),
        valuation_errors=[],
        price_provider="none",
        unique_price_symbols_fetched=0,
    )


def _complete_usd_view() -> PortfolioIntelligenceView:
    return _view(
        priced=[
            _row(
                symbol="AAPL",
                price_available=True,
                market_value=40.0,
                currency="USD",
                weight_pct=40.0,
                asset_class="equity",
            ),
            _row(
                symbol="SPUS",
                price_available=True,
                market_value=60.0,
                currency="USD",
                weight_pct=60.0,
                asset_class="etf",
            ),
        ]
    )


def _partial_bist_view(*, top_weight: float = 19.2) -> PortfolioIntelligenceView:
    priced_mv = 58515.97
    equity_mv = priced_mv * 0.55
    etf_mv = priced_mv - equity_mv
    return _view(
        priced=[
            _row(
                symbol="AAPL",
                price_available=True,
                market_value=equity_mv * top_weight / 55.0,
                currency="USD",
                weight_pct=top_weight,
                asset_class="equity",
            ),
            _row(
                symbol="AVGO",
                price_available=True,
                market_value=equity_mv - (equity_mv * top_weight / 55.0),
                currency="USD",
                weight_pct=55.0 - top_weight,
                asset_class="equity",
            ),
            _row(
                symbol="SPUS",
                price_available=True,
                market_value=etf_mv,
                currency="USD",
                weight_pct=45.0,
                asset_class="etf",
            ),
        ],
        foreign=[
            _row(symbol="BIMAS", price_available=False, market_value=None, currency="TRY"),
            _row(symbol="ASELS", price_available=False, market_value=None, currency="TRY"),
            _row(symbol="TUPRS", price_available=False, market_value=None, currency="TRY"),
        ],
        mixed=True,
    )


def _asset_class_policy(*, equity: float, etf: float, cash: float = 0.0) -> AllocationPolicy:
    targets = [
        AllocationTarget("equity", AllocationDimension.ASSET_CLASS, equity),
        AllocationTarget("etf", AllocationDimension.ASSET_CLASS, etf),
    ]
    if cash:
        targets.append(AllocationTarget("cash", AllocationDimension.ASSET_CLASS, cash))
    return AllocationPolicy(
        targets=tuple(targets),
        provenance=AllocationProvenance.USER_DEFINED,
    )


class CurrentAllocationTests(unittest.TestCase):
    def test_priced_allocation_aggregates_and_preserves_symbols(self) -> None:
        view = build_allocation_intelligence(_complete_usd_view())
        by_id = {row.bucket_id: row for row in view.asset_class_buckets}
        self.assertAlmostEqual(by_id["equity"].observable_weight_pct or 0, 40.0, places=2)
        self.assertAlmostEqual(by_id["etf"].observable_weight_pct or 0, 60.0, places=2)
        self.assertEqual(by_id["equity"].position_count, 1)
        self.assertEqual(by_id["etf"].position_count, 1)
        self.assertEqual(by_id["equity"].symbols, ("AAPL",))
        self.assertEqual(by_id["etf"].symbols, ("SPUS",))
        self.assertEqual(view.completeness, AllocationCompleteness.COMPLETE_ALLOCATION)

    def test_unknown_classification_is_other_or_unknown(self) -> None:
        portfolio = _view(
            priced=[
                _row(
                    symbol="ZZZZ",
                    price_available=True,
                    market_value=100.0,
                    currency="USD",
                    weight_pct=100.0,
                    asset_class="mystery",
                )
            ]
        )
        view = build_allocation_intelligence(portfolio)
        self.assertEqual(view.asset_class_buckets[0].bucket_id, "other")
        self.assertEqual(view.market_buckets[0].bucket_id, "unknown")


class PartialValuationTests(unittest.TestCase):
    def test_unpriced_bist_represented_without_zero_weight(self) -> None:
        view = build_allocation_intelligence(_partial_bist_view())
        symbols = {row.symbol for row in view.unpriced_holdings}
        self.assertEqual(symbols, {"BIMAS", "ASELS", "TUPRS"})
        tr = next(row for row in view.market_buckets if row.bucket_id == "tr")
        self.assertIsNone(tr.observable_weight_pct)
        self.assertIsNone(tr.observable_market_value)
        self.assertNotEqual(tr.observable_weight_pct, 0)
        self.assertEqual(set(tr.unpriced_symbols), {"BIMAS", "ASELS", "TUPRS"})
        self.assertEqual(view.completeness, AllocationCompleteness.PARTIAL_ALLOCATION)
        self.assertIn("PARTIAL_VALUATION", view.limitations)
        for bucket in view.asset_class_buckets:
            if bucket.observable_weight_pct is not None:
                self.assertEqual(
                    bucket.weight_scope,
                    AllocationCompleteness.OBSERVABLE_ALLOCATION,
                )

    def test_holdings_recover_unvalued_when_view_omits_bist(self) -> None:
        priced = [
            _row(
                symbol="AAPL",
                price_available=True,
                market_value=100.0,
                currency="USD",
                weight_pct=100.0,
            )
        ]
        portfolio = _view(priced=priced)
        assets = [
            {"id": "as-AAPL", "symbol": "AAPL", "asset_class": "equity", "market": "US", "currency": "USD"},
            {"id": "as-BIMAS", "symbol": "BIMAS", "asset_class": "equity", "market": "TR", "currency": "TRY"},
            {"id": "as-ASELS", "symbol": "ASELS", "asset_class": "equity", "market": "TR", "currency": "TRY"},
            {"id": "as-TUPRS", "symbol": "TUPRS", "asset_class": "equity", "market": "TR", "currency": "TRY"},
        ]
        positions = [
            {"id": "p-AAPL", "asset_id": "as-AAPL", "quantity": 1, "average_cost": 10},
            {"id": "p-BIMAS", "asset_id": "as-BIMAS", "quantity": 1, "average_cost": 10},
            {"id": "p-ASELS", "asset_id": "as-ASELS", "quantity": 1, "average_cost": 10},
            {"id": "p-TUPRS", "asset_id": "as-TUPRS", "quantity": 1, "average_cost": 10},
        ]
        view = build_allocation_intelligence(portfolio, assets=assets, positions=positions)
        self.assertEqual(
            {row.symbol for row in view.unpriced_holdings},
            {"BIMAS", "ASELS", "TUPRS"},
        )
        tr = next(row for row in view.market_buckets if row.bucket_id == "tr")
        self.assertIsNone(tr.observable_weight_pct)
        self.assertEqual(view.completeness, AllocationCompleteness.PARTIAL_ALLOCATION)


class TargetPolicyTests(unittest.TestCase):
    def test_missing_target_is_not_configured(self) -> None:
        view = build_allocation_intelligence(_complete_usd_view())
        self.assertEqual(view.target_policy_status, AllocationPolicyStatus.TARGET_NOT_CONFIGURED)
        self.assertEqual(view.routing[0].status, RoutingStatus.TARGET_NOT_CONFIGURED)
        self.assertEqual(view.drift, ())

    def test_invalid_totals_and_negative_weights_rejected(self) -> None:
        with self.assertRaises(WealthValidationError):
            AllocationPolicy(
                targets=(
                    AllocationTarget("equity", AllocationDimension.ASSET_CLASS, 40),
                    AllocationTarget("etf", AllocationDimension.ASSET_CLASS, 40),
                ),
                provenance=AllocationProvenance.USER_DEFINED,
            ).validate()
        with self.assertRaises(WealthValidationError):
            AllocationTarget("equity", AllocationDimension.ASSET_CLASS, -1).validate()
        with self.assertRaises(WealthValidationError):
            AllocationPolicy(
                targets=(AllocationTarget("equity", AllocationDimension.ASSET_CLASS, 100),),
                provenance=AllocationProvenance.USER_DEFINED,
                tolerance_pct=-1,
            ).validate()


class DriftTests(unittest.TestCase):
    def test_complete_portfolio_drift_math_and_signs(self) -> None:
        policy = _asset_class_policy(equity=50, etf=50)
        view = build_allocation_intelligence(_complete_usd_view(), policy=policy)
        by_id = {row.bucket_id: row for row in view.drift}
        self.assertEqual(by_id["equity"].status, DriftStatus.UNDERWEIGHT)
        self.assertEqual(by_id["etf"].status, DriftStatus.OVERWEIGHT)
        self.assertAlmostEqual(by_id["equity"].drift_pct or 0, -10.0, places=2)
        self.assertAlmostEqual(by_id["etf"].drift_pct or 0, 10.0, places=2)

    def test_tolerance_marks_on_target(self) -> None:
        policy = AllocationPolicy(
            targets=(
                AllocationTarget("equity", AllocationDimension.ASSET_CLASS, 41.5),
                AllocationTarget("etf", AllocationDimension.ASSET_CLASS, 58.5),
            ),
            tolerance_pct=2.0,
            provenance=AllocationProvenance.USER_DEFINED,
        )
        view = build_allocation_intelligence(_complete_usd_view(), policy=policy)
        self.assertTrue(all(row.status == DriftStatus.ON_TARGET for row in view.drift))

    def test_partial_valuation_can_be_indeterminate(self) -> None:
        policy = _asset_class_policy(equity=70, etf=30)
        view = build_allocation_intelligence(_partial_bist_view(), policy=policy)
        statuses = {row.status for row in view.drift}
        self.assertIn(DriftStatus.INDETERMINATE, statuses)
        equity = next(row for row in view.drift if row.bucket_id == "equity")
        self.assertIsNotNone(equity.drift_pct)
        self.assertEqual(equity.status, DriftStatus.INDETERMINATE)
        self.assertIn("PARTIAL_VALUATION", equity.limitations)


class RoutingTests(unittest.TestCase):
    def test_contribution_routing_reduces_total_absolute_drift(self) -> None:
        policy = _asset_class_policy(equity=50, etf=50)
        view = build_allocation_intelligence(
            _complete_usd_view(),
            policy=policy,
            contribution_amount=Decimal("20"),
            contribution_currency="USD",
        )
        route = view.routing[0]
        self.assertEqual(route.status, RoutingStatus.AVAILABLE)
        self.assertEqual(route.best_bucket_id, "equity")
        self.assertGreater(route.improvement or 0, 0)
        self.assertLess(route.after_drift_score or 0, route.before_drift_score or 0)
        self.assertNotIn(route.best_bucket_id, {"AAPL", "SPUS", "TSLA"})

    def test_tie_routing_is_deterministic(self) -> None:
        portfolio = _view(
            priced=[
                _row(
                    symbol="AAPL",
                    price_available=True,
                    market_value=50.0,
                    currency="USD",
                    weight_pct=50.0,
                    asset_class="equity",
                ),
                _row(
                    symbol="SPUS",
                    price_available=True,
                    market_value=50.0,
                    currency="USD",
                    weight_pct=50.0,
                    asset_class="etf",
                ),
            ]
        )
        policy = _asset_class_policy(equity=50, etf=50)
        first = build_allocation_intelligence(
            portfolio,
            policy=policy,
            contribution_amount=Decimal("10"),
            contribution_currency="USD",
        )
        second = build_allocation_intelligence(
            portfolio,
            policy=policy,
            contribution_amount=Decimal("10"),
            contribution_currency="USD",
        )
        self.assertEqual(first.routing[0].best_bucket_id, second.routing[0].best_bucket_id)
        self.assertEqual(first.routing[0].best_bucket_id, "equity")

    def test_missing_fx_makes_routing_unavailable(self) -> None:
        view = build_allocation_intelligence(
            _complete_usd_view(),
            policy=_asset_class_policy(equity=50, etf=50),
            contribution_amount=Decimal("60000"),
            contribution_currency="TRY",
        )
        self.assertEqual(view.routing[0].status, RoutingStatus.FX_REQUIRED)
        self.assertIsNone(view.routing[0].best_bucket_id)

    def test_fx_assumption_enables_routing(self) -> None:
        view = build_allocation_intelligence(
            _complete_usd_view(),
            policy=_asset_class_policy(equity=50, etf=50),
            contribution_amount=Decimal("340"),
            contribution_currency="TRY",
            conversion=ConversionAssumption("TRY", "USD", Decimal("34")),
        )
        self.assertEqual(view.routing[0].status, RoutingStatus.AVAILABLE)
        self.assertEqual(view.routing[0].best_bucket_id, "equity")

    def test_no_target_routing_unavailable(self) -> None:
        view = build_allocation_intelligence(
            _complete_usd_view(),
            contribution_amount=Decimal("10"),
            contribution_currency="USD",
        )
        self.assertEqual(view.routing[0].status, RoutingStatus.TARGET_NOT_CONFIGURED)


class SafetyTests(unittest.TestCase):
    def test_no_sell_or_security_recommendation(self) -> None:
        view = build_allocation_intelligence(
            _complete_usd_view(),
            policy=_asset_class_policy(equity=50, etf=50),
            contribution_amount=Decimal("20"),
            contribution_currency="USD",
        )
        blob = " ".join(
            [
                view.to_dict().__repr__(),
                str(view.routing[0].best_bucket_id),
                *[row.bucket_id for row in view.drift],
            ]
        ).lower()
        for token in TRADE_TOKENS:
            self.assertNotIn(token, blob)
        self.assertNotEqual(view.routing[0].best_bucket_id, "AAPL")

    def test_no_provider_or_persistence_path(self) -> None:
        source = ENGINE.read_text(encoding="utf-8").lower()
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token.lower(), source)
        raw = ENGINE.read_text(encoding="utf-8")
        for token in WRITE_TOKENS:
            self.assertNotIn(token, raw)
        build_allocation_intelligence(_partial_bist_view())

    def test_concentration_threshold_unchanged(self) -> None:
        self.assertEqual(CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT, 20.0)
        self.assertEqual(CONCENTRATION_REVIEW_THRESHOLD_PCT, 20.0)
        self.assertEqual(ALLOCATION_DRIFT_TOLERANCE_PCT, 2.0)
        source = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT", source)
        view = build_allocation_intelligence(_partial_bist_view())
        self.assertTrue(all(row.bucket_id != "AAPL" for row in view.asset_class_buckets))


class DecisionSurfaceTests(unittest.TestCase):
    def test_signals_expose_unconfigured_target_without_rewriting_decision(self) -> None:
        view = build_allocation_intelligence(_partial_bist_view())
        self.assertEqual(view.signals.target_status, AllocationPolicyStatus.TARGET_NOT_CONFIGURED)
        self.assertTrue(view.signals.allocation_evidence_incomplete)
        self.assertFalse(view.signals.contribution_routing_available)
        self.assertFalse(view.signals.material_drift)
        decision = Path("services/portfolio_decision_intelligence.py").read_text(encoding="utf-8")
        self.assertIn("AllocationDecisionSignals", decision)
        self.assertNotIn("portfolio_allocation_policy", decision)
        self.assertNotIn(".insert(", decision)


if __name__ == "__main__":
    unittest.main()
