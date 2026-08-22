from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from repositories.wealth_portfolio_snapshot_repository import (
    WealthPortfolioSnapshotRepository,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_core_service import WealthCoreService
from services.wealth_performance_engine import build_performance_period, snapshot_view_from_row
from services.wealth_snapshot_capture_service import (
    SnapshotCaptureStatus,
    capture_portfolio_snapshot,
)
from services.wealth_snapshot_serializer import (
    build_valuation_payload,
    unpriced_symbols_from_view,
    valuation_is_complete,
)
from services.wealth_timeline_service import WealthTimelineService

PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)
WRITE_LEDGER_TOKENS = (
    "post_transaction",
    "register_asset",
    "create_account",
    "list_positions().",
)
CHANGED = (
    Path("services/wealth_snapshot_capture_service.py"),
    Path("scripts/run_daily_wealth_snapshot.py"),
    Path("services/wealth_snapshot_serializer.py"),
    Path("repositories/wealth_portfolio_snapshot_repository.py"),
)


def _row(*, symbol: str, price_available: bool, market_value, currency: str, **kwargs) -> PositionValuationRow:
    defaults = dict(
        position_id=f"p-{symbol}",
        account_id="a1",
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class="equity",
        account_name="Broker",
        quantity=1,
        average_cost=10,
        valuation_currency=currency,
        price=110 if price_available else None,
        price_available=price_available,
        market_value=market_value,
        cost_basis=10,
        unrealized_pl=100 if price_available else None,
        weight_pct=10.0 if price_available else None,
        is_cash=False,
        included_in_base_totals=price_available and currency == "USD",
    )
    defaults.update(kwargs)
    return PositionValuationRow(**defaults)


def _view(*, complete: bool = True, priced_value: float = 10000.0) -> PortfolioIntelligenceView:
    priced = [
        _row(symbol="AAPL", price_available=True, market_value=priced_value, currency="USD"),
    ]
    unpriced = []
    foreign = []
    if not complete:
        foreign = [
            _row(symbol="BIMAS", price_available=False, market_value=None, currency="TRY"),
            _row(symbol="ASELS", price_available=False, market_value=None, currency="TRY"),
            _row(symbol="TUPRS", price_available=False, market_value=None, currency="TRY"),
        ]
    total = len(priced) + len(unpriced) + len(foreign)
    priced_count = len(priced)
    coverage = (priced_count / total) * 100.0 if total else 100.0
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=priced_value,
        priced_total_cost_basis=9000.0,
        priced_total_unrealized_pl=1000.0,
        priced_position_count=priced_count,
        unpriced_position_count=len(unpriced) + len(foreign),
        foreign_currency_position_count=len(foreign),
        total_position_count=total,
        mixed_currency_warning=bool(foreign),
        fx_supported=False,
        priced_positions=priced,
        unpriced_positions=unpriced,
        foreign_currency_positions=foreign,
        asset_class_allocation=[AllocationSlice("equity", "equity", priced_value, 100.0)],
        account_allocation=[AllocationSlice("a1", "Broker", priced_value, 100.0)],
        health=PortfolioHealthMetrics(100.0, 100.0, 100.0, 0.0, 100.0, coverage),
        valuation_errors=[],
        price_provider="candidate_snapshot",
        unique_price_symbols_fetched=priced_count,
    )


def _wealth() -> WealthCoreService:
    wealth = WealthCoreService(MagicMock(), "user-a")
    wealth.portfolios.list_for_user = MagicMock(return_value=[{"id": "pf-1", "user_id": "user-a"}])
    wealth.list_liabilities = MagicMock(return_value=[])
    return wealth


