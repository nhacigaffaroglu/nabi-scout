from __future__ import annotations

import os
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from services.exposure_determinacy_diagnostics import HYBRID_ALLOCATION_ACTIVE
from services.hybrid_exposure_allocation_policy import (
    HYBRID_BOUNDED_MIX_MAINTENANCE,
    HYBRID_LIVE_BLOCKER_PRECEDENCE,
    HYBRID_MAX_UNKNOWN_ABSOLUTE_VALUE,
    HYBRID_MAX_UNKNOWN_PORTFOLIO_PCT,
    HybridExposureAllocationPolicy,
    HybridPortfolioMode,
    first_live_blocker,
    resolve_hybrid_allocation_policy,
    resolve_hybrid_portfolio_mode,
    select_hybrid_allocation_intent,
)
from services.layer_exposure_determinacy import (
    LayerExposureDeterminacy,
    assess_economic_exposure_determinacy,
)
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
    classify_instrument_exposure,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_goal_models import ConversionAssumption
from services.wealth_new_money_allocation import (
    REASON_MIX_MAINTENANCE,
    REASON_PARTICIPATION_BLOCKED,
    REASON_RESEARCH_NOT_ALLOWED,
    allocate_new_money,
)

POLICY_MODULE = Path("services/hybrid_exposure_allocation_policy.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
DETERMINACY = Path("services/layer_exposure_determinacy.py")

CURRENT_TARGETS = (
    ("equity", 75.0),
    ("fixed_income", 5.0),
    ("sukuk", 10.0),
    ("real_estate", 5.0),
    ("cash", 5.0),
    ("commodity", 0.0),
    ("other", 0.0),
)
CURRENT_KNOWN = {
    "equity": 96.6857,
    "fixed_income": 0.0,
    "sukuk": 0.0,
    "real_estate": 0.0,
    "cash": 0.0,
    "commodity": 0.0,
    "other": 0.0,
}
CURRENT_U = 3.3166
AFTER_SPSK_U = 0.2594
TOL = 2.0


def _row(
    symbol: str,
    *,
    market_value: float,
    weight_pct: float,
    asset_class: str = "equity",
    price: float = 100.0,
    currency: str = "USD",
    price_available: bool = True,
    participation: str | None = "Uygun",
    research_allowed: bool | None = None,
    position_id: str | None = None,
    account_id: str = "acc-1",
) -> PositionValuationRow:
    nabi = None
    if participation is not None or research_allowed is not None:
        nabi = SimpleNamespace(
            participation_status=participation,
            symbol=symbol,
            research_allowed=research_allowed,
        )
    return PositionValuationRow(
        position_id=position_id or f"p-{symbol}",
        account_id=account_id,
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


def _view(priced: list[PositionValuationRow]) -> PortfolioIntelligenceView:
    priced_mv = sum(float(row.market_value or 0.0) for row in priced)
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=priced_mv,
        priced_total_cost_basis=priced_mv,
        priced_total_unrealized_pl=0.0,
        priced_position_count=len(priced),
        unpriced_position_count=0,
        foreign_currency_position_count=0,
        total_position_count=len(priced),
        mixed_currency_warning=False,
        fx_supported=False,
        priced_positions=tuple(priced),
        unpriced_positions=(),
        foreign_currency_positions=(),
        asset_class_allocation=[AllocationSlice("equity", "equity", priced_mv, 100.0)],
        account_allocation=[AllocationSlice("acc-1", "Broker", priced_mv, 100.0)],
        health=PortfolioHealthMetrics(100.0, 100.0, 100.0, 0.0, 100.0, 100.0),
        valuation_errors=[],
        price_provider="none",
        unique_price_symbols_fetched=0,
    )


def _ee_policy(**weights) -> AllocationPolicy:
    items = weights or dict(CURRENT_TARGETS)
    return AllocationPolicy(
        targets=tuple(
            AllocationTarget(bucket, AllocationDimension.ECONOMIC_EXPOSURE, pct)
            for bucket, pct in items.items()
        ),
        provenance=AllocationProvenance.USER_DEFINED,
        tolerance_pct=TOL,
    )


def _fx(rate: str = "30") -> ConversionAssumption:
    return ConversionAssumption("TRY", "USD", Decimal(rate))


def _candidate(symbol: str, decision="GÜÇLÜ ADAY", price=100, **extra) -> dict:
    row = {
        "symbol": symbol,
        "decision": decision,
        "current_price": price,
        "currency": "USD",
        "market": "US",
        "asset_type": extra.pop("asset_type", "Hisse"),
        "participation_status": extra.pop("participation_status", "Uygun"),
        "data_source": extra.pop("data_source", "FMP"),
    }
    row.update(extra)
    return row


def _slice(bucket: str, weight: float) -> EconomicExposure:
    return EconomicExposure(
        exposure_bucket=bucket,
        weight_pct=weight,
        evidence_source=ExposureEvidenceSource.CANONICAL_STATIC_MAPPING,
        confidence=ExposureConfidence.HIGH,
    )


def _current_book() -> PortfolioIntelligenceView:
    return _view(
        [
            _row("CRM", market_value=96683.4, weight_pct=96.6834),
            _row("SPSK", market_value=3316.6, weight_pct=3.3166, asset_class="etf"),
        ]
    )


def _post_spsk_book() -> PortfolioIntelligenceView:
    return _view(
        [
            _row("CRM", market_value=9974.06, weight_pct=99.7406),
            _row("SPSK", market_value=25.94, weight_pct=0.2594, asset_class="etf"),
        ]
    )


def _complete_mix_book() -> PortfolioIntelligenceView:
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


def _plan(view=None, policy=None, candidates=(), amount="100000", hybrid=None, **kwargs):
    enabled = None if hybrid is None else bool(hybrid)
    return allocate_new_money(
        available_amount=Decimal(amount),
        amount_currency="TRY",
        portfolio_view=view or _current_book(),
        policy=policy or _ee_policy(),
        candidates=candidates,
        conversion=_fx(),
        enable_hybrid_exposure_allocation=enabled,
        **kwargs,
    )


def _shadow(unknown: float, known=None):
    return assess_economic_exposure_determinacy(
        targets=CURRENT_TARGETS,
        known_by_layer=known or CURRENT_KNOWN,
        unknown_pct=unknown,
        tolerance_pct=TOL,
        valuation_complete=True,
        unpriced=False,
    )


def _mode(unknown: float, *, enabled=True, known=None, unpriced=False, valuation=True):
    return resolve_hybrid_portfolio_mode(
        policy=resolve_hybrid_allocation_policy(enabled),
        determinacy=_shadow(unknown, known=known),
        valuation_complete=valuation,
        unpriced=unpriced,
        dimension="ECONOMIC_EXPOSURE",
    )


class FlagAndPolicyTests(unittest.TestCase):
    def test_1_flag_absent_is_off(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        self.assertFalse(resolve_hybrid_allocation_policy(None).enabled)
        self.assertFalse(_plan(hybrid=None).hybrid_allocation_active)

    def test_2_flag_false_strict_unchanged(self) -> None:
        off = _plan(hybrid=False)
        self.assertFalse(off.hybrid_allocation_active)
        self.assertEqual(off.total_allocated, Decimal("0"))
        self.assertEqual(off.residual_cash, Decimal("100000"))
        self.assertEqual(first_live_blocker(off.limitations), "EXPOSURE_CLASSIFICATION_INCOMPLETE")
        self.assertNotIn("PORTFOLIO_EXPOSURE_UNSAFE", off.limitations)

    def test_3_flag_true_hybrid_path(self) -> None:
        on = _plan(hybrid=True)
        self.assertTrue(on.hybrid_allocation_active)
        self.assertEqual(on.hybrid_portfolio_mode, HybridPortfolioMode.UNSAFE.value)
        self.assertEqual(first_live_blocker(on.limitations), "PORTFOLIO_EXPOSURE_UNSAFE")

    def test_35_no_production_default_on(self) -> None:
        self.assertFalse(HYBRID_ALLOCATION_ACTIVE)
        self.assertFalse(HybridExposureAllocationPolicy().enabled)
        source = POLICY_MODULE.read_text(encoding="utf-8")
        self.assertIn("enable_hybrid_exposure_allocation: bool = False", source)
        self.assertNotIn("os.environ", source)
        self.assertFalse(os.environ.get("NABI_ENABLE_HYBRID_EXPOSURE_ALLOCATION"))

    def test_33_no_absolute_guard(self) -> None:
        self.assertIsNone(HYBRID_MAX_UNKNOWN_ABSOLUTE_VALUE)
        self.assertIsNone(resolve_hybrid_allocation_policy(True).max_unknown_absolute_value)

    def test_34_drift_tolerance_is_not_ceiling(self) -> None:
        self.assertEqual(HYBRID_MAX_UNKNOWN_PORTFOLIO_PCT, 1.00)
        self.assertNotEqual(HYBRID_MAX_UNKNOWN_PORTFOLIO_PCT, TOL)
        self.assertEqual(_mode(1.00), HybridPortfolioMode.BOUNDED)
        self.assertEqual(_mode(1.0001), HybridPortfolioMode.UNSAFE)


class ModeBoundaryTests(unittest.TestCase):
    def test_4_u0_complete(self) -> None:
        self.assertEqual(_mode(0.0), HybridPortfolioMode.COMPLETE)

    def test_5_u_tiny_bounded(self) -> None:
        self.assertEqual(_mode(0.0001), HybridPortfolioMode.BOUNDED)

    def test_6_u_one_exactly_bounded(self) -> None:
        self.assertEqual(_mode(0.9999), HybridPortfolioMode.BOUNDED)
        self.assertEqual(_mode(1.0000), HybridPortfolioMode.BOUNDED)

    def test_7_u_over_one_unsafe(self) -> None:
        self.assertEqual(_mode(1.0001), HybridPortfolioMode.UNSAFE)
        self.assertEqual(_mode(2.0), HybridPortfolioMode.UNSAFE)
        self.assertEqual(_mode(CURRENT_U), HybridPortfolioMode.UNSAFE)

    def test_8_unsafe_no_allocation(self) -> None:
        plan = _plan(hybrid=True)
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertEqual(plan.recommendations, ())

    def test_missing_valuation_unavailable(self) -> None:
        self.assertEqual(
            _mode(0.2, unpriced=True),
            HybridPortfolioMode.UNAVAILABLE,
        )
        from dataclasses import replace

        row = _row("CRM", market_value=10000, weight_pct=100, price_available=False)
        view = replace(
            _view([]),
            unpriced_position_count=1,
            priced_position_count=0,
            total_position_count=1,
            unpriced_positions=(row,),
        )
        plan = _plan(view=view, hybrid=True)
        self.assertEqual(first_live_blocker(plan.limitations), "PORTFOLIO_EXPOSURE_UNAVAILABLE")


class LayerContractTests(unittest.TestCase):
    def test_9_bounded_robust_uw_selectable(self) -> None:
        intent = select_hybrid_allocation_intent(
            policy=resolve_hybrid_allocation_policy(True),
            determinacy=_shadow(AFTER_SPSK_U),
            dimension="ECONOMIC_EXPOSURE",
        )
        layers = {row.bucket_id for row in intent.underweight_rows}
        self.assertEqual(layers, {"fixed_income", "sukuk", "real_estate", "cash"})
        self.assertTrue(intent.use_robust_layers)
        self.assertFalse(intent.allow_mix_maintenance)

    def test_10_bounded_ambiguous_blocked(self) -> None:
        view = assess_economic_exposure_determinacy(
            targets=(("equity", 75.0), ("sukuk", 25.0)),
            known_by_layer={"equity": 76.5, "sukuk": 22.5},
            unknown_pct=1.0,
            tolerance_pct=2.0,
            valuation_complete=True,
            unpriced=False,
        )
        self.assertEqual(
            {row.layer: row.status.value for row in view.layers}["equity"],
            "AMBIGUOUS",
        )
        intent = select_hybrid_allocation_intent(
            policy=resolve_hybrid_allocation_policy(True),
            determinacy=view,
            dimension="ECONOMIC_EXPOSURE",
        )
        self.assertNotIn("equity", {row.bucket_id for row in intent.underweight_rows})

    def test_11_bounded_on_target_blocked(self) -> None:
        intent = select_hybrid_allocation_intent(
            policy=resolve_hybrid_allocation_policy(True),
            determinacy=_shadow(AFTER_SPSK_U),
            dimension="ECONOMIC_EXPOSURE",
        )
        self.assertFalse(intent.allow_mix_maintenance)
        self.assertNotIn("commodity", {row.bucket_id for row in intent.underweight_rows})
        self.assertNotIn("other", {row.bucket_id for row in intent.underweight_rows})

    def test_12_complete_on_target_mix_preserved(self) -> None:
        off = _plan(view=_complete_mix_book(), policy=_ee_policy(equity=70, sukuk=30), hybrid=False)
        on = _plan(view=_complete_mix_book(), policy=_ee_policy(equity=70, sukuk=30), hybrid=True)
        self.assertEqual(on.hybrid_portfolio_mode, HybridPortfolioMode.COMPLETE.value)
        self.assertEqual(off.recommendations, on.recommendations)
        self.assertEqual(off.total_allocated, on.total_allocated)
        self.assertTrue(on.recommendations)
        self.assertTrue(all(row.reason_code == REASON_MIX_MAINTENANCE for row in on.recommendations))

    def test_13_simple_threshold_false_safe_prevented(self) -> None:
        view = _view(
            [
                _row("CRM", market_value=7650, weight_pct=76.5),
                _row("SPSK", market_value=100, weight_pct=1.0, asset_class="etf"),
                _row("SUKUK1", market_value=2250, weight_pct=22.5, asset_class="sukuk"),
            ]
        )
        plan = _plan(view=view, policy=_ee_policy(equity=75, sukuk=25), hybrid=True)
        self.assertEqual(plan.hybrid_portfolio_mode, HybridPortfolioMode.BOUNDED.value)
        self.assertNotIn("CRM", [row.symbol for row in plan.recommendations])
        self.assertEqual(plan.total_allocated, Decimal("0"))


class FillabilityTests(unittest.TestCase):
    def test_14_no_eligible_fill_residual(self) -> None:
        view = _view(
            [
                _row("CRM", market_value=9000, weight_pct=90),
                _row("SPSK", market_value=50, weight_pct=0.5, asset_class="etf"),
                _row("SUKUK1", market_value=950, weight_pct=9.5, asset_class="sukuk"),
            ]
        )
        plan = _plan(
            view=_view(
                [
                    _row("CRM", market_value=9950, weight_pct=99.5),
                    _row("SPSK", market_value=50, weight_pct=0.5, asset_class="etf"),
                ]
            ),
            policy=_ee_policy(equity=70, sukuk=30),
            hybrid=True,
        )
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertTrue(
            first_live_blocker(plan.limitations).startswith(
                "NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER"
            )
        )
        del view

    def test_15_eligible_fill_runs_downstream_gates(self) -> None:
        plan = _plan(
            view=_view(
                [
                    _row("CRM", market_value=9950, weight_pct=99.5),
                    _row("SPSK", market_value=50, weight_pct=0.5, asset_class="etf"),
                ]
            ),
            policy=_ee_policy(equity=70, sukuk=30),
            candidates=[_candidate("TESTSUK", asset_type="Sukuk")],
            canonical_mappings={"TESTSUK": (_slice("sukuk", 100.0),)},
            hybrid=True,
        )
        self.assertEqual(plan.hybrid_portfolio_mode, HybridPortfolioMode.BOUNDED.value)
        self.assertNotEqual(first_live_blocker(plan.limitations), "PORTFOLIO_EXPOSURE_UNSAFE")
        touched = {row.symbol for row in plan.recommendations} | {row.symbol for row in plan.skipped}
        self.assertIn("TESTSUK", touched)

    def test_a_sukuk_uw_no_asset(self) -> None:
        plan = _plan(
            view=_view(
                [
                    _row("CRM", market_value=9950, weight_pct=99.5),
                    _row("SPSK", market_value=50, weight_pct=0.5, asset_class="etf"),
                ]
            ),
            policy=_ee_policy(equity=70, sukuk=30),
            hybrid=True,
        )
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertEqual(plan.recommendations, ())

    def test_b_sukuk_uw_eligible_test_asset(self) -> None:
        plan = _plan(
            view=_view(
                [
                    _row("CRM", market_value=9000, weight_pct=90),
                    _row("SPSK", market_value=50, weight_pct=0.5, asset_class="etf"),
                    _row("TESTSUK", market_value=950, weight_pct=9.5, asset_class="sukuk"),
                ]
            ),
            policy=_ee_policy(equity=70, sukuk=30),
            canonical_mappings={"TESTSUK": (_slice("sukuk", 100.0),)},
            hybrid=True,
        )
        recs = [row.symbol for row in plan.recommendations]
        skips = {row.symbol: row.reason_code for row in plan.skipped}
        self.assertTrue("TESTSUK" in recs or "TESTSUK" in skips)
        if recs:
            self.assertIn("TESTSUK", recs)

    def test_c_equity_uw_eligible_asset(self) -> None:
        plan = _plan(
            view=_view(
                [
                    _row("SUKUK1", market_value=9950, weight_pct=99.5, asset_class="sukuk"),
                    _row("SPSK", market_value=50, weight_pct=0.5, asset_class="etf"),
                ]
            ),
            policy=_ee_policy(equity=70, sukuk=30),
            candidates=[_candidate("CRM")],
            hybrid=True,
        )
        self.assertTrue(
            any(row.symbol == "CRM" for row in plan.recommendations)
            or any(row.symbol == "CRM" for row in plan.skipped)
        )

    def test_d_ambiguous_must_not_allocate(self) -> None:
        plan = _plan(
            view=_view(
                [
                    _row("CRM", market_value=7650, weight_pct=76.5),
                    _row("SPSK", market_value=100, weight_pct=1.0, asset_class="etf"),
                    _row("SUKUK1", market_value=2250, weight_pct=22.5, asset_class="sukuk"),
                ]
            ),
            policy=_ee_policy(equity=75, sukuk=25),
            candidates=[_candidate("AAPL")],
            hybrid=True,
        )
        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.total_allocated, Decimal("0"))

    def test_e_on_target_u_gt_0_no_mix(self) -> None:
        plan = _plan(
            view=_view(
                [
                    _row("AAPL", market_value=6980, weight_pct=69.8),
                    _row("SUKUK1", market_value=2980, weight_pct=29.8, asset_class="sukuk"),
                    _row("SPSK", market_value=40, weight_pct=0.4, asset_class="etf"),
                ]
            ),
            policy=_ee_policy(equity=70, sukuk=30),
            hybrid=True,
        )
        self.assertEqual(plan.hybrid_portfolio_mode, HybridPortfolioMode.BOUNDED.value)
        self.assertEqual(plan.recommendations, ())
        self.assertIn("NO_ROBUST_UNDERWEIGHT_LAYER", plan.limitations)

    def test_f_on_target_u0_mix_preserved(self) -> None:
        plan = _plan(
            view=_complete_mix_book(),
            policy=_ee_policy(equity=70, sukuk=30),
            hybrid=True,
        )
        self.assertTrue(all(row.reason_code == REASON_MIX_MAINTENANCE for row in plan.recommendations))


class ParticipationFirewallTests(unittest.TestCase):
    def _sukuk_gap_view(self, participation: str, research_allowed=None):
        return _view(
            [
                _row("SUKUK1", market_value=9950, weight_pct=99.5, asset_class="sukuk"),
                _row("SPSK", market_value=50, weight_pct=0.5, asset_class="etf"),
            ]
        ), [_candidate("CRM", participation_status=participation, research_allowed=research_allowed)]

    def test_16_uygun_may_continue(self) -> None:
        view, cands = self._sukuk_gap_view("Uygun")
        plan = _plan(view=view, policy=_ee_policy(equity=70, sukuk=30), candidates=cands, hybrid=True)
        self.assertFalse(
            any(row.symbol == "CRM" and row.reason_code == REASON_PARTICIPATION_BLOCKED for row in plan.skipped)
        )
        self.assertTrue(any(row.symbol == "CRM" for row in (*plan.recommendations, *plan.skipped)))

    def test_17_kontrol_et_blocked(self) -> None:
        view, cands = self._sukuk_gap_view("Kontrol Et")
        plan = _plan(view=view, policy=_ee_policy(equity=70, sukuk=30), candidates=cands, hybrid=True)
        self.assertTrue(
            any(row.symbol == "CRM" and row.reason_code == REASON_PARTICIPATION_BLOCKED for row in plan.skipped)
        )
        self.assertNotIn("CRM", [row.symbol for row in plan.recommendations])

    def test_18_uygun_degil_blocked(self) -> None:
        view, cands = self._sukuk_gap_view("Uygun Değil")
        plan = _plan(view=view, policy=_ee_policy(equity=70, sukuk=30), candidates=cands, hybrid=True)
        self.assertTrue(
            any(row.symbol == "CRM" and row.reason_code == REASON_PARTICIPATION_BLOCKED for row in plan.skipped)
        )
        self.assertNotIn("CRM", [row.symbol for row in plan.recommendations])

    def test_19_research_allowed_false_blocked(self) -> None:
        view, cands = self._sukuk_gap_view("Uygun", research_allowed=False)
        plan = _plan(view=view, policy=_ee_policy(equity=70, sukuk=30), candidates=cands, hybrid=True)
        self.assertTrue(
            any(row.symbol == "CRM" and row.reason_code == REASON_RESEARCH_NOT_ALLOWED for row in plan.skipped)
        )
        self.assertNotIn("CRM", [row.symbol for row in plan.recommendations])


class InferenceAndInvariantTests(unittest.TestCase):
    def test_20_spsk_remains_unknown(self) -> None:
        instrument = classify_instrument_exposure(
            _row("SPSK", market_value=331.66, weight_pct=3.3166, asset_class="etf")
        )
        buckets = {row.exposure_bucket for row in instrument.economic_exposures}
        self.assertIn("unknown", buckets)
        self.assertNotIn("sukuk", buckets)

    def test_21_no_spsk_sukuk_inference(self) -> None:
        for path in (POLICY_MODULE, NEW_MONEY):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("SPSK → sukuk", text)
            self.assertNotIn('"SPSK": "sukuk"', text)

    def test_22_no_spre_reit_inference(self) -> None:
        text = POLICY_MODULE.read_text(encoding="utf-8") + NEW_MONEY.read_text(encoding="utf-8")
        self.assertNotIn("SPRE →", text)
        self.assertNotIn("REIT", text)

    def test_23_no_spwo_international_inference(self) -> None:
        text = POLICY_MODULE.read_text(encoding="utf-8")
        self.assertNotIn("SPWO", text)
        self.assertNotIn("international", text.lower())

    def test_24_no_cash_other_cash_inference(self) -> None:
        self.assertNotIn("Cash&Other", POLICY_MODULE.read_text(encoding="utf-8"))

    def test_25_security_master_not_written(self) -> None:
        text = POLICY_MODULE.read_text(encoding="utf-8")
        self.assertNotIn(".insert(", text)
        self.assertNotIn(".upsert(", text)
        self.assertNotIn("SecurityMasterService().", text)

    def test_26_duplicate_lots_conserved(self) -> None:
        view = _view(
            [
                _row("CRM", market_value=4800, weight_pct=48, position_id="p-crm-a", account_id="a"),
                _row("CRM", market_value=4800, weight_pct=48, position_id="p-crm-b", account_id="b"),
                _row("SPSK", market_value=400, weight_pct=4, asset_class="etf"),
            ]
        )
        off = _plan(view=view, hybrid=False)
        on = _plan(view=view, hybrid=True)
        self.assertEqual(off.total_allocated, on.total_allocated)
        self.assertEqual(len(view.priced_positions), 3)

    def test_27_fund_lookthrough_unchanged(self) -> None:
        self.assertIn("del max_unknown_portfolio_pct", DETERMINACY.read_text(encoding="utf-8"))
        self.assertNotIn("BOUNDED =", DETERMINACY.read_text(encoding="utf-8"))


class CurrentAndSyntheticUatTests(unittest.TestCase):
    def test_28_strict_off_100k_unchanged(self) -> None:
        plan = _plan(hybrid=False)
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertEqual(first_live_blocker(plan.limitations), "EXPOSURE_CLASSIFICATION_INCOMPLETE")

    def test_29_hybrid_on_current_portfolio_unsafe(self) -> None:
        plan = _plan(hybrid=True)
        self.assertGreater(CURRENT_U, 1.00)
        self.assertEqual(plan.hybrid_portfolio_mode, "UNSAFE")
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertEqual(first_live_blocker(plan.limitations), "PORTFOLIO_EXPOSURE_UNSAFE")

    def test_30_post_spsk_synthetic_bounded(self) -> None:
        statuses = {row.layer: row.status for row in _shadow(AFTER_SPSK_U).layers}
        self.assertEqual(statuses["equity"], LayerExposureDeterminacy.ROBUST_OVERWEIGHT)
        self.assertEqual(statuses["fixed_income"], LayerExposureDeterminacy.ROBUST_UNDERWEIGHT)
        self.assertEqual(statuses["sukuk"], LayerExposureDeterminacy.ROBUST_UNDERWEIGHT)
        self.assertEqual(statuses["real_estate"], LayerExposureDeterminacy.ROBUST_UNDERWEIGHT)
        self.assertEqual(statuses["cash"], LayerExposureDeterminacy.ROBUST_UNDERWEIGHT)
        self.assertEqual(statuses["commodity"], LayerExposureDeterminacy.ROBUST_ON_TARGET)
        self.assertEqual(statuses["other"], LayerExposureDeterminacy.ROBUST_ON_TARGET)
        plan = _plan(view=_post_spsk_book(), hybrid=True)
        self.assertEqual(plan.hybrid_portfolio_mode, "BOUNDED")
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertTrue(
            first_live_blocker(plan.limitations).startswith(
                "NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER"
            )
        )
        self.assertNotIn("commodity", [row.layer for row in plan.recommendations])

    def test_31_blocker_precedence(self) -> None:
        self.assertEqual(
            list(HYBRID_LIVE_BLOCKER_PRECEDENCE[:4]),
            [
                "PORTFOLIO_EXPOSURE_UNAVAILABLE",
                "PORTFOLIO_EXPOSURE_UNSAFE",
                "NO_ROBUST_UNDERWEIGHT_LAYER",
                "NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER",
            ],
        )
        unsafe = _plan(hybrid=True)
        self.assertEqual(first_live_blocker(unsafe.limitations), "PORTFOLIO_EXPOSURE_UNSAFE")
        self.assertNotIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", unsafe.limitations)


class AdviserHybridTests(unittest.TestCase):
    def test_32_adviser_active_flag_correct(self) -> None:
        off = build_nabi_adviser_context(
            "100.000 TL ek param var",
            portfolio_view=_current_book(),
            policy=_ee_policy(),
            goal_dashboard=SimpleNamespace(
                fx_schedule=SimpleNamespace(usdtry_for_year=lambda year: Decimal("30")),
                as_of_date=SimpleNamespace(year=2026),
            ),
        )
        self.assertFalse(off.economic_exposure_context["hybrid_allocation_active"])
        self.assertEqual(off.economic_exposure_context["portfolio_mode"], "STRICT")
        self.assertEqual(
            off.economic_exposure_context["hybrid_policy"]["max_unknown_portfolio_pct"],
            1.00,
        )
        self.assertIsNone(off.economic_exposure_context["hybrid_policy"]["absolute_guard"])
        self.assertFalse(off.economic_exposure_context["hybrid_policy"]["bounded_mix_maintenance"])
        self.assertEqual(off.economic_exposure_context["live_blocker"], "EXPOSURE_CLASSIFICATION_INCOMPLETE")
        self.assertIn("tamamlanmadığı", off.canonical_answer)

        on = build_nabi_adviser_context(
            "100.000 TL ek param var",
            portfolio_view=_current_book(),
            policy=_ee_policy(),
            enable_hybrid_exposure_allocation=True,
            goal_dashboard=SimpleNamespace(
                fx_schedule=SimpleNamespace(usdtry_for_year=lambda year: Decimal("30")),
                as_of_date=SimpleNamespace(year=2026),
            ),
        )
        self.assertTrue(on.economic_exposure_context["hybrid_allocation_active"])
        self.assertEqual(on.economic_exposure_context["portfolio_mode"], "UNSAFE")
        self.assertEqual(on.economic_exposure_context["live_blocker"], "PORTFOLIO_EXPOSURE_UNSAFE")
        self.assertEqual(on.new_money_context["total_allocated"], "0")
        self.assertNotIn("dağıtım:", on.canonical_answer.lower())
        self.assertFalse(HYBRID_BOUNDED_MIX_MAINTENANCE)


class ShadowReuseTests(unittest.TestCase):
    def test_no_duplicate_bound_math(self) -> None:
        text = POLICY_MODULE.read_text(encoding="utf-8")
        self.assertIn("ceiling_allows_bound_evaluation", text)
        self.assertNotIn("known_pct + unknown_pct", text)
        self.assertNotIn("target_pct - tolerance_pct", text)
        self.assertIn("select_hybrid_allocation_intent", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertNotIn("known_pct + unknown_pct", NEW_MONEY.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
