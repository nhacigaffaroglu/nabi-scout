from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.candidate_pipeline_presentation import display_nabi_score
from services.canonical_current_valuation import (
    canonical_current_snapshot,
    canonical_total_wealth_usd,
    canonical_try_equivalent,
    canonical_wealth_metrics,
)
from services.fx_rate_contract import FxConversionResult
from services.nabi_dashboard_presentation import (
    FX_MISSING_COPY,
    present_current_try_equivalent,
    present_wealth_section,
)
from services.portfolio_cockpit_presentation import (
    BENCHMARK_UNAVAILABLE_COPY,
    COST_MISSING_COPY,
    HOLDINGS_TABLE_COLUMNS,
    LAYER_UNAVAILABLE_COPY,
    allocation_sums_to_total,
    build_portfolio_cockpit,
    weights_sum_near_100,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.ui_table_headers import label_for_column
from services.wealth_brief_presentation import BriefPerformance
from services.wealth_goal_models import current_wealth_from_portfolio_view
from services.wealth_history_service import WealthHistoryState, build_wealth_history
from services.wealth_institution_center_presentation import present_institution_center
from services.wealth_performance_center_presentation import (
    INSUFFICIENT_COPY,
    PerformancePeriod,
    build_performance_center,
)
from tests.test_portfolio_decision_center_ui import _row, _view
from tests.test_wealth_performance_center_ux import _pos, _snap

CANON = Path("services/canonical_current_valuation.py")
COCKPIT = Path("services/portfolio_cockpit_presentation.py")
COCKPIT_UI = Path("components/portfolio_cockpit_ui.py")
WEALTH_PAGE = Path("pages/10_Wealth.py")
HOME = Path("components/nabi_home_dashboard.py")
GOAL_UI = Path("components/wealth_goal_center_ui.py")
PLANNING_TOKENS = (
    "wealth_planning_fx",
    "PlanningFxSchedule",
    "usdtry_for_year",
    "wealth_planning_fx_assumptions",
)
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "TwelveData",
    "BorsaIstanbul",
    "WealthPriceService",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    "capture_portfolio_snapshot",
    "save_planning_fx_schedule",
    "save_policy",
)
TABLE_HEADERS_TR = (
    "Sembol",
    "Varlık",
    "Kurum",
    "Adet",
    "Güncel Fiyat",
    "Para Birimi",
    "Piyasa Değeri",
    "Portföy Payı",
    "Maliyet",
    "K/Z",
    "K/Z %",
    "NABI Score",
    "Karar",
)


def _priced(
    symbol: str,
    *,
    market_value: float,
    weight_pct: float,
    currency: str = "USD",
    quantity: float = 1.0,
    price: float = 100.0,
    cost_basis: float = 80.0,
    unrealized_pl: float | None = 20.0,
    asset_class: str = "equity",
    account_id: str = "acc-ml",
    account_name: str = "ML",
    included: bool = True,
    fx_rate: float | None = None,
) -> PositionValuationRow:
    return _row(
        symbol=symbol,
        price_available=True,
        market_value=market_value,
        currency=currency,
        weight_pct=weight_pct,
        quantity=quantity,
        price=price,
        cost_basis=cost_basis,
        unrealized_pl=unrealized_pl,
        asset_class=asset_class,
        account_id=account_id,
        account_name=account_name,
        included_in_base_totals=included,
        fx_converted=fx_rate is not None,
        fx_rate_used=fx_rate,
        native_market_value=market_value * fx_rate if fx_rate else market_value,
    )