def _repo(*, existing=None):
    repo = MagicMock(spec=WealthPortfolioSnapshotRepository)
    repo.istanbul_calendar_date = WealthPortfolioSnapshotRepository.istanbul_calendar_date
    repo.istanbul_date_from_captured_at = (
        WealthPortfolioSnapshotRepository.istanbul_date_from_captured_at
    )
    repo.find_for_portfolio_on_date.return_value = existing
    repo.insert.return_value = {
        "id": "snap-1",
        "user_id": "user-a",
        "portfolio_id": "pf-1",
        "captured_at": "2026-08-17T12:00:00+00:00",
        "snapshot_date": "2026-08-17",
        "base_currency": "USD",
        "priced_market_value": 10000.0,
        "total_cost_basis": 9000.0,
        "unrealized_pl": 1000.0,
        "cash_value": 0,
        "invested_value": 10000.0,
        "liabilities_total": 0,
        "net_wealth_partial": 10000.0,
        "priced_position_coverage_pct": 100.0,
        "unpriced_position_count": 0,
        "mixed_currency_warning": False,
        "valuation_payload": {},
        "created_at": "2026-08-17T12:00:00+00:00",
    }
    return repo


class IstanbulDateTests(unittest.TestCase):
    def test_utc_turkey_day_boundary(self) -> None:
        same_day = datetime(2026, 8, 17, 20, 59, tzinfo=timezone.utc)
        next_day = datetime(2026, 8, 17, 21, 0, tzinfo=timezone.utc)
        self.assertEqual(
            WealthPortfolioSnapshotRepository.istanbul_calendar_date(same_day).isoformat(),
            "2026-08-17",
        )
        self.assertEqual(
            WealthPortfolioSnapshotRepository.istanbul_calendar_date(next_day).isoformat(),
            "2026-08-18",
        )


class SerializerCompletenessTests(unittest.TestCase):
    def test_complete_valuation_snapshot_payload(self) -> None:
        view = _view(complete=True)
        payload = build_valuation_payload(view)
        self.assertTrue(payload["valuation_complete"])
        self.assertTrue(valuation_is_complete(view))
        self.assertEqual(payload["unpriced_symbols"], [])

    def test_partial_valuation_preserves_unpriced_symbols(self) -> None:
        view = _view(complete=False, priced_value=58642.17)
        payload = build_valuation_payload(view)
        self.assertFalse(payload["valuation_complete"])
        self.assertEqual(payload["unpriced_symbols"], ["BIMAS", "ASELS", "TUPRS"])
        self.assertEqual(unpriced_symbols_from_view(view), ("BIMAS", "ASELS", "TUPRS"))
        self.assertEqual(payload["priced_total_market_value"], 58642.17)

    def test_missing_price_never_zero(self) -> None:
        view = _view(complete=False, priced_value=58642.17)
        for row in view.foreign_currency_positions:
            self.assertIsNone(row.market_value)
            self.assertNotEqual(row.market_value, 0)
        self.assertGreater(view.priced_total_market_value, 0)


