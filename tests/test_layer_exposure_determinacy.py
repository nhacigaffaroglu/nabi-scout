from __future__ import annotations

import math
import unittest
from decimal import Decimal
from pathlib import Path

from services.layer_exposure_determinacy import (
    EVALUATION_MODE_SHADOW,
    MASS_OVERFLOW_REASON,
    WEIGHT_QUANT,
    ExposureDeterminacyView,
    LayerExposureDeterminacy,
    ShadowEvaluationMode,
    assess_economic_exposure_determinacy,
    assess_layer_uncertainty,
)
from services.portfolio_allocation_intelligence import (
    AllocationDimension,
    DriftStatus,
    build_allocation_intelligence,
)
from services.portfolio_economic_exposure import build_economic_exposure
from services.wealth_new_money_allocation import (
    _allocation_buckets_from_exposure,
    allocate_new_money,
)
from tests.test_economic_exposure_wiring import (
    _ee_policy,
    _lot,
    _sm_aapl,
    _spus_snapshot,
)
from tests.test_portfolio_economic_exposure import (
    _equity,
    _etf,
    _snapshot,
    _view_from_rows,
)
from tests.test_wealth_new_money_allocation import _fx, _row, _view
from services.fund_intelligence_contract import FundHoldingRow


MODULE = Path("services/layer_exposure_determinacy.py")
ALLOCATION = Path("services/portfolio_allocation_intelligence.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
ADVISER = Path("services/nabi_adviser_context.py")
EXPOSURE = Path("services/portfolio_economic_exposure.py")
FORBIDDEN = (
    "supabase",
    "streamlit",
    "openai",
    "FMPClient",
    "fmp_client",
    "SECFinancialClient",
    "AlphaVantage",
)
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
CURRENT_D = 2.0


def _layer(**kwargs):
    defaults = dict(
        layer="equity",
        known_pct=96.6857,
        unknown_pct=0.0,
        target_pct=75.0,
        tolerance_pct=2.0,
    )
    defaults.update(kwargs)
    return assess_layer_uncertainty(**defaults)


def _current_shadow():
    return assess_economic_exposure_determinacy(
        targets=CURRENT_TARGETS,
        known_by_layer=CURRENT_KNOWN,
        unknown_pct=CURRENT_U,
        tolerance_pct=CURRENT_D,
        valuation_complete=True,
        unpriced=False,
        max_unknown_portfolio_pct=None,
    )


class PureModuleTests(unittest.TestCase):
    def test_40_no_db_or_provider_dependency(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        lowered = source.lower()
        for token in FORBIDDEN:
            self.assertNotIn(token.lower(), lowered)
        self.assertNotIn("streamlit", lowered)
        self.assertNotIn(".insert(", source)

    def test_12_no_arbitrary_ceiling_exists(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        self.assertIn("del max_unknown_portfolio_pct", source)
        self.assertNotIn("BOUNDED =", source)
        self.assertNotIn("UNSAFE =", source)
        self.assertNotRegex(source, r"max_unknown_portfolio_pct\s*=\s*[0-9]")

    def test_35_simple_threshold_absent(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("valuation_complete = True", source)
        self.assertNotIn("unknown_pct <=", source)
        self.assertNotIn("U <=", source)

    def test_11_no_ceiling_required_in_shadow_mode(self) -> None:
        view = _current_shadow()
        self.assertEqual(view.evaluation_mode, ShadowEvaluationMode.SHADOW_EVALUATED)
        self.assertIsNone(view.max_unknown_portfolio_pct)
        self.assertEqual(view.evaluation_mode.value, EVALUATION_MODE_SHADOW)

    def test_42_classification_complete_only_when_u_zero_and_valued(self) -> None:
        complete = assess_economic_exposure_determinacy(
            targets=(("equity", 100.0),),
            known_by_layer={"equity": 100.0},
            unknown_pct=0.0,
            tolerance_pct=2.0,
            valuation_complete=True,
        )
        self.assertTrue(complete.classification_complete)
        incomplete = _current_shadow()
        self.assertFalse(incomplete.classification_complete)
        unpriced = assess_economic_exposure_determinacy(
            targets=(("equity", 100.0),),
            known_by_layer={"equity": 100.0},
            unknown_pct=0.0,
            tolerance_pct=2.0,
            valuation_complete=False,
        )
        self.assertFalse(unpriced.classification_complete)


class EquationTests(unittest.TestCase):
    def test_1_u_zero_maps_exactly_to_canonical_drift(self) -> None:
        cases = (
            (60.0, 75.0, 2.0, LayerExposureDeterminacy.ROBUST_UNDERWEIGHT, DriftStatus.UNDERWEIGHT),
            (74.0, 75.0, 2.0, LayerExposureDeterminacy.ROBUST_ON_TARGET, DriftStatus.ON_TARGET),
            (75.0, 75.0, 2.0, LayerExposureDeterminacy.ROBUST_ON_TARGET, DriftStatus.ON_TARGET),
            (77.0, 75.0, 2.0, LayerExposureDeterminacy.ROBUST_ON_TARGET, DriftStatus.ON_TARGET),
            (77.01, 75.0, 2.0, LayerExposureDeterminacy.ROBUST_OVERWEIGHT, DriftStatus.OVERWEIGHT),
            (96.6857, 75.0, 2.0, LayerExposureDeterminacy.ROBUST_OVERWEIGHT, DriftStatus.OVERWEIGHT),
        )
        for known, target, tolerance, robust, drift in cases:
            row = _layer(known_pct=known, unknown_pct=0.0, target_pct=target, tolerance_pct=tolerance)
            actual = known
            lower = target - tolerance
            upper = target + tolerance
            if actual < lower:
                expected_drift = DriftStatus.UNDERWEIGHT
            elif actual > upper:
                expected_drift = DriftStatus.OVERWEIGHT
            else:
                expected_drift = DriftStatus.ON_TARGET
            self.assertEqual(expected_drift, drift)
            self.assertEqual(row.status, robust)

    def test_2_tiny_u_does_not_make_robust_layer_ambiguous(self) -> None:
        row = _layer(known_pct=96.6857, unknown_pct=0.01, target_pct=75.0, tolerance_pct=2.0)
        self.assertEqual(row.status, LayerExposureDeterminacy.ROBUST_OVERWEIGHT)

    def test_3_ambiguous_layer_detected(self) -> None:
        row = _layer(layer="fixed_income", known_pct=0.0, unknown_pct=3.3166, target_pct=5.0)
        self.assertEqual(row.status, LayerExposureDeterminacy.AMBIGUOUS)

    def test_4_robust_uw_iff_max_below_lower(self) -> None:
        row = _layer(layer="sukuk", known_pct=0.0, unknown_pct=3.3166, target_pct=10.0)
        self.assertLess(row.max_pct, row.lower_bound_pct)
        self.assertEqual(row.status, LayerExposureDeterminacy.ROBUST_UNDERWEIGHT)
        on_boundary = _layer(layer="sukuk", known_pct=0.0, unknown_pct=8.0, target_pct=10.0)
        self.assertEqual(on_boundary.max_pct, on_boundary.lower_bound_pct)
        self.assertEqual(on_boundary.status, LayerExposureDeterminacy.AMBIGUOUS)

    def test_5_robust_ow_iff_min_above_upper(self) -> None:
        row = _layer(known_pct=96.6857, unknown_pct=3.3166)
        self.assertGreater(row.min_pct, row.upper_bound_pct)
        self.assertEqual(row.status, LayerExposureDeterminacy.ROBUST_OVERWEIGHT)
        on_upper = _layer(known_pct=77.0, unknown_pct=0.0)
        self.assertEqual(on_upper.status, LayerExposureDeterminacy.ROBUST_ON_TARGET)

    def test_6_robust_on_target_requires_entire_interval_inside_band(self) -> None:
        row = _layer(known_pct=74.0, unknown_pct=2.0, target_pct=75.0)
        self.assertEqual(row.status, LayerExposureDeterminacy.ROBUST_ON_TARGET)
        spilled = _layer(known_pct=74.0, unknown_pct=4.0, target_pct=75.0)
        self.assertEqual(spilled.status, LayerExposureDeterminacy.AMBIGUOUS)

    def test_7_lower_boundary_inclusive_on_target(self) -> None:
        row = _layer(known_pct=73.0, unknown_pct=0.0, target_pct=75.0, tolerance_pct=2.0)
        self.assertEqual(row.min_pct, row.lower_bound_pct)
        self.assertEqual(row.status, LayerExposureDeterminacy.ROBUST_ON_TARGET)

    def test_8_upper_boundary_inclusive_on_target(self) -> None:
        row = _layer(known_pct=77.0, unknown_pct=0.0, target_pct=75.0, tolerance_pct=2.0)
        self.assertEqual(row.max_pct, row.upper_bound_pct)
        self.assertEqual(row.status, LayerExposureDeterminacy.ROBUST_ON_TARGET)

    def test_9_target_zero(self) -> None:
        inside = _layer(layer="commodity", known_pct=0.0, unknown_pct=2.0, target_pct=0.0)
        self.assertEqual(inside.status, LayerExposureDeterminacy.ROBUST_ON_TARGET)
        spill = _layer(layer="commodity", known_pct=0.0, unknown_pct=3.3166, target_pct=0.0)
        self.assertEqual(spill.status, LayerExposureDeterminacy.AMBIGUOUS)

    def test_10_target_one_hundred(self) -> None:
        row = _layer(known_pct=96.6857, unknown_pct=0.0, target_pct=100.0)
        self.assertEqual(row.status, LayerExposureDeterminacy.ROBUST_UNDERWEIGHT)
        full = _layer(known_pct=100.0, unknown_pct=0.0, target_pct=100.0)
        self.assertEqual(full.status, LayerExposureDeterminacy.ROBUST_ON_TARGET)


class FailClosedTests(unittest.TestCase):
    def test_13_invalid_u_unavailable(self) -> None:
        row = _layer(unknown_pct=-0.1)
        self.assertEqual(row.status, LayerExposureDeterminacy.UNAVAILABLE)
        self.assertIn("INVALID_UNKNOWN", row.reason_codes)

    def test_14_nan_unavailable(self) -> None:
        for key in ("known_pct", "unknown_pct", "target_pct", "tolerance_pct"):
            row = _layer(**{key: math.nan})
            self.assertEqual(row.status, LayerExposureDeterminacy.UNAVAILABLE)

    def test_15_u_over_100_unavailable(self) -> None:
        row = _layer(unknown_pct=100.01)
        self.assertEqual(row.status, LayerExposureDeterminacy.UNAVAILABLE)
        self.assertIn("UNKNOWN_EXCEEDS_100", row.reason_codes)

    def test_16_unpriced_valuation_unavailable(self) -> None:
        view = assess_economic_exposure_determinacy(
            targets=CURRENT_TARGETS,
            known_by_layer=CURRENT_KNOWN,
            unknown_pct=CURRENT_U,
            tolerance_pct=CURRENT_D,
            valuation_complete=True,
            unpriced=True,
        )
        self.assertEqual(view.evaluation_mode, ShadowEvaluationMode.UNAVAILABLE)
        self.assertTrue(all(row.status == LayerExposureDeterminacy.UNAVAILABLE for row in view.layers))

    def test_missing_target_unavailable(self) -> None:
        row = assess_layer_uncertainty(
            layer="sukuk",
            known_pct=0.0,
            unknown_pct=1.0,
            target_pct=None,
            tolerance_pct=2.0,
        )
        self.assertEqual(row.status, LayerExposureDeterminacy.UNAVAILABLE)
        self.assertIn("MISSING_TARGET", row.reason_codes)

    def test_36_ku_over_100_not_clamped(self) -> None:
        row = _layer(known_pct=96.6857, unknown_pct=3.3166)
        self.assertGreater(row.max_pct, 100.0)
        self.assertAlmostEqual(row.max_pct, 100.0023, places=4)

    def test_37_mass_overflow_reason_emitted(self) -> None:
        row = _layer(known_pct=96.6857, unknown_pct=3.3166)
        self.assertIn(MASS_OVERFLOW_REASON, row.reason_codes)
        view = _current_shadow()
        self.assertIn(MASS_OVERFLOW_REASON, view.reason_codes)

    def test_17_unknown_never_reclassified(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        self.assertIn("UNKNOWN is not assigned", source)
        row = _layer(layer="sukuk", known_pct=0.0, unknown_pct=3.3166, target_pct=10.0)
        self.assertEqual(row.known_pct, 0.0)
        self.assertEqual(row.unknown_pct, 3.3166)


class CurrentPortfolioShadowTests(unittest.TestCase):
    def test_38_current_portfolio_expected_shadow_statuses(self) -> None:
        view = _current_shadow()
        by_id = {row.layer: row.status for row in view.layers}
        self.assertEqual(by_id["equity"], LayerExposureDeterminacy.ROBUST_OVERWEIGHT)
        self.assertEqual(by_id["sukuk"], LayerExposureDeterminacy.ROBUST_UNDERWEIGHT)
        for layer in ("fixed_income", "real_estate", "cash", "commodity", "other"):
            self.assertEqual(by_id[layer], LayerExposureDeterminacy.AMBIGUOUS)

    def test_39_shadow_result_deterministic(self) -> None:
        first = _current_shadow().to_dict()
        second = _current_shadow().to_dict()
        self.assertEqual(first, second)

    def test_41_serialization_stable(self) -> None:
        payload = _current_shadow().to_dict()
        self.assertEqual(payload["evaluation_mode"], "SHADOW_EVALUATED")
        self.assertIn("layers", payload)
        self.assertEqual(len(payload["layers"]), 7)
        restored = ExposureDeterminacyView(
            evaluation_mode=ShadowEvaluationMode.SHADOW_EVALUATED,
            classification_complete=False,
            known_pct=payload["known_pct"],
            unknown_pct=payload["unknown_pct"],
            layers=_current_shadow().layers,
            reason_codes=tuple(payload["reason_codes"]),
        )
        self.assertEqual(restored.to_dict()["unknown_pct"], payload["unknown_pct"])


class IntegrationTests(unittest.TestCase):
    def test_23_production_drift_remains_indeterminate(self) -> None:
        exposure = build_economic_exposure(
            _view_from_rows(
                [
                    _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk"),
                    _lot("SPUS", 1013.94, position_id="p-b", account_id="midas"),
                    _equity("AAPL", 80000.0),
                ]
            ),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        intelligence = build_allocation_intelligence(
            _view_from_rows(
                [
                    _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk"),
                    _lot("SPUS", 1013.94, position_id="p-b", account_id="midas"),
                    _equity("AAPL", 80000.0),
                ]
            ),
            policy=_ee_policy(),
            exposure_buckets=_allocation_buckets_from_exposure(exposure),
        )
        statuses = {
            row.status
            for row in intelligence.drift
            if row.dimension == AllocationDimension.ECONOMIC_EXPOSURE
        }
        self.assertEqual(statuses, {DriftStatus.INDETERMINATE})
        self.assertIsNotNone(intelligence.exposure_determinacy)
        shadow = {row.layer: row.status for row in intelligence.exposure_determinacy.layers}
        self.assertEqual(shadow["equity"], LayerExposureDeterminacy.ROBUST_OVERWEIGHT)
        self.assertEqual(shadow["sukuk"], LayerExposureDeterminacy.ROBUST_UNDERWEIGHT)

    def test_31_shadow_field_is_additive(self) -> None:
        view = build_allocation_intelligence(
            _view_from_rows([_equity("AAPL", 100.0)]),
            policy=_ee_policy(),
        )
        self.assertTrue(hasattr(view, "exposure_determinacy"))
        self.assertTrue(hasattr(view, "drift"))
        payload = view.to_dict()
        self.assertIn("drift_status", payload)
        self.assertIn("exposure_determinacy", payload)

    def test_21_new_money_does_not_consume_robust_status(self) -> None:
        source = NEW_MONEY.read_text(encoding="utf-8")
        self.assertIn("select_hybrid_allocation_intent", source)
        self.assertIn("DriftStatus.UNDERWEIGHT", source)
        self.assertIn("enable_hybrid_exposure_allocation: Optional[bool] = None", source)
        self.assertNotIn("known_pct + unknown_pct", source)

    def test_22_robust_uw_does_not_create_allocation(self) -> None:
        plan = allocate_new_money(
            available_amount=Decimal("100000"),
            amount_currency="TRY",
            portfolio_view=_view(
                [
                    _row("HLAL", market_value=5633, weight_pct=85, asset_class="etf"),
                    _row("AAPL", market_value=1000, weight_pct=15, participation="Uygun Değil"),
                ]
            ),
            policy=_ee_policy(),
            conversion=_fx(),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", plan.limitations)

    def test_18_19_20_participation_unaffected(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("Participation", source)
        self.assertNotIn("Uygun", source)
        self.assertNotIn("Kontrol Et", source)
        blocked = allocate_new_money(
            available_amount=Decimal("100000"),
            amount_currency="TRY",
            portfolio_view=_view(
                [_row("AAPL", market_value=10000, weight_pct=100, participation="Kontrol Et")]
            ),
            policy=_ee_policy(),
            conversion=_fx(),
        )
        self.assertTrue(any(row.reason_code == "PARTICIPATION_BLOCKED" for row in blocked.skipped))

    def test_24_duplicate_lots_still_conserve(self) -> None:
        exposure = build_economic_exposure(
            _view_from_rows(
                [
                    _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk"),
                    _lot("SPUS", 1013.94, position_id="p-b", account_id="midas"),
                ]
            ),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        lots = [row for row in exposure.instruments if row.symbol == "SPUS"]
        self.assertEqual(len(lots), 2)
        self.assertAlmostEqual(sum(float(row.observable_market_value or 0) for row in lots), 6646.94, places=2)

    def test_25_26_official_holdings_and_security_master_still_used(self) -> None:
        allocation = ALLOCATION.read_text(encoding="utf-8")
        self.assertIn("assess_economic_exposure_determinacy", allocation)
        self.assertIn("max_unknown_portfolio_pct=None", allocation)
        exposure_src = EXPOSURE.read_text(encoding="utf-8")
        self.assertIn("PERSISTED_HOLDINGS_LOOKTHROUGH", exposure_src)
        new_money = NEW_MONEY.read_text(encoding="utf-8")
        self.assertIn("security_master=security_master", new_money)

    def test_27_30_no_inference_in_shadow_engine(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        for token in ("SPSK", "SPRE", "SPWO", "REIT", "Cash&Other", "sukuk inference"):
            self.assertNotIn(token, source)
        snapshot = {
            "SPSK": _snapshot("SPSK", (FundHoldingRow("X", "Bond", 100.0, None, None, None),)),
            "SPRE": _snapshot("SPRE", (FundHoldingRow("O", "Realty Income REIT", 100.0, None, None, None),)),
            "SPWO": _snapshot("SPWO", (FundHoldingRow("NESN", "Nestle", 100.0, None, None, None),)),
            "SPUS": _snapshot(
                "SPUS",
                (
                    FundHoldingRow("AAPL", "Apple", 99.72, None, None, None),
                    FundHoldingRow("CASH&OTHER", "Cash & Other", 0.28, None, None, None),
                ),
            ),
        }
        view = build_economic_exposure(
            _view_from_rows(
                [_etf("SPSK", 40), _etf("SPRE", 20), _etf("SPWO", 20), _etf("SPUS", 20)]
            ),
            fund_snapshots=snapshot,
            security_master=_sm_aapl(),
        )
        unknown = next(row for row in view.buckets if row.bucket_id == "unknown")
        self.assertIn("SPSK", unknown.contributing_symbols)
        self.assertIn("SPRE", unknown.contributing_symbols)
        self.assertIn("SPWO", unknown.contributing_symbols)
        real_estate = next(row for row in view.buckets if row.bucket_id == "real_estate")
        self.assertFalse(real_estate.contributing_symbols)
        spus = next(row for row in view.instruments if row.symbol == "SPUS")
        self.assertTrue(any(item.exposure_bucket == "unknown" for item in spus.economic_exposures))
        self.assertFalse(any(item.exposure_bucket == "cash" for item in spus.economic_exposures))

    def test_32_adviser_production_blocker_unchanged(self) -> None:
        from services.nabi_adviser_context import build_nabi_adviser_context
        from types import SimpleNamespace

        context = build_nabi_adviser_context(
            "100.000 TL ek param var",
            portfolio_view=_view([_row("HLAL", market_value=1000, weight_pct=100, asset_class="etf")]),
            policy=_ee_policy(),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
            goal_dashboard=SimpleNamespace(
                fx_schedule=SimpleNamespace(usdtry_for_year=lambda year: Decimal("51")),
                as_of_date=SimpleNamespace(year=2026),
            ),
        )
        self.assertEqual(context.new_money_context["total_allocated"], "0")
        self.assertEqual(context.new_money_context["residual_cash"], "100000")
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", context.new_money_context["limitations"])
        self.assertNotIn("exposure_determinacy", context.new_money_context)
        self.assertNotIn("ROBUST_UNDERWEIGHT", str(context.new_money_context))

    def test_33_34_mass_and_issuer_rounding_remain_separate(self) -> None:
        exposure_src = EXPOSURE.read_text(encoding="utf-8")
        self.assertIn("ISSUER_WEIGHT_ROUNDING_BAND_PCT", exposure_src)
        self.assertNotIn("ISSUER_WEIGHT_ROUNDING_BAND_PCT", MODULE.read_text(encoding="utf-8"))
        self.assertEqual(WEIGHT_QUANT, 4)

    def test_43_new_money_output_identical_shape(self) -> None:
        kwargs = dict(
            available_amount=Decimal("100000"),
            amount_currency="TRY",
            portfolio_view=_view(
                [_row("HLAL", market_value=5633, weight_pct=100, asset_class="etf")]
            ),
            policy=_ee_policy(),
            conversion=_fx(),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        first = allocate_new_money(**kwargs)
        second = allocate_new_money(**kwargs)
        self.assertEqual(first.total_allocated, second.total_allocated)
        self.assertEqual(first.residual_cash, second.residual_cash)
        self.assertEqual(first.limitations, second.limitations)
        self.assertEqual(first.total_allocated, Decimal("0"))
        self.assertEqual(first.residual_cash, Decimal("100000"))


if __name__ == "__main__":
    unittest.main()
