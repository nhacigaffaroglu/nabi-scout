from __future__ import annotations

import time
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from services.hybrid_exposure_allocation_policy import (
    HYBRID_MAX_UNKNOWN_PORTFOLIO_PCT,
    HybridExposureAllocationPolicy,
    HybridPortfolioMode,
    first_live_blocker,
    policy_ceiling_is_usable,
    resolve_hybrid_allocation_policy,
    resolve_hybrid_portfolio_mode,
    select_hybrid_allocation_intent,
)
from services.layer_exposure_determinacy import assess_economic_exposure_determinacy
from services.nabi_adviser_context import build_nabi_adviser_context
from services.portfolio_allocation_intelligence import (
    AllocationDimension,
    AllocationPolicy,
    AllocationProvenance,
    AllocationTarget,
)
from services.portfolio_economic_exposure import (
    EconomicExposure,
    ExposureConfidence,
    ExposureEvidenceSource,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_goal_models import ConversionAssumption
from services.wealth_new_money_allocation import allocate_new_money

POLICY = Path("services/hybrid_exposure_allocation_policy.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
ADVISER = Path("services/nabi_adviser_context.py")

TARGETS = (
    ("equity", 75.0),
    ("fixed_income", 5.0),
    ("sukuk", 10.0),
    ("real_estate", 5.0),
    ("cash", 5.0),
    ("commodity", 0.0),
    ("other", 0.0),
)
KNOWN = {
    "equity": 96.6857,
    "fixed_income": 2.9567,
    "sukuk": 0.0,
    "real_estate": 0.0,
    "cash": 0.0,
    "commodity": 0.0,
    "other": 0.0,
}
LIVE_U = 0.3599


def _ee_policy() -> AllocationPolicy:
    return AllocationPolicy(
        targets=tuple(
            AllocationTarget(bucket, AllocationDimension.ECONOMIC_EXPOSURE, pct)
            for bucket, pct in TARGETS
        ),
        provenance=AllocationProvenance.USER_DEFINED,
        tolerance_pct=2.0,
    )


def _row(symbol, *, market_value, weight_pct, asset_class="equity", **extra):
    price = extra.get("price", 100.0)
    price_available = extra.get("price_available", True)
    currency = extra.get("currency", "USD")
    nabi = SimpleNamespace(
        participation_status=extra.get("participation", "Uygun"),
        symbol=symbol,
        research_allowed=extra.get("research_allowed"),
    )
    return PositionValuationRow(
        position_id=extra.get("position_id") or f"p-{symbol}",
        account_id=extra.get("account_id", "acc-1"),
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class=asset_class,
        account_name="Broker",
        quantity=market_value / price if price else 0,
        average_cost=price,
        valuation_currency=currency,
        price=price if price_available else None,
        price_available=price_available,
        market_value=market_value if price_available else None,
        cost_basis=market_value,
        unrealized_pl=0,
        weight_pct=weight_pct,
        is_cash=asset_class == "cash",
        included_in_base_totals=price_available and currency == "USD",
        nabi=nabi,
    )


def _view(rows):
    priced_mv = sum(float(row.market_value or 0.0) for row in rows)
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Ana Portföy",
        base_currency="USD",
        priced_total_market_value=priced_mv,
        priced_total_cost_basis=priced_mv,
        priced_total_unrealized_pl=0.0,
        priced_position_count=len(rows),
        unpriced_position_count=0,
        foreign_currency_position_count=0,
        total_position_count=len(rows),
        mixed_currency_warning=False,
        fx_supported=False,
        priced_positions=tuple(rows),
        unpriced_positions=(),
        foreign_currency_positions=(),
        asset_class_allocation=[AllocationSlice("equity", "equity", priced_mv, 100.0)],
        account_allocation=[AllocationSlice("acc-1", "Broker", priced_mv, 100.0)],
        health=PortfolioHealthMetrics(100.0, 100.0, 100.0, 0.0, 100.0, 100.0),
        valuation_errors=[],
        price_provider="none",
        unique_price_symbols_fetched=0,
    )


def _live_book():
    return _view(
        [
            _row("CRM", market_value=84555.6, weight_pct=96.6857),
            _row("FI1", market_value=2585.85, weight_pct=2.9567, asset_class="fixed_income"),
            _row("UNK1", market_value=314.71, weight_pct=0.3599, asset_class="etf"),
        ]
    )


def _complete_book():
    return _view(
        [
            _row("AAPL", market_value=1400, weight_pct=14),
            _row("MSFT", market_value=1400, weight_pct=14),
            _row("NVDA", market_value=1400, weight_pct=14),
            _row("GOOG", market_value=1400, weight_pct=14),
            _row("AMZN", market_value=1400, weight_pct=14),
            _row("SUKUK1", market_value=1500, weight_pct=15, asset_class="sukuk"),
            _row("SUKUK2", market_value=1500, weight_pct=15, asset_class="sukuk"),
        ]
    )


def _candidate(symbol, **extra):
    row = {
        "symbol": symbol,
        "decision": extra.pop("decision", "GÜÇLÜ ADAY"),
        "current_price": extra.pop("price", 100),
        "currency": "USD",
        "market": "US",
        "asset_type": extra.pop("asset_type", "Hisse"),
        "participation_status": extra.pop("participation_status", "Uygun"),
        "data_source": "FMP",
    }
    row.update(extra)
    return row


def _slice(bucket, weight=100.0):
    return EconomicExposure(
        exposure_bucket=bucket,
        weight_pct=weight,
        evidence_source=ExposureEvidenceSource.CANONICAL_STATIC_MAPPING,
        confidence=ExposureConfidence.HIGH,
    )


def _plan(*, view=None, hybrid=None, policy=None, **kwargs):
    enabled = None if hybrid is None else bool(hybrid)
    return allocate_new_money(
        available_amount=Decimal("100000"),
        amount_currency="TRY",
        portfolio_view=view or _live_book(),
        policy=policy or _ee_policy(),
        conversion=ConversionAssumption("TRY", "USD", Decimal("30")),
        enable_hybrid_exposure_allocation=enabled,
        **kwargs,
    )


def _shadow(unknown, known=None):
    return assess_economic_exposure_determinacy(
        targets=TARGETS,
        known_by_layer=known or KNOWN,
        unknown_pct=unknown,
        tolerance_pct=2.0,
        valuation_complete=True,
        unpriced=False,
    )


def _mode(unknown, *, policy=None, enabled=True, **kwargs):
    return resolve_hybrid_portfolio_mode(
        policy=policy or resolve_hybrid_allocation_policy(enabled),
        determinacy=_shadow(unknown),
        valuation_complete=kwargs.get("valuation_complete", True),
        unpriced=kwargs.get("unpriced", False),
        dimension="ECONOMIC_EXPOSURE",
    )


class ConfigAndStateMachineTests(unittest.TestCase):
    def test_flag_missing_is_off(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        self.assertFalse(resolve_hybrid_allocation_policy(None).enabled)
        self.assertEqual(_plan(hybrid=None).hybrid_portfolio_mode, "STRICT")

    def test_approved_ceiling_is_centralized(self) -> None:
        self.assertEqual(HYBRID_MAX_UNKNOWN_PORTFOLIO_PCT, 1.00)
        self.assertTrue(policy_ceiling_is_usable(1.00))
        self.assertFalse(policy_ceiling_is_usable(None))
        self.assertFalse(policy_ceiling_is_usable(float("nan")))
        self.assertFalse(policy_ceiling_is_usable(-1))
        self.assertNotIn("os.environ", POLICY.read_text(encoding="utf-8"))

    def test_missing_or_invalid_ceiling_unavailable(self) -> None:
        missing = HybridExposureAllocationPolicy(
            enable_hybrid_exposure_allocation=True,
            max_unknown_portfolio_pct=None,
        )
        invalid = HybridExposureAllocationPolicy(
            enable_hybrid_exposure_allocation=True,
            max_unknown_portfolio_pct=float("nan"),
        )
        self.assertEqual(_mode(0.25, policy=missing), HybridPortfolioMode.UNAVAILABLE)
        self.assertEqual(_mode(0.25, policy=invalid), HybridPortfolioMode.UNAVAILABLE)
        plan = _plan(hybrid=True, hybrid_policy=missing)
        self.assertEqual(plan.hybrid_portfolio_mode, "UNAVAILABLE")
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(first_live_blocker(plan.limitations), "PORTFOLIO_EXPOSURE_UNAVAILABLE")

    def test_state_machine_no_overlap(self) -> None:
        self.assertEqual(_mode(0.0, enabled=False), HybridPortfolioMode.STRICT)
        self.assertEqual(_mode(0.0), HybridPortfolioMode.COMPLETE)
        for unknown in (0.0001, 0.10, 0.25, 0.50, 0.9999, 1.0000, LIVE_U):
            self.assertEqual(_mode(unknown), HybridPortfolioMode.BOUNDED, unknown)
        for unknown in (1.0001, 1.5, 3.3166, 5.0, 10.0):
            self.assertEqual(_mode(unknown), HybridPortfolioMode.UNSAFE, unknown)
        self.assertEqual(_mode(0.2, unpriced=True), HybridPortfolioMode.UNAVAILABLE)
        self.assertEqual(_mode(float("nan")), HybridPortfolioMode.UNAVAILABLE)

    def test_unsafe_does_not_fall_back_to_strict(self) -> None:
        plan = _plan(
            view=_view([_row("CRM", market_value=9000, weight_pct=90), _row("SPSK", market_value=1000, weight_pct=10, asset_class="etf")]),
            hybrid=True,
        )
        self.assertEqual(plan.hybrid_portfolio_mode, "UNSAFE")
        self.assertEqual(plan.recommendations, ())
        self.assertNotEqual(first_live_blocker(plan.limitations), "EXPOSURE_CLASSIFICATION_INCOMPLETE")


class ReplayAndRollbackTests(unittest.TestCase):
    def test_live_book_strict_and_hybrid_side_by_side(self) -> None:
        off = _plan(view=_live_book(), hybrid=False)
        on = _plan(view=_live_book(), hybrid=True)
        self.assertEqual(off.hybrid_portfolio_mode, "STRICT")
        self.assertEqual(first_live_blocker(off.limitations), "EXPOSURE_CLASSIFICATION_INCOMPLETE")
        self.assertEqual(on.hybrid_portfolio_mode, "BOUNDED")
        self.assertEqual(off.total_allocated, Decimal("0"))
        self.assertEqual(on.total_allocated, Decimal("0"))
        self.assertEqual(off.residual_cash, Decimal("100000"))
        self.assertEqual(on.residual_cash, Decimal("100000"))
        self.assertTrue(
            first_live_blocker(on.limitations).startswith(
                "NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER"
            )
        )

    def test_complete_book_on_equals_off(self) -> None:
        policy = AllocationPolicy(
            targets=(
                AllocationTarget("equity", AllocationDimension.ECONOMIC_EXPOSURE, 70),
                AllocationTarget("sukuk", AllocationDimension.ECONOMIC_EXPOSURE, 30),
            ),
            provenance=AllocationProvenance.USER_DEFINED,
            tolerance_pct=2.0,
        )
        off = _plan(view=_complete_book(), policy=policy, hybrid=False)
        on = _plan(view=_complete_book(), policy=policy, hybrid=True)
        self.assertEqual(on.hybrid_portfolio_mode, "COMPLETE")
        self.assertEqual(off.recommendations, on.recommendations)
        self.assertEqual(off.total_allocated, on.total_allocated)
        self.assertEqual(off.residual_cash, on.residual_cash)

    def test_rollback_flag_restores_strict(self) -> None:
        on = _plan(view=_live_book(), hybrid=True)
        off = _plan(view=_live_book(), hybrid=False)
        self.assertEqual(on.hybrid_portfolio_mode, "BOUNDED")
        self.assertEqual(off.hybrid_portfolio_mode, "STRICT")
        self.assertEqual(first_live_blocker(off.limitations), "EXPOSURE_CLASSIFICATION_INCOMPLETE")
        self.assertFalse(off.hybrid_allocation_active)


class MultiLayerAndPriorityTests(unittest.TestCase):
    def test_unfillable_sukuk_does_not_block_real_estate(self) -> None:
        plan = _plan(
            view=_live_book(),
            hybrid=True,
            candidates=[_candidate("REIT1", asset_type="REIT")],
            canonical_mappings={"REIT1": (_slice("real_estate"),)},
        )
        self.assertEqual(plan.hybrid_portfolio_mode, "BOUNDED")
        self.assertIn("REIT1", [row.symbol for row in plan.recommendations])
        self.assertGreater(plan.total_allocated, Decimal("0"))
        self.assertIn("UNFILLED_UNDERWEIGHT:sukuk", plan.limitations)
        self.assertFalse(
            first_live_blocker(plan.limitations).startswith(
                "NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER"
            )
        )

    def test_layer_priority_is_largest_gap_then_name(self) -> None:
        intent = select_hybrid_allocation_intent(
            policy=resolve_hybrid_allocation_policy(True),
            determinacy=_shadow(LIVE_U),
            dimension="ECONOMIC_EXPOSURE",
        )
        order = [row.bucket_id for row in intent.underweight_rows]
        self.assertEqual(order, ["sukuk", "cash", "real_estate"])
        drifts = [row.drift_pct for row in intent.underweight_rows]
        self.assertEqual(drifts, sorted(drifts))

    def test_cash_layer_is_not_a_security_fill(self) -> None:
        source = NEW_MONEY.read_text(encoding="utf-8")
        self.assertIn('if layer == "cash":\n            return False', source)
        plan = _plan(view=_live_book(), hybrid=True)
        self.assertNotIn("cash", [row.layer for row in plan.recommendations])
        self.assertEqual(plan.residual_cash, Decimal("100000"))


class AdviserAndStatelessTests(unittest.TestCase):
    def test_adviser_separates_strict_and_bounded_facts(self) -> None:
        goal = SimpleNamespace(
            fx_schedule=SimpleNamespace(usdtry_for_year=lambda year: Decimal("30")),
            as_of_date=SimpleNamespace(year=2026),
        )
        off = build_nabi_adviser_context(
            "100.000 TL ek param var",
            portfolio_view=_live_book(),
            policy=_ee_policy(),
            goal_dashboard=goal,
        )
        on = build_nabi_adviser_context(
            "100.000 TL ek param var",
            portfolio_view=_live_book(),
            policy=_ee_policy(),
            enable_hybrid_exposure_allocation=True,
            goal_dashboard=goal,
        )
        self.assertFalse(off.economic_exposure_context["hybrid_allocation_active"])
        self.assertEqual(off.economic_exposure_context["portfolio_mode"], "STRICT")
        self.assertFalse(off.economic_exposure_context["classification_complete"])
        self.assertIn("tamamlanmadığı", off.canonical_answer)
        self.assertTrue(on.economic_exposure_context["hybrid_allocation_active"])
        self.assertEqual(on.economic_exposure_context["portfolio_mode"], "BOUNDED")
        self.assertGreater(on.economic_exposure_context["unknown_pct"], 0)
        self.assertLessEqual(on.economic_exposure_context["unknown_pct"], 1.00)
        self.assertIn("sukuk", on.economic_exposure_context["robust_underweight_layers"])
        self.assertEqual(on.economic_exposure_context["fillable_robust_underweight_layers"], [])
        self.assertIn("sukuk", on.economic_exposure_context["unfillable_robust_underweight_layers"])
        self.assertNotIn("portfolio complete", on.canonical_answer.lower())

    def test_hybrid_modules_are_stateless(self) -> None:
        for path in (POLICY, NEW_MONEY):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(".insert(", text)
            self.assertNotIn(".upsert(", text)
            self.assertNotIn(".update(", text)
            self.assertNotIn(".delete(", text)

    def test_hybrid_overhead_is_local(self) -> None:
        view = _live_book()
        start = time.perf_counter()
        _plan(view=view, hybrid=False)
        strict = time.perf_counter() - start
        start = time.perf_counter()
        _plan(view=view, hybrid=True)
        hybrid = time.perf_counter() - start
        self.assertLess(hybrid, 1.0)
        self.assertLess(strict, 1.0)
        self.assertNotIn("FMPClient", POLICY.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