class CaptureServiceTests(unittest.TestCase):
    def test_scheduled_daily_first_capture(self) -> None:
        repo = _repo()
        result = capture_portfolio_snapshot(
            _wealth(),
            {"id": "pf-1", "user_id": "user-a"},
            captured_at=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
            view=_view(),
            snapshots=repo,
        )
        self.assertEqual(result.status, SnapshotCaptureStatus.CREATED)
        self.assertTrue(result.written)
        repo.insert.assert_called_once()
        payload = repo.insert.call_args.args[0]
        self.assertEqual(payload["snapshot_date"], "2026-08-17")
        self.assertTrue(result.valuation_complete)

    def test_same_day_duplicate_already_captured(self) -> None:
        existing = _repo().insert.return_value
        existing["valuation_payload"] = {"valuation_complete": True, "unpriced_symbols": []}
        repo = _repo(existing=existing)
        result = capture_portfolio_snapshot(
            _wealth(),
            {"id": "pf-1"},
            captured_at=datetime(2026, 8, 17, 18, 0, tzinfo=timezone.utc),
            view=_view(),
            snapshots=repo,
        )
        self.assertEqual(result.status, SnapshotCaptureStatus.ALREADY_CAPTURED)
        self.assertFalse(result.written)
        repo.insert.assert_not_called()

    def test_next_istanbul_calendar_day_creates(self) -> None:
        repo = _repo()
        first = capture_portfolio_snapshot(
            _wealth(),
            {"id": "pf-1"},
            captured_at=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
            view=_view(),
            snapshots=repo,
        )
        self.assertEqual(first.snapshot_date, "2026-08-17")
        repo.find_for_portfolio_on_date.return_value = None
        second = capture_portfolio_snapshot(
            _wealth(),
            {"id": "pf-1"},
            captured_at=datetime(2026, 8, 17, 21, 30, tzinfo=timezone.utc),
            view=_view(),
            snapshots=repo,
        )
        self.assertEqual(second.snapshot_date, "2026-08-18")
        self.assertEqual(repo.insert.call_count, 2)

    def test_partial_valuation_may_still_persist(self) -> None:
        repo = _repo()
        result = capture_portfolio_snapshot(
            _wealth(),
            {"id": "pf-1"},
            captured_at=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
            view=_view(complete=False, priced_value=58642.17),
            snapshots=repo,
        )
        self.assertEqual(result.status, SnapshotCaptureStatus.CREATED)
        self.assertFalse(result.valuation_complete)
        self.assertEqual(result.unpriced_symbols, ("BIMAS", "ASELS", "TUPRS"))
        payload = repo.insert.call_args.args[0]
        self.assertEqual(payload["priced_market_value"], 58642.17)
        self.assertEqual(payload["unpriced_position_count"], 3)
        self.assertFalse(payload["valuation_payload"]["valuation_complete"])

    def test_dry_run_writes_zero(self) -> None:
        repo = _repo()
        result = capture_portfolio_snapshot(
            _wealth(),
            {"id": "pf-1"},
            dry_run=True,
            captured_at=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
            view=_view(complete=False),
            snapshots=repo,
        )
        self.assertEqual(result.status, SnapshotCaptureStatus.CREATED)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.written)
        repo.insert.assert_not_called()

    def test_valuation_failure_writes_zero(self) -> None:
        repo = _repo()
        wealth = _wealth()
        with patch(
            "services.wealth_snapshot_capture_service.PortfolioIntelligenceService"
        ) as intel_cls:
            intel_cls.return_value.build_view.side_effect = RuntimeError("valuation failed")
            result = capture_portfolio_snapshot(
                wealth,
                {"id": "pf-1"},
                captured_at=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
                snapshots=repo,
            )
        self.assertEqual(result.status, SnapshotCaptureStatus.ERROR)
        self.assertFalse(result.written)
        repo.insert.assert_not_called()

    def test_no_portfolio(self) -> None:
        result = capture_portfolio_snapshot(_wealth(), None, snapshots=_repo())
        self.assertEqual(result.status, SnapshotCaptureStatus.NO_PORTFOLIO)
        self.assertFalse(result.written)

    def test_append_only_does_not_upsert(self) -> None:
        source = Path("services/wealth_snapshot_capture_service.py").read_text(encoding="utf-8")
        self.assertNotIn("upsert", source)
        self.assertNotIn(".delete(", source)
        self.assertNotIn(".update(", source)
        self.assertIn("repo.insert", source)