def _canonical_view() -> PortfolioIntelligenceView:
    usd = 21255.0
    bist = 58358.0
    total = usd + bist
    priced = [
        _priced("AAPL", market_value=10000.0, weight_pct=10000.0 / total * 100.0, quantity=40, price=250),
        _priced("SPUS", market_value=11255.0, weight_pct=11255.0 / total * 100.0, quantity=200, price=56.275, asset_class="etf"),
        _priced(
            "TUPRS",
            market_value=24000.0,
            weight_pct=24000.0 / total * 100.0,
            currency="USD",
            quantity=1032,
            price=960.0,
            account_id="acc-tfk",
            account_name="TFK",
            fx_rate=41.28,
        ),
        _priced(
            "ASELS",
            market_value=17000.0,
            weight_pct=17000.0 / total * 100.0,
            currency="USD",
            quantity=680,
            price=1031.76,
            account_id="acc-tfk",
            account_name="TFK",
            fx_rate=41.28,
        ),
        _priced(
            "BIMAS",
            market_value=17358.0,
            weight_pct=17358.0 / total * 100.0,
            currency="USD",
            quantity=797,
            price=899.0,
            account_id="acc-tfk",
            account_name="TFK",
            fx_rate=41.28,
        ),
    ]
    view = _view(priced=priced)
    return PortfolioIntelligenceView(
        **{
            **view.__dict__,
            "priced_total_market_value": total,
            "priced_position_count": len(priced),
            "unpriced_position_count": 0,
            "foreign_currency_position_count": 0,
            "total_position_count": len(priced),
            "mixed_currency_warning": False,
            "asset_class_allocation": [
                AllocationSlice("equity", "equity", 10000.0 + 24000.0 + 17000.0 + 17358.0, (10000 + 24000 + 17000 + 17358) / total * 100),
                AllocationSlice("etf", "etf", 11255.0, 11255.0 / total * 100),
            ],
            "health": PortfolioHealthMetrics(
                24000.0 / total * 100,
                (24000.0 + 17358.0 + 17000.0) / total * 100,
                (10000 + 24000 + 17000 + 17358) / total * 100,
                0.0,
                100.0,
                100.0,
            ),
        }
    )


def _accounts() -> list[dict]:
    return [
        {"id": "acc-ml", "name": "ML", "institution": "ML", "currency": "USD"},
        {"id": "acc-tfk", "name": "TFK", "institution": "TFK", "currency": "TRY"},
    ]


def _fx_ok(amount: float, *, rate: float = 41.28) -> MagicMock:
    fx = MagicMock()
    fx.convert_amount.return_value = FxConversionResult(
        native_amount=amount,
        native_currency="USD",
        converted_amount=amount * rate,
        base_currency="TRY",
        rate_used=rate,
        rate_date="2026-08-22",
        converted=True,
        unavailable=False,
        stale=False,
        limitation="",
    )
    fx.get_rate_row.return_value = SimpleNamespace(
        rate=rate,
        source="fx_rates",
        rate_date="2026-08-22",
        stale=False,
    )
    return fx


def _fx_missing(amount: float) -> MagicMock:
    fx = MagicMock()
    fx.convert_amount.return_value = FxConversionResult(
        native_amount=amount,
        native_currency="USD",
        converted_amount=None,
        base_currency="TRY",
        rate_used=None,
        rate_date=None,
        converted=False,
        unavailable=True,
        stale=False,
        limitation="USD/TRY kuru bulunamadı; dönüşüm yapılmadı.",
    )
    fx.get_rate_row.return_value = None
    return fx


class CanonicalSourceWiringTests(unittest.TestCase):
    def test_surfaces_use_canonical_helper(self) -> None:
        wealth = WEALTH_PAGE.read_text(encoding="utf-8")
        home = HOME.read_text(encoding="utf-8")
        goal = GOAL_UI.read_text(encoding="utf-8")
        self.assertIn("build_canonical_current_view", wealth)
        self.assertIn("build_canonical_current_view", home)
        self.assertIn("build_canonical_current_view", goal)
        self.assertNotIn("from services.wealth_price_service import WealthPriceService", wealth)
        self.assertIn("render_wealth_command_center", wealth)
        self.assertIn("build_canonical_current_view", wealth)

    def test_canonical_path_excludes_planning_fx_and_fmp(self) -> None:
        source = CANON.read_text(encoding="utf-8")
        self.assertNotIn("from services.wealth_planning_fx", source)
        self.assertNotIn("usdtry_for_year", source)
        self.assertNotIn("PlanningFxSchedule", source)
        self.assertNotIn("from services.wealth_price_service", source)
        self.assertNotIn("FMPClient", source)
        self.assertNotIn("openai", source)
        self.assertIn("CandidatePriceService", source)
        self.assertIn("FxRateService", source)

    def test_cockpit_is_presentation_only(self) -> None:
        for path in (COCKPIT, COCKPIT_UI):
            source = path.read_text(encoding="utf-8")
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
            self.assertNotIn("WealthPriceService", source)
            self.assertNotIn("wealth_planning_fx", source)


