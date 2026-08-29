from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from services.exposure_determinacy_diagnostics import (
    ABSOLUTE_GUARD_CANDIDATES,
    CEILING_CANDIDATES_PCT,
    HYBRID_ALLOCATION_ACTIVE,
    HYBRID_BLOCKER_PRECEDENCE,
    LIVE_BLOCKER_INCOMPLETE,
    MIX_MAINTENANCE_RECOMMENDATION,
    SHADOW_BLOCKER_NO_FILL,
    absolute_guard_allows,
    build_exposure_diagnostics,
    calibrate_book,
    ceiling_allows_bound_evaluation,
    combined_guard_unsafe,
    eligible_fill_assets,
    evaluate_ceiling_candidates,
    unknown_contributors_from_exposure,
)
from services.layer_exposure_determinacy import (
    LayerExposureDeterminacy,
    assess_economic_exposure_determinacy,
)
from services.nabi_adviser_context import build_nabi_adviser_context
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


DIAG = Path("services/exposure_determinacy_diagnostics.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
ADVISER = Path("services/nabi_adviser_context.py")
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


def _current_determinacy(*, unknown=CURRENT_U, known=None):
    return assess_economic_exposure_determinacy(
        targets=CURRENT_TARGETS,
        known_by_layer=known or CURRENT_KNOWN,
        unknown_pct=unknown,
        tolerance_pct=TOL,
        valuation_complete=True,
    )


def _two_lot_exposure():
    return build_economic_exposure(
        _view_from_rows(
            [
                _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk"),
                _lot("SPUS", 1013.94, position_id="p-b", account_id="midas"),
                _equity("CRM", 80000.0),
            ]
        ),
        fund_snapshots=_spus_snapshot(),
        security_master=_sm_aapl(),
    )


class CeilingPureTests(unittest.TestCase):
    def test_7_8_no_ceiling_activated_and_none_is_unevaluated(self) -> None:
        self.assertIsNone(ceiling_allows_bound_evaluation(3.3166, None))
        self.assertFalse(HYBRID_ALLOCATION_ACTIVE)
        source = DETERMINACY.read_text(encoding="utf-8")
        self.assertIn("del max_unknown_portfolio_pct", source)

    def test_9_ceiling_equality_is_inclusive(self) -> None:
        self.assertTrue(ceiling_allows_bound_evaluation(1.00, 1.00))
        self.assertFalse(ceiling_allows_bound_evaluation(1.0001, 1.00))
        self.assertTrue(ceiling_allows_bound_evaluation(0.25, 0.25))

    def test_10_simple_threshold_does_not_override_ambiguous(self) -> None:
        case = calibrate_book(
            unknown_pct=1.8,
            known_by_layer={"equity": 76.5, "sukuk": 0.0, "cash": 0.0},
            targets=(("equity", 75.0), ("sukuk", 10.0), ("cash", 15.0)),
            tolerance_pct=2.0,
            simple_threshold=2.0,
        )
        self.assertEqual(case["statuses"]["equity"], "AMBIGUOUS")
        self.assertTrue(case["simple_threshold_false_safe"])
        self.assertTrue(case["strict_blocks"])

    def test_current_and_after_spsk_ceiling_table(self) -> None:
        current = dict(evaluate_ceiling_candidates(CURRENT_U))
        after = dict(evaluate_ceiling_candidates(AFTER_SPSK_U))
        self.assertEqual(
            [current[item] for item in CEILING_CANDIDATES_PCT],
            [False, False, False, False, False, True, True],
        )
        self.assertEqual(
            [after[item] for item in CEILING_CANDIDATES_PCT],
            [False, True, True, True, True, True, True],
        )


class CalibrationReplayTests(unittest.TestCase):
    def test_synthetic_u_ladder_and_boundary(self) -> None:
        cases = []
        for unknown in (0.0, 0.02, 0.25, 0.50, 1.00, 2.00, 3.3166, 5.00, 10.00):
            known = {"equity": 100.0 - unknown, **{key: 0.0 for key in CURRENT_KNOWN if key != "equity"}}
            cases.append(
                calibrate_book(
                    unknown_pct=unknown,
                    known_by_layer=known,
                    targets=CURRENT_TARGETS,
                    tolerance_pct=TOL,
                    simple_threshold=2.0,
                )
            )
        self.assertFalse(cases[0]["strict_blocks"])
        self.assertTrue(all(row["strict_blocks"] for row in cases[1:]))
        self.assertTrue(cases[6]["has_robust_underweight"])
        self.assertIn("sukuk", cases[6]["robust_underweight"])
        self.assertGreaterEqual(cases[6]["ambiguous_count"], 4)
        self.assertTrue(cases[5]["simple_threshold_complete"])
        self.assertFalse(cases[5]["simple_threshold_false_safe"])
        boundary = calibrate_book(
            unknown_pct=1.8,
            known_by_layer={"equity": 76.5, "sukuk": 0.0, "fixed_income": 21.7},
            targets=(("equity", 75.0), ("sukuk", 10.0), ("fixed_income", 15.0)),
            tolerance_pct=2.0,
            simple_threshold=2.0,
        )
        self.assertTrue(boundary["simple_threshold_false_safe"])


class ContributorAndFillTests(unittest.TestCase):
    def test_3_unknown_contributors_are_lot_aware(self) -> None:
        exposure = _two_lot_exposure()
        contrib = {row.symbol: row for row in unknown_contributors_from_exposure(exposure)}
        self.assertEqual(contrib["SPUS"].lot_count, 2)
        self.assertGreater(contrib["SPUS"].unknown_market_value, 0)

    def test_11_12_spsk_unresolved_and_resolution_does_not_classify(self) -> None:
        source = DIAG.read_text(encoding="utf-8")
        self.assertNotIn("SPSK → sukuk", source)
        after = _current_determinacy(unknown=AFTER_SPSK_U)
        self.assertAlmostEqual(after.unknown_pct or 0, AFTER_SPSK_U)
        self.assertEqual(
            {row.layer: row.status for row in after.layers}["sukuk"],
            LayerExposureDeterminacy.ROBUST_UNDERWEIGHT,
        )
        self.assertEqual(after.layers[0].known_pct, 96.6857)

    def test_13_15_fillability_uses_canonical_mappings_no_inferred_sukuk(self) -> None:
        exposure = build_economic_exposure(
            _view_from_rows(
                [
                    _etf("SPUS", 50),
                    _etf("SPSK", 30),
                    _equity("CRM", 20),
                ]
            ),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        fills = eligible_fill_assets(
            exposure.instruments,
            extra_symbols=(
                {"symbol": "CRM", "participation_status": "Uygun"},
            ),
        )
        by_symbol = {row.symbol: row.layers for row in fills}
        self.assertIn("equity", by_symbol["SPUS"])
        self.assertIn("CRM", by_symbol)
        self.assertEqual(by_symbol["SPSK"], ())
        self.assertNotIn("sukuk", by_symbol["SPSK"])

    def test_16_17_no_reit_or_international_inference(self) -> None:
        source = DIAG.read_text(encoding="utf-8")
        self.assertNotIn("REIT", source)
        snapshot = {
            "SPRE": _snapshot("SPRE", (FundHoldingRow("O", "Realty Income REIT", 100.0, None, None, None),)),
            "SPWO": _snapshot("SPWO", (FundHoldingRow("NESN", "Nestle", 100.0, None, None, None),)),
        }
        view = build_economic_exposure(
            _view_from_rows([_etf("SPRE", 50), _etf("SPWO", 50)]),
            fund_snapshots=snapshot,
        )
        real_estate = next(row for row in view.buckets if row.bucket_id == "real_estate")
        self.assertFalse(real_estate.contributing_symbols)


class AdviserAndAllocationTests(unittest.TestCase):
    def test_1_2_adviser_context_has_shadow_and_production_fields(self) -> None:
        context = build_nabi_adviser_context(
            "100.000 TL ek param var",
            portfolio_view=_view(
                [
                    _row("SPUS", market_value=5633, weight_pct=85, asset_class="etf"),
                    _row("CRM", market_value=1000, weight_pct=15, participation="Uygun"),
                ]
            ),
            policy=_ee_policy(),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
            candidates=[{"symbol": "CRM", "participation_status": "Uygun"}],
            goal_dashboard=SimpleNamespace(
                fx_schedule=SimpleNamespace(usdtry_for_year=lambda year: Decimal("51")),
                as_of_date=SimpleNamespace(year=2026),
            ),
        )
        block = context.economic_exposure_context
        self.assertIsNotNone(block)
        self.assertIn("production_completeness", block)
        self.assertIn("shadow_evaluation", block)
        self.assertFalse(block["hybrid_allocation_active"])
        self.assertIn("unknown_contributors", block)
        self.assertIn("layers", block)
        self.assertIn("production_status", block["layers"][0])
        self.assertIn("robust_status", block["layers"][0])
        self.assertEqual(context.new_money_context["total_allocated"], "0")
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", context.new_money_context["limitations"])
        self.assertNotIn("ROBUST_UNDERWEIGHT", str(context.new_money_context))
        self.assertIn(
            "tamamlanmadığı",
            context.canonical_answer,
        )

    def test_4_5_6_20_live_allocation_and_shadow_next_blocker(self) -> None:
        exposure = _two_lot_exposure()
        intelligence = build_allocation_intelligence(
            _view_from_rows(
                [
                    _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk"),
                    _lot("SPUS", 1013.94, position_id="p-b", account_id="midas"),
                    _equity("CRM", 80000.0),
                ]
            ),
            policy=_ee_policy(),
            exposure_buckets=_allocation_buckets_from_exposure(exposure),
            exposure_view=exposure,
            candidates=[{"symbol": "CRM", "participation_status": "Uygun"}],
        )
        self.assertEqual(
            {
                row.status
                for row in intelligence.drift
                if row.dimension == AllocationDimension.ECONOMIC_EXPOSURE
            },
            {DriftStatus.INDETERMINATE},
        )
        diag = intelligence.exposure_diagnostics
        self.assertIsNotNone(diag)
        self.assertEqual(diag.live_blocker, LIVE_BLOCKER_INCOMPLETE)
        self.assertTrue(diag.shadow_next_blocker.startswith(SHADOW_BLOCKER_NO_FILL))
        self.assertIn("sukuk", diag.unfillable_robust_underweight_layers)
        self.assertEqual(diag.fillable_robust_underweight_layers, ())
        plan = allocate_new_money(
            available_amount=Decimal("100000"),
            amount_currency="TRY",
            portfolio_view=_view(
                [_row("SPUS", market_value=5633, weight_pct=100, asset_class="etf")]
            ),
            policy=_ee_policy(),
            conversion=_fx(),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", plan.limitations)

    def test_14_18_participation_and_mix_maintenance_not_in_production(self) -> None:
        self.assertNotIn("ROBUST_UNDERWEIGHT", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertNotIn("exposure_diagnostics", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertEqual(MIX_MAINTENANCE_RECOMMENDATION, "OPTION_C_U0_ONLY")
        self.assertNotIn(MIX_MAINTENANCE_RECOMMENDATION, NEW_MONEY.read_text(encoding="utf-8"))

    def test_19_blocker_hierarchy_deterministic(self) -> None:
        self.assertEqual(HYBRID_BLOCKER_PRECEDENCE[0], "PORTFOLIO_EXPOSURE_UNSAFE")
        self.assertLess(
            HYBRID_BLOCKER_PRECEDENCE.index(SHADOW_BLOCKER_NO_FILL),
            HYBRID_BLOCKER_PRECEDENCE.index("PARTICIPATION_BLOCKED"),
        )


class AbsoluteGuardTests(unittest.TestCase):
    def test_absolute_and_or_semantics(self) -> None:
        self.assertIsNone(absolute_guard_allows(2900.56, None))
        self.assertTrue(absolute_guard_allows(2900.56, 5000))
        self.assertFalse(absolute_guard_allows(2900.56, 1000))
        self.assertTrue(
            combined_guard_unsafe(percent_allows=False, absolute_allows=True, mode="OR")
        )
        self.assertFalse(
            combined_guard_unsafe(percent_allows=True, absolute_allows=True, mode="OR")
        )
        self.assertEqual(ABSOLUTE_GUARD_CANDIDATES[0], None)


if __name__ == "__main__":
    unittest.main()