class PerformanceCompatibilityTests(unittest.TestCase):
    def test_chronological_retrieval_order(self) -> None:
        wealth = _wealth()
        service = WealthTimelineService(wealth)
        service.snapshots.list_for_portfolio = MagicMock(
            return_value=[
                {
                    "id": "s2",
                    "user_id": "user-a",
                    "portfolio_id": "pf-1",
                    "captured_at": "2026-08-18T06:30:00+00:00",
                    "base_currency": "USD",
                    "priced_market_value": 11000.0,
                    "total_cost_basis": 9000.0,
                    "unrealized_pl": 2000.0,
                    "cash_value": 0,
                    "invested_value": 11000.0,
                    "liabilities_total": None,
                    "net_wealth_partial": None,
                    "priced_position_coverage_pct": 25.0,
                    "unpriced_position_count": 3,
                    "mixed_currency_warning": True,
                    "valuation_payload": {"valuation_complete": False},
                    "created_at": "2026-08-18T06:30:00+00:00",
                },
                {
                    "id": "s1",
                    "user_id": "user-a",
                    "portfolio_id": "pf-1",
                    "captured_at": "2026-08-17T06:30:00+00:00",
                    "base_currency": "USD",
                    "priced_market_value": 10000.0,
                    "total_cost_basis": 9000.0,
                    "unrealized_pl": 1000.0,
                    "cash_value": 0,
                    "invested_value": 10000.0,
                    "liabilities_total": None,
                    "net_wealth_partial": None,
                    "priced_position_coverage_pct": 25.0,
                    "unpriced_position_count": 3,
                    "mixed_currency_warning": True,
                    "valuation_payload": {"valuation_complete": False},
                    "created_at": "2026-08-17T06:30:00+00:00",
                },
            ]
        )
        snaps = service.list_snapshots("pf-1")
        self.assertEqual([row.id for row in snaps], ["s2", "s1"])
        chronological = list(reversed(snaps))
        self.assertEqual([row.id for row in chronological], ["s1", "s2"])

    def test_one_snapshot_does_not_fabricate_return(self) -> None:
        wealth = _wealth()
        service = WealthTimelineService(wealth)
        row = {
            "id": "s1",
            "user_id": "user-a",
            "portfolio_id": "pf-1",
            "captured_at": "2026-08-17T06:30:00+00:00",
            "base_currency": "USD",
            "priced_market_value": 10000.0,
            "total_cost_basis": 9000.0,
            "unrealized_pl": 1000.0,
            "cash_value": 0,
            "invested_value": 10000.0,
            "liabilities_total": None,
            "net_wealth_partial": None,
            "priced_position_coverage_pct": 25.0,
            "unpriced_position_count": 3,
            "mixed_currency_warning": True,
            "valuation_payload": {"valuation_complete": False},
            "created_at": "2026-08-17T06:30:00+00:00",
        }
        service.snapshots.list_for_portfolio = MagicMock(return_value=[row])
        timeline = service.build_timeline_view({"id": "pf-1", "name": "Main", "base_currency": "USD"})
        self.assertEqual(len(timeline.snapshots), 1)
        self.assertIsNone(timeline.latest_period)

    def test_partial_snapshot_not_comparable_alone(self) -> None:
        start = snapshot_view_from_row(
            {
                "id": "s1",
                "user_id": "user-a",
                "portfolio_id": "pf-1",
                "captured_at": "2026-08-17T06:30:00+00:00",
                "base_currency": "USD",
                "priced_market_value": 10000.0,
                "total_cost_basis": 9000.0,
                "unrealized_pl": 1000.0,
                "cash_value": 0,
                "invested_value": 10000.0,
                "liabilities_total": None,
                "net_wealth_partial": None,
                "priced_position_coverage_pct": 25.0,
                "unpriced_position_count": 3,
                "mixed_currency_warning": True,
                "valuation_payload": {},
                "created_at": "2026-08-17T06:30:00+00:00",
            }
        )
        end = snapshot_view_from_row(
            {
                "id": "s2",
                "user_id": "user-a",
                "portfolio_id": "pf-1",
                "captured_at": "2026-08-18T06:30:00+00:00",
                "base_currency": "USD",
                "priced_market_value": 11000.0,
                "total_cost_basis": 9000.0,
                "unrealized_pl": 2000.0,
                "cash_value": 0,
                "invested_value": 11000.0,
                "liabilities_total": None,
                "net_wealth_partial": None,
                "priced_position_coverage_pct": 25.0,
                "unpriced_position_count": 3,
                "mixed_currency_warning": True,
                "valuation_payload": {},
                "created_at": "2026-08-18T06:30:00+00:00",
            }
        )
        period = build_performance_period(
            start=start,
            end=end,
            transactions=[],
            account_ids=set(),
        )
        self.assertFalse(period.performance_comparable)
        self.assertIsNone(period.simple_period_return_pct)
        reasons = " ".join(period.warnings)
        self.assertIn("Karışık para birimli", reasons)
        self.assertIn("fiyatsız pozisyon", reasons)
        self.assertIn("fiyatlı pozisyon kapsamı eksik", reasons)
        self.assertNotIn("Mixed-currency", reasons)
        self.assertNotIn("Unpriced positions present", reasons)
        self.assertNotIn("Incomplete priced-position coverage", reasons)