class CrossScreenValuationTests(unittest.TestCase):
    def test_dashboard_wealth_goal_institution_cockpit_usd_match(self) -> None:
        view = _canonical_view()
        usd = canonical_total_wealth_usd(view)
        metrics = canonical_wealth_metrics(view)
        dashboard = present_wealth_section(
            metrics,
            coverage_pct=view.health.priced_position_coverage_pct,
            fx_service=_fx_ok(usd),
            performance=BriefPerformance(
                period_label="Aylık",
                return_label=None,
                best_label=None,
                weakest_label=None,
                limitation=INSUFFICIENT_COPY,
            ),
        )
        snapshot = canonical_current_snapshot(view)
        goal = current_wealth_from_portfolio_view(view)
        institutions = present_institution_center(view, _accounts())
        cockpit = build_portfolio_cockpit(view, fx_service=_fx_ok(usd), accounts=_accounts())
        self.assertAlmostEqual(usd, 79613.0, places=2)
        self.assertAlmostEqual(dashboard.usd_amount or 0.0, usd)
        self.assertAlmostEqual(float(snapshot.current_value_lower_bound), usd)
        self.assertAlmostEqual(float(goal.current_value_lower_bound), usd)
        self.assertAlmostEqual(institutions.totals.total_value, usd)
        self.assertAlmostEqual(cockpit.usd_total, usd)
        self.assertTrue(snapshot.valuation_complete)
        self.assertTrue(goal.valuation_complete)
        self.assertTrue(dashboard.valuation_complete)
        self.assertTrue(cockpit.hero.valuation_complete)

    def test_fmp_partial_path_is_not_canonical(self) -> None:
        view = _canonical_view()
        usd_only = sum(
            float(row.market_value or 0.0)
            for row in view.priced_positions
            if row.fx_rate_used is None
        )
        self.assertAlmostEqual(usd_only, 21255.0, places=2)
        self.assertNotAlmostEqual(usd_only, canonical_total_wealth_usd(view))


class CurrentFxDisplayTests(unittest.TestCase):
    def test_dashboard_try_uses_current_fx_rates(self) -> None:
        fx = _fx_ok(79613.0, rate=41.28)
        shown = present_current_try_equivalent(79613.0, fx)
        self.assertTrue(shown.available)
        self.assertAlmostEqual(shown.amount or 0.0, 79613.0 * 41.28, places=1)
        fx.convert_amount.assert_called_once()
        kwargs = fx.convert_amount.call_args.kwargs
        self.assertEqual(kwargs["from_currency"], "USD")
        self.assertEqual(kwargs["to_currency"], "TRY")

    def test_missing_current_fx_omits_try(self) -> None:
        view = _canonical_view()
        cockpit = build_portfolio_cockpit(view, fx_service=_fx_missing(79613.0))
        self.assertIsNone(cockpit.hero.try_label)
        self.assertIsNone(cockpit.try_equivalent.amount)
        self.assertTrue(cockpit.hero.try_limitation)

    def test_planning_fx_cannot_enter_current_try(self) -> None:
        source = Path("services/nabi_dashboard_presentation.py").read_text(encoding="utf-8")
        self.assertNotIn("usdtry_for_year", source)
        try_view = canonical_try_equivalent(_canonical_view(), _fx_ok(79613.0, rate=41.28))
        self.assertNotAlmostEqual(try_view.amount or 0.0, 79613.0 * 51.0, places=0)


class BistCurrentFxTests(unittest.TestCase):
    def test_bist_rows_included_with_persisted_fx(self) -> None:
        view = _canonical_view()
        bist = [row for row in view.priced_positions if row.symbol in {"TUPRS", "ASELS", "BIMAS"}]
        self.assertEqual({row.symbol: row.quantity for row in bist}, {
            "TUPRS": 1032,
            "ASELS": 680,
            "BIMAS": 797,
        })
        self.assertTrue(all(row.included_in_base_totals for row in bist))
        self.assertTrue(all(row.fx_rate_used == 41.28 for row in bist))
        self.assertAlmostEqual(
            sum(float(row.market_value or 0.0) for row in bist),
            58358.0,
            places=2,
        )


class CockpitReconciliationTests(unittest.TestCase):
    def test_cockpit_total_and_allocations_reconcile(self) -> None:
        view = _canonical_view()
        cockpit = build_portfolio_cockpit(view, fx_service=_fx_ok(79613.0), accounts=_accounts())
        self.assertAlmostEqual(cockpit.usd_total, 79613.0, places=2)
        self.assertTrue(allocation_sums_to_total(cockpit.asset_allocation, cockpit.usd_total))
        self.assertTrue(weights_sum_near_100(cockpit.holding_weights))
        ids = [row.symbol for row in cockpit.holding_weights]
        self.assertEqual(len(ids), len(set(ids)))
        priced_sum = sum(float(row.market_value or 0.0) for row in view.priced_positions)
        self.assertAlmostEqual(priced_sum, cockpit.usd_total)

    def test_no_position_double_counting(self) -> None:
        view = _canonical_view()
        cockpit = build_portfolio_cockpit(view, accounts=_accounts())
        self.assertEqual(len(cockpit.holdings_table), len(view.priced_positions))
        self.assertEqual(len(cockpit.holding_weights), len(view.priced_positions))
        self.assertEqual(
            {row.symbol for row in cockpit.holdings_table},
            {row.symbol for row in view.priced_positions},
        )


