from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from services.fund_intelligence_contract import FundHoldingRow
from services.nabi_adviser_context import build_nabi_adviser_context
from services.portfolio_allocation_intelligence import (
    AllocationDimension,
    AllocationPolicy,
    AllocationProvenance,
    AllocationTarget,
    DriftStatus,
)
from services.portfolio_economic_exposure import (
    TARGET_SUM_EPSILON_PCT,
    build_economic_exposure,
)
from services.portfolio_intelligence_contract import PositionValuationRow
from services.security_master_contract import (
    IDENTIFIER_TYPE_TICKER,
    INSTRUMENT_EQUITY,
    SOURCE_US_LISTING,
)
from services.security_master_service import (
    SecurityMasterService,
    SecurityMasterUnavailableError,
    memory_security_master,
    production_security_master,
)
from services.wealth_new_money_allocation import (
    REASON_PARTICIPATION_BLOCKED,
    allocate_new_money,
)
from tests.test_portfolio_economic_exposure import (
    _equity,
    _etf,
    _snapshot,
    _view_from_rows,
)
from tests.test_wealth_new_money_allocation import _fx, _plan, _row, _view


EXPOSURE = Path("services/portfolio_economic_exposure.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
ADVISER = Path("services/nabi_adviser_context.py")
UI = Path("components/portfolio_economic_exposure_ui.py")
BRIEF = Path("components/wealth_brief_ui.py")
PAGE = Path("pages/10_Wealth.py")
ALLOCATION = Path("services/portfolio_allocation_intelligence.py")


def _lot(
    symbol: str,
    market_value: float,
    *,
    asset_class: str = "etf",
    position_id: str,
    account_id: str,
    account_name: str = "Broker",
) -> PositionValuationRow:
    row = _etf(symbol, market_value) if asset_class == "etf" else _equity(symbol, market_value)
    return PositionValuationRow(
        **{
            **row.__dict__,
            "position_id": position_id,
            "account_id": account_id,
            "account_name": account_name,
        }
    )


def _spus_snapshot() -> dict:
    return {
        "SPUS": _snapshot(
            "SPUS",
            (
                FundHoldingRow("AAPL", "Apple", 99.72, None, None, None),
                FundHoldingRow("CASH&OTHER", "Cash & Other", 0.28, None, None, None),
            ),
        )
    }


def _sm_aapl() -> SecurityMasterService:
    return memory_security_master(
        [
            {
                "identifier": "AAPL",
                "identifier_type": IDENTIFIER_TYPE_TICKER,
                "instrument_type": INSTRUMENT_EQUITY,
                "source": SOURCE_US_LISTING,
                "observed_at": "2026-08-29T00:00:00+00:00",
                "symbol": "AAPL",
            }
        ],
        include_canonical_static=False,
    )


def _ee_policy() -> AllocationPolicy:
    return AllocationPolicy(
        targets=(
            AllocationTarget("equity", AllocationDimension.ECONOMIC_EXPOSURE, 75.0),
            AllocationTarget("sukuk", AllocationDimension.ECONOMIC_EXPOSURE, 10.0),
            AllocationTarget("cash", AllocationDimension.ECONOMIC_EXPOSURE, 5.0),
            AllocationTarget("fixed_income", AllocationDimension.ECONOMIC_EXPOSURE, 5.0),
            AllocationTarget("real_estate", AllocationDimension.ECONOMIC_EXPOSURE, 5.0),
            AllocationTarget("commodity", AllocationDimension.ECONOMIC_EXPOSURE, 0.0),
            AllocationTarget("other", AllocationDimension.ECONOMIC_EXPOSURE, 0.0),
        ),
        provenance=AllocationProvenance.USER_DEFINED,
    )


def _bucket_total(view) -> float:
    return sum(float(row.observable_market_value or 0.0) for row in view.buckets)


class MultiLotAggregationTests(unittest.TestCase):
    def test_single_spus_holding_is_counted_once(self) -> None:
        view = build_economic_exposure(
            _view_from_rows([_lot("SPUS", 5633.0, position_id="p-a", account_id="tfk")]),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        self.assertEqual(sum(1 for row in view.instruments if row.symbol == "SPUS"), 1)
        unknown = next(row for row in view.buckets if row.bucket_id == "unknown")
        equity = next(row for row in view.buckets if row.bucket_id == "equity")
        self.assertAlmostEqual(unknown.observable_market_value or 0, 5633.0 * 0.0028, places=2)
        self.assertAlmostEqual(equity.observable_market_value or 0, 5633.0 * 0.9972, places=2)

    def test_two_spus_holdings_are_both_counted(self) -> None:
        view = build_economic_exposure(
            _view_from_rows(
                [
                    _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk", account_name="TFK"),
                    _lot("SPUS", 1013.94, position_id="p-b", account_id="midas", account_name="Midas"),
                ]
            ),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        lots = [row for row in view.instruments if row.symbol == "SPUS"]
        self.assertEqual(len(lots), 2)
        self.assertAlmostEqual(sum(float(row.observable_market_value or 0) for row in lots), 6646.94, places=2)

    def test_same_symbol_two_institutions_fully_accumulates(self) -> None:
        view = build_economic_exposure(
            _view_from_rows(
                [
                    _lot("SPUS", 1000.0, position_id="p-a", account_id="tfk"),
                    _lot("SPUS", 2000.0, position_id="p-b", account_id="midas"),
                ]
            ),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        self.assertAlmostEqual(_bucket_total(view), 3000.0, places=4)

    def test_different_market_values_accumulate(self) -> None:
        view = build_economic_exposure(
            _view_from_rows(
                [
                    _lot("SPUS", 10.0, position_id="p-a", account_id="a1"),
                    _lot("SPUS", 90.0, position_id="p-b", account_id="a2"),
                ]
            ),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        equity = next(row for row in view.buckets if row.bucket_id == "equity")
        self.assertAlmostEqual(equity.observable_market_value or 0, 100.0 * 0.9972, places=4)

    def test_lookthrough_cached_while_mv_accumulates(self) -> None:
        source = EXPOSURE.read_text(encoding="utf-8")
        self.assertIn("classified_by_symbol", source)
        self.assertNotIn("seen_symbols", source)
        view = build_economic_exposure(
            _view_from_rows(
                [
                    _lot("SPUS", 50.0, position_id="p-a", account_id="a1"),
                    _lot("SPUS", 50.0, position_id="p-b", account_id="a2"),
                ]
            ),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        slices = {row.symbol: row.economic_exposures for row in view.instruments if row.symbol == "SPUS"}
        self.assertEqual(len(slices), 1)
        self.assertEqual(
            view.instruments[0].economic_exposures,
            view.instruments[1].economic_exposures,
        )

    def test_direct_equity_duplicate_lots_both_count(self) -> None:
        view = build_economic_exposure(
            _view_from_rows(
                [
                    _lot("AAPL", 100.0, asset_class="equity", position_id="p-a", account_id="a1"),
                    _lot("AAPL", 50.0, asset_class="equity", position_id="p-b", account_id="a2"),
                ]
            )
        )
        equity = next(row for row in view.buckets if row.bucket_id == "equity")
        self.assertAlmostEqual(equity.observable_market_value or 0, 150.0, places=4)
        self.assertEqual(sum(1 for row in view.instruments if row.symbol == "AAPL"), 2)

    def test_input_priced_mv_equals_output_bucket_mv(self) -> None:
        rows = [
            _lot("AAPL", 400.0, asset_class="equity", position_id="p-eq", account_id="a1"),
            _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk"),
            _lot("SPUS", 1013.94, position_id="p-b", account_id="midas"),
        ]
        portfolio = _view_from_rows(rows)
        view = build_economic_exposure(
            portfolio,
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        self.assertAlmostEqual(
            _bucket_total(view),
            float(portfolio.priced_total_market_value),
            delta=TARGET_SUM_EPSILON_PCT,
        )

    def test_unknown_bucket_obeys_conservation(self) -> None:
        view = build_economic_exposure(
            _view_from_rows(
                [
                    _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk"),
                    _lot("SPUS", 1013.94, position_id="p-b", account_id="midas"),
                ]
            ),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        unknown = next(row for row in view.buckets if row.bucket_id == "unknown")
        self.assertAlmostEqual(unknown.observable_market_value or 0, 6646.94 * 0.0028, places=2)
        self.assertIn("UNKNOWN_EXPOSURE_PRESERVED", unknown.limitations)


class SecurityMasterWiringTests(unittest.TestCase):
    def test_db_backed_master_resolves_spus_through_official_holdings(self) -> None:
        view = build_economic_exposure(
            _view_from_rows([_etf("SPUS", 100.0)]),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        spus = next(row for row in view.instruments if row.symbol == "SPUS")
        buckets = {item.exposure_bucket: item.weight_pct for item in spus.economic_exposures}
        self.assertAlmostEqual(buckets["equity"], 99.72)
        self.assertAlmostEqual(buckets["unknown"], 0.28)

    def test_new_money_receives_injected_security_master(self) -> None:
        source = NEW_MONEY.read_text(encoding="utf-8")
        self.assertIn("security_master: Optional[SecurityMasterService] = None", source)
        self.assertIn("security_master=security_master", source)
        self.assertNotIn("SecurityMasterService()", source)
        snapshots = _spus_snapshot()
        master = _sm_aapl()
        empty = SecurityMasterService(include_canonical_static=False)
        injected = build_economic_exposure(
            _view_from_rows([_etf("SPUS", 100.0)]),
            fund_snapshots=snapshots,
            security_master=master,
        )
        fallback = build_economic_exposure(
            _view_from_rows([_etf("SPUS", 100.0)]),
            fund_snapshots=snapshots,
            security_master=empty,
        )
        inj = next(row for row in injected.instruments if row.symbol == "SPUS")
        fb = next(row for row in fallback.instruments if row.symbol == "SPUS")
        self.assertGreater(
            next(s.weight_pct for s in inj.economic_exposures if s.exposure_bucket == "equity"),
            next((s.weight_pct for s in fb.economic_exposures if s.exposure_bucket == "equity"), 0.0),
        )
        plan = allocate_new_money(
            available_amount=Decimal("100000"),
            amount_currency="TRY",
            portfolio_view=_view([_row("HLAL", market_value=1000, weight_pct=100, asset_class="etf")]),
            policy=_ee_policy(),
            conversion=_fx(),
            fund_snapshots=snapshots,
            security_master=master,
        )
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", plan.limitations)

    def test_new_money_does_not_instantiate_empty_production_master(self) -> None:
        source = NEW_MONEY.read_text(encoding="utf-8")
        self.assertNotIn("SecurityMasterService()", source)
        self.assertNotIn("production_security_master", source)

    def test_production_master_fails_closed_without_client(self) -> None:
        with self.assertRaises(SecurityMasterUnavailableError):
            production_security_master(None)

    def test_in_memory_injection_remains_possible(self) -> None:
        master = memory_security_master([], include_canonical_static=False)
        view = build_economic_exposure(
            _view_from_rows([_equity("AAPL", 100.0)]),
            security_master=master,
        )
        self.assertEqual(view.instruments[0].economic_exposures[0].exposure_bucket, "equity")

    def test_production_paths_inject_security_master(self) -> None:
        self.assertIn("try_security_master_from_wealth", UI.read_text(encoding="utf-8"))
        self.assertIn("try_security_master_from_wealth", BRIEF.read_text(encoding="utf-8"))
        self.assertIn("security_master_from_wealth", PAGE.read_text(encoding="utf-8"))
        self.assertIn("security_master=security_master", ADVISER.read_text(encoding="utf-8"))


class MethodologyUnchangedTests(unittest.TestCase):
    def test_participation_gate_unchanged(self) -> None:
        plan = _plan(
            view=_view([_row("AAPL", market_value=10000, weight_pct=100, participation="Kontrol Et")]),
            candidates=[],
        )
        self.assertTrue(
            any(row.reason_code == REASON_PARTICIPATION_BLOCKED for row in plan.skipped)
        )
        self.assertEqual(plan.recommendations, ())

    def test_strategic_targets_and_unknown_completeness_unchanged(self) -> None:
        allocation = ALLOCATION.read_text(encoding="utf-8")
        self.assertIn("unknown_priced", allocation)
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", allocation)
        view = build_economic_exposure(
            _view_from_rows(
                [
                    _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk"),
                    _lot("SPUS", 1013.94, position_id="p-b", account_id="midas"),
                ]
            ),
            fund_snapshots=_spus_snapshot(),
            security_master=_sm_aapl(),
        )
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", view.limitations)
        intelligence = __import__(
            "services.portfolio_allocation_intelligence", fromlist=["build_allocation_intelligence"]
        ).build_allocation_intelligence(
            _view_from_rows(
                [
                    _lot("SPUS", 5633.0, position_id="p-a", account_id="tfk"),
                    _lot("SPUS", 1013.94, position_id="p-b", account_id="midas"),
                ]
            ),
            policy=_ee_policy(),
            exposure_buckets=__import__(
                "services.wealth_new_money_allocation", fromlist=["_allocation_buckets_from_exposure"]
            )._allocation_buckets_from_exposure(view),
        )
        statuses = {
            row.status
            for row in intelligence.drift
            if row.dimension == AllocationDimension.ECONOMIC_EXPOSURE
        }
        self.assertEqual(statuses, {DriftStatus.INDETERMINATE})

    def test_new_money_residual_cash_remains_valid(self) -> None:
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
        self.assertIn("RESIDUAL_CASH", plan.limitations)

    def test_adviser_deterministic_path_receives_canonical_master(self) -> None:
        master = _sm_aapl()
        context = build_nabi_adviser_context(
            "100.000 TL ek param var",
            portfolio_view=_view([_row("HLAL", market_value=1000, weight_pct=100, asset_class="etf")]),
            policy=_ee_policy(),
            fund_snapshots=_spus_snapshot(),
            security_master=master,
            goal_dashboard=SimpleNamespace(
                fx_schedule=SimpleNamespace(usdtry_for_year=lambda year: Decimal("51")),
                as_of_date=SimpleNamespace(year=2026),
            ),
        )
        self.assertEqual(context.intent, "NEW_MONEY_SCENARIO")
        self.assertEqual(context.new_money_context["total_allocated"], "0")
        self.assertEqual(context.new_money_context["residual_cash"], "100000")
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", context.new_money_context["limitations"])


if __name__ == "__main__":
    unittest.main()