class MixedCurrencyWarningSemanticTests(unittest.TestCase):
    def test_usd_plus_unpriced_try_is_warning(self) -> None:
        from services.portfolio_intelligence_engine import rollup_portfolio_intelligence

        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=[
                _row(symbol="AAPL", price_available=True, market_value=100.0, currency="USD"),
                _row(
                    symbol="BIMAS",
                    price_available=False,
                    market_value=None,
                    currency="TRY",
                    included_in_base_totals=False,
                ),
            ],
            price_provider="none",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        self.assertTrue(view.mixed_currency_warning)
        payload = build_valuation_payload(view)
        self.assertTrue(payload["mixed_currency_warning"])
        self.assertIsNone(
            next(row for row in view.unpriced_positions + view.foreign_currency_positions if row.symbol == "BIMAS").price
        )

    def test_tl_alias_behaves_as_try(self) -> None:
        from services.portfolio_intelligence_engine import mixed_currency_warning_from_rows
        from services.wealth_price_service import normalize_currency

        self.assertEqual(normalize_currency("TL"), "TRY")
        rows = [
            _row(symbol="AAPL", price_available=True, market_value=100.0, currency="USD"),
            _row(
                symbol="ASELS",
                price_available=False,
                market_value=None,
                currency="TL",
                included_in_base_totals=False,
            ),
        ]
        self.assertTrue(mixed_currency_warning_from_rows(rows, "USD"))

    def test_usd_only_snapshot_is_not_mixed(self) -> None:
        from services.portfolio_intelligence_engine import rollup_portfolio_intelligence

        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=[
                _row(symbol="AAPL", price_available=True, market_value=100.0, currency="USD"),
                _row(symbol="MSFT", price_available=True, market_value=50.0, currency="USD"),
            ],
            price_provider="none",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        self.assertFalse(view.mixed_currency_warning)

    def test_fx_overlay_keeps_warning_for_unpriced_try(self) -> None:
        from services.fx_conversion_engine import apply_fx_to_portfolio_view
        from services.fx_rate_service import FxRateService
        from services.portfolio_intelligence_engine import rollup_portfolio_intelligence

        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=[
                _row(symbol="AAPL", price_available=True, market_value=100.0, currency="USD"),
                _row(
                    symbol="TUPRS",
                    price_available=False,
                    market_value=None,
                    currency="TRY",
                    included_in_base_totals=False,
                ),
            ],
            price_provider="none",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        fx = FxRateService(MagicMock())
        fx.repo.get_rate = MagicMock(return_value=None)
        adjusted, totals = apply_fx_to_portfolio_view(view, fx)
        self.assertEqual(totals.unconverted_market_value, 0.0)
        self.assertTrue(adjusted.mixed_currency_warning)
        self.assertEqual(fx.remote_calls, 0)
        self.assertTrue(
            any(row.symbol == "TUPRS" for row in adjusted.foreign_currency_positions)
        )
        self.assertIn("TUPRS", unpriced_symbols_from_view(adjusted))


class SafetyTests(unittest.TestCase):
    def test_no_remote_provider_calls(self) -> None:
        for path in CHANGED:
            source = path.read_text(encoding="utf-8").lower()
            for token in PROVIDER_TOKENS:
                with self.subTest(path=str(path), token=token):
                    self.assertNotIn(token.lower(), source)
        capture = Path("services/wealth_snapshot_capture_service.py").read_text(encoding="utf-8")
        self.assertIn("CandidatePriceService", capture)
        self.assertIn("nabi_client=None", capture)
        self.assertIn("enrich_nabi=False", capture)
        self.assertNotIn("FxRateRefreshService", capture)
        self.assertNotIn("wealth_planning_fx", capture)

    def test_no_ledger_candidate_or_position_writes(self) -> None:
        capture = Path("services/wealth_snapshot_capture_service.py").read_text(encoding="utf-8")
        script = Path("scripts/run_daily_wealth_snapshot.py").read_text(encoding="utf-8")
        for source in (capture, script):
            for token in WRITE_LEDGER_TOKENS:
                self.assertNotIn(token, source)
            self.assertNotIn("CandidateRepository().upsert", source)
            self.assertNotIn("materialize_position", source)


if __name__ == "__main__":
    unittest.main()