class GainLossEvidenceTests(unittest.TestCase):
    def test_missing_cost_basis_omits_gain(self) -> None:
        missing = _priced(
            "CASH",
            market_value=1000.0,
            weight_pct=100.0,
            cost_basis=0.0,
            unrealized_pl=0.0,
            asset_class="cash",
        )
        view = _view(priced=[missing])
        cockpit = build_portfolio_cockpit(view)
        self.assertFalse(cockpit.gain_available)
        self.assertIsNone(cockpit.hero.gain_usd_label)
        self.assertTrue(cockpit.holdings_table[0].cost_missing)
        self.assertIsNone(cockpit.holdings_table[0].unrealized_pl)
        self.assertIn("COST_MISSING_COPY", COCKPIT_UI.read_text(encoding="utf-8"))
        self.assertEqual(COST_MISSING_COPY, "Maliyet verisi yok")


class PerformanceEvidenceTests(unittest.TestCase):
    def test_partial_snapshots_do_not_fabricate_return(self) -> None:
        snaps = [
            _snap("s1", "2026-07-01T00:00:00+00:00", 70000.0, complete=False),
            _snap("s2", "2026-08-01T00:00:00+00:00", 79613.0, complete=False),
        ]
        history = build_wealth_history(snaps)
        self.assertNotEqual(history.history_state, WealthHistoryState.COMPARABLE)
        self.assertIsNone(history.return_pct)
        center = build_performance_center(snaps, period=PerformancePeriod.MONTHLY)
        self.assertFalse(center.sufficient)
        cockpit = build_portfolio_cockpit(_canonical_view(), performance=center)
        self.assertIsNone(cockpit.hero.period_label)

    def test_contributions_are_not_treated_as_return(self) -> None:
        ui = COCKPIT_UI.read_text(encoding="utf-8")
        self.assertIn("net_external_contributions", ui)
        self.assertIn("Modified Dietz", ui)
        self.assertIn("Katkılar getiri değildir", ui)

    def test_benchmark_unavailable_is_not_fabricated(self) -> None:
        cockpit = build_portfolio_cockpit(_canonical_view(), benchmark_available=False)
        self.assertFalse(cockpit.benchmark_available)
        self.assertEqual(cockpit.benchmark_limitation, BENCHMARK_UNAVAILABLE_COPY)
        self.assertNotIn("FMPClient", COCKPIT_UI.read_text(encoding="utf-8"))


class LayerAndScoreTests(unittest.TestCase):
    def test_layer_unavailable_when_no_target_policy(self) -> None:
        cockpit = build_portfolio_cockpit(_canonical_view())
        self.assertFalse(cockpit.layer_available)
        self.assertEqual(cockpit.layer_limitation, LAYER_UNAVAILABLE_COPY)

    def test_incomplete_candidate_score_hidden(self) -> None:
        incomplete = {
            "symbol": "AAPL",
            "decision": "VERİ EKSİK",
            "participation_status": "Kontrol Et",
            "nabi_score": 31.4,
            "data_completeness": 20.0,
            "last_scanned_at": None,
        }
        self.assertIsNone(display_nabi_score(incomplete))
        cockpit = build_portfolio_cockpit(
            _canonical_view(),
            candidates=[incomplete],
        )
        aapl = next(row for row in cockpit.holdings_table if row.symbol == "AAPL")
        self.assertIsNone(aapl.nabi_score)


class TurkishHeaderTests(unittest.TestCase):
    def test_cockpit_table_uses_turkish_headers(self) -> None:
        ui = COCKPIT_UI.read_text(encoding="utf-8")
        for header in TABLE_HEADERS_TR:
            self.assertIn(header, ui)
        mapped = [label_for_column(column) for column in HOLDINGS_TABLE_COLUMNS]
        self.assertIn("Sembol", mapped)
        self.assertIn("Kurum", mapped)
        self.assertIn("Piyasa Değeri", mapped)
        self.assertTrue(all(label != label.lower() or label.isascii() for label in mapped))


if __name__ == "__main__":
    unittest.main()
