from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from components.wealth_goal_center_ui import _db_only_goal_view
from services.bist_symbol_mapping import select_bist_provider_mapping
from services.candidate_price_service import CandidatePriceService
from services.fx_conversion_engine import (
    apply_fx_to_portfolio_view,
    convert_native_to_base_market_value,
)
from services.fx_rate_service import FxRateService
from services.portfolio_decision_intelligence import build_portfolio_decision
from services.portfolio_intelligence_contract import PriceQuote
from services.portfolio_intelligence_engine import (
    compute_market_value,
    rollup_portfolio_intelligence,
    value_position,
)
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.wealth_goal_models import current_wealth_from_portfolio_view
from services.wealth_goal_planning import planning_conversion
from services.wealth_planning_fx import schedule_from_mapping
from services.wealth_snapshot_capture_service import (
    SnapshotCaptureStatus,
    capture_portfolio_snapshot,
)
from services.wealth_snapshot_serializer import (
    unpriced_symbols_from_view,
    valuation_is_complete,
)
from tests.test_wealth_snapshot_capture import _repo as _snapshot_repo


AS_OF = date(2026, 8, 18)
PLANNING_FX = {2026: 51, 2027: 59, 2028: 66, 2029: 73, 2030: 80, 2031: 87}
TRACKING_START = date(2026, 9, 1)
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)
VALUATION_PATHS = (
    Path("services/fx_rate_service.py"),
    Path("services/fx_conversion_engine.py"),
    Path("services/candidate_price_service.py"),
    Path("services/wealth_snapshot_capture_service.py"),
)


def _fx_service(usdtry: float | None, *, source: str = "fmp_quote") -> FxRateService:
    service = FxRateService(object())

    def _get_rate(*, base_currency, quote_currency, on_or_before=None):
        if usdtry is None:
            return None
        if base_currency == "USD" and quote_currency == "TRY":
            return {
                "base_currency": "USD",
                "quote_currency": "TRY",
                "rate": usdtry,
                "rate_date": AS_OF.isoformat(),
                "source": source,
                "data_quality": "good",
            }
        return None

    service.repo.get_rate = MagicMock(side_effect=_get_rate)
    return service


def _quote(price, currency, *, available=True, as_of="2026-08-18T00:00:00+00:00"):
    return PriceQuote(
        price=price,
        currency=currency,
        available=available,
        source="candidate_snapshot",
        error=None if available else "missing_price",
        as_of=as_of if available else None,
    )


def _position(symbol: str, asset_id: str, account_id: str, quantity: float) -> dict:
    return {
        "id": f"pos-{symbol}-{account_id}",
        "account_id": account_id,
        "asset_id": asset_id,
        "quantity": quantity,
        "average_cost": 10.0,
        "cost_currency": "USD" if symbol not in {"TUPRS", "ASELS", "BIMAS"} else "TRY",
    }


def _asset(symbol: str, currency: str, asset_id: str | None = None, market: str | None = None) -> dict:
    return {
        "id": asset_id or f"asset-{symbol}",
        "symbol": symbol,
        "asset_class": "equity",
        "currency": currency,
        "market": market or ("TR" if currency in {"TRY", "TL"} else "US"),
    }


class FakeCandidatePrices:
    PROVIDER_NAME = "candidate_snapshot"
    fetch_count = 0

    def __init__(self, quotes: dict[str, PriceQuote]) -> None:
        self._quotes = quotes
        self.remote_calls = 0

    def prefetch_assets(self, assets) -> None:
        return None

    def get_quote_for_asset(self, symbol, asset_class, currency, *, market=None):
        return self._quotes.get(
            str(symbol or "").strip().upper(),
            PriceQuote(
                price=None,
                currency=currency,
                available=False,
                source=self.PROVIDER_NAME,
                error="missing_price",
            ),
        )


def _wealth(*, positions, assets, quotes, usdtry: float | None):
    wealth = MagicMock()
    wealth.user_id = "user-1"
    wealth.client = object()
    wealth.list_positions.return_value = positions
    wealth.list_accounts.return_value = [
        {"id": "acc-ml", "name": "ML", "institution": "Merrill Lynch"},
        {"id": "acc-midas", "name": "Midas", "institution": "Midas"},
        {"id": "acc-tfk", "name": "TFK", "institution": "TFK"},
    ]
    wealth.list_assets.return_value = assets
    wealth.list_liabilities.return_value = []
    wealth.portfolios.get_default_for_user.return_value = {
        "id": "pf-1",
        "name": "Ana Portföy",
        "base_currency": "USD",
    }
    wealth.portfolios.list_for_user.return_value = [
        {"id": "pf-1", "user_id": "user-1"}
    ]
    price_service = FakeCandidatePrices(quotes)
    fx = _fx_service(usdtry)
    return wealth, price_service, fx


def _build_view(wealth, price_service, fx):
    with patch(
        "services.portfolio_intelligence_service.FxRateService",
        return_value=fx,
    ):
        return PortfolioIntelligenceService(
            wealth,
            price_service,
            nabi_client=None,
        ).build_view(
            {"id": "pf-1", "name": "Ana Portföy", "base_currency": "USD"},
            enrich_nabi=False,
        )


class UsdValuationTests(unittest.TestCase):
    def test_usd_asset_times_usd_price(self) -> None:
        native = compute_market_value(10.0, 120.0)
        self.assertAlmostEqual(native, 1200.0)
        fx = _fx_service(51.0)
        converted = convert_native_to_base_market_value(
            native_market_value=native,
            native_currency="USD",
            base_currency="USD",
            fx_service=fx,
        )
        self.assertTrue(converted.converted)
        self.assertAlmostEqual(converted.converted_amount, 1200.0)
        self.assertAlmostEqual(converted.rate_used, 1.0)
        fx.repo.get_rate.assert_not_called()

    def test_usd_asset_not_double_converted(self) -> None:
        row = value_position(
            position=_position("TSLA", "asset-TSLA", "acc-ml", 10),
            asset=_asset("TSLA", "USD"),
            account={"name": "ML"},
            base_currency="USD",
            quote=_quote(200.0, "USD"),
        )
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Ana",
            base_currency="USD",
            rows=[row],
            price_provider="candidate_snapshot",
            unique_price_symbols_fetched=1,
            valuation_errors=[],
        )
        adjusted, _ = apply_fx_to_portfolio_view(view, _fx_service(40.0))
        self.assertAlmostEqual(adjusted.priced_total_market_value, 2000.0)
        self.assertFalse(adjusted.priced_positions[0].fx_converted)
        self.assertEqual(adjusted.priced_positions[0].valuation_currency, "USD")


class TryUsdtryDirectionTests(unittest.TestCase):
    def test_try_divides_by_usdtry_not_multiplies(self) -> None:
        fx = _fx_service(40.0)
        result = convert_native_to_base_market_value(
            native_market_value=400.0,
            native_currency="TRY",
            base_currency="USD",
            fx_service=fx,
        )
        self.assertAlmostEqual(result.converted_amount, 10.0)
        inverted = 400.0 * 40.0
        self.assertNotAlmostEqual(result.converted_amount, inverted)

    def test_try_asset_quantity_times_try_price_over_usdtry(self) -> None:
        row = value_position(
            position=_position("TUPRS", "asset-TUPRS", "acc-tfk", 1032),
            asset=_asset("TUPRS", "TL", market="TR"),
            account={"name": "TFK"},
            base_currency="USD",
            quote=_quote(200.0, "TRY"),
        )
        self.assertEqual(row.valuation_currency, "TRY")
        self.assertAlmostEqual(row.price, 200.0)
        self.assertAlmostEqual(row.market_value, 1032 * 200.0)
        self.assertFalse(row.included_in_base_totals)
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Ana",
            base_currency="USD",
            rows=[row],
            price_provider="candidate_snapshot",
            unique_price_symbols_fetched=1,
            valuation_errors=[],
        )
        adjusted, _ = apply_fx_to_portfolio_view(view, _fx_service(40.0))
        priced = adjusted.priced_positions[0]
        self.assertEqual(priced.valuation_currency, "TRY")
        self.assertAlmostEqual(priced.price, 200.0)
        self.assertAlmostEqual(priced.market_value, 1032 * 200.0 / 40.0)
        self.assertTrue(priced.fx_converted)

    def test_different_current_fx_changes_bist_usd_mv(self) -> None:
        row = value_position(
            position=_position("BIMAS", "asset-BIMAS", "acc-tfk", 10),
            asset=_asset("BIMAS", "TRY"),
            account={"name": "TFK"},
            base_currency="USD",
            quote=_quote(80.0, "TRY"),
        )
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Ana",
            base_currency="USD",
            rows=[row],
            price_provider="candidate_snapshot",
            unique_price_symbols_fetched=1,
            valuation_errors=[],
        )
        at_40, _ = apply_fx_to_portfolio_view(view, _fx_service(40.0))
        at_80, _ = apply_fx_to_portfolio_view(view, _fx_service(80.0))
        self.assertAlmostEqual(at_40.priced_total_market_value, 20.0)
        self.assertAlmostEqual(at_80.priced_total_market_value, 10.0)


class EvidenceGapTests(unittest.TestCase):
    def _try_row(self, *, priced: bool):
        return value_position(
            position=_position("ASELS", "asset-ASELS", "acc-tfk", 680),
            asset=_asset("ASELS", "TRY"),
            account={"name": "TFK"},
            base_currency="USD",
            quote=_quote(50.0, "TRY") if priced else _quote(None, "TRY", available=False),
        )

    def test_missing_try_price_is_incomplete(self) -> None:
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Ana",
            base_currency="USD",
            rows=[self._try_row(priced=False)],
            price_provider="candidate_snapshot",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        adjusted, _ = apply_fx_to_portfolio_view(view, _fx_service(40.0))
        current = current_wealth_from_portfolio_view(adjusted)
        self.assertFalse(current.valuation_complete)
        self.assertIn("ASELS", current.missing_price_symbols)
        self.assertNotIn("ASELS", current.missing_fx_symbols)

    def test_missing_current_fx_is_incomplete(self) -> None:
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Ana",
            base_currency="USD",
            rows=[self._try_row(priced=True)],
            price_provider="candidate_snapshot",
            unique_price_symbols_fetched=1,
            valuation_errors=[],
        )
        adjusted, _ = apply_fx_to_portfolio_view(view, _fx_service(None))
        current = current_wealth_from_portfolio_view(adjusted)
        self.assertFalse(current.valuation_complete)
        self.assertIn("ASELS", current.missing_fx_symbols)
        self.assertNotIn("ASELS", current.missing_price_symbols)
        self.assertAlmostEqual(current.current_value_lower_bound, Decimal("0"))

    def test_missing_both_reports_both_reasons(self) -> None:
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Ana",
            base_currency="USD",
            rows=[self._try_row(priced=False)],
            price_provider="candidate_snapshot",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        adjusted, _ = apply_fx_to_portfolio_view(view, _fx_service(None))
        current = current_wealth_from_portfolio_view(adjusted)
        self.assertFalse(current.valuation_complete)
        self.assertIn("ASELS", current.missing_price_symbols)
        self.assertIn("ASELS", current.missing_fx_symbols)
        self.assertIn("ASELS", current.unvalued_symbols)

    def test_complete_persisted_evidence_clears_partial_valuation(self) -> None:
        usd = value_position(
            position=_position("TSLA", "asset-TSLA", "acc-ml", 10),
            asset=_asset("TSLA", "USD"),
            account={"name": "ML"},
            base_currency="USD",
            quote=_quote(100.0, "USD"),
        )
        try_row = self._try_row(priced=True)
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Ana",
            base_currency="USD",
            rows=[usd, try_row],
            price_provider="candidate_snapshot",
            unique_price_symbols_fetched=2,
            valuation_errors=[],
        )
        adjusted, _ = apply_fx_to_portfolio_view(view, _fx_service(40.0))
        current = current_wealth_from_portfolio_view(adjusted)
        self.assertTrue(current.valuation_complete)
        self.assertEqual(current.unvalued_symbols, ())
        self.assertTrue(valuation_is_complete(adjusted))
        decision = build_portfolio_decision(
            adjusted,
            as_of_date=AS_OF,
            current_wealth=current,
            fx_schedule=schedule_from_mapping(PLANNING_FX),
            conversion=planning_conversion(Decimal("51")),
            contribution_tracking_start=TRACKING_START,
        )
        self.assertNotIn(
            "incomplete_valuation",
            {row.id for row in decision.actions},
        )


class PlanningFxIsolationTests(unittest.TestCase):
    def test_planning_fx_is_never_accepted_as_current_fx(self) -> None:
        row = value_position(
            position=_position("TUPRS", "asset-TUPRS", "acc-tfk", 10),
            asset=_asset("TUPRS", "TRY"),
            account={"name": "TFK"},
            base_currency="USD",
            quote=_quote(51.0, "TRY"),
        )
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Ana",
            base_currency="USD",
            rows=[row],
            price_provider="candidate_snapshot",
            unique_price_symbols_fetched=1,
            valuation_errors=[],
        )
        adjusted, _ = apply_fx_to_portfolio_view(view, _fx_service(40.0))
        planning_mv = 10 * 51.0 / 51.0
        current_mv = 10 * 51.0 / 40.0
        self.assertAlmostEqual(adjusted.priced_total_market_value, current_mv)
        self.assertNotAlmostEqual(adjusted.priced_total_market_value, planning_mv)
        for path in VALUATION_PATHS:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("wealth_planning_fx", source)
            self.assertNotIn("USER_DEFINED", source)
            self.assertNotIn("PlanningFxSchedule", source)


class GoalAndSnapshotIntegrationTests(unittest.TestCase):
    def test_goal_center_consumes_persisted_current_fx(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 10)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(80.0, "TRY")},
            usdtry=40.0,
        )
        with patch(
            "services.candidate_price_service.CandidatePriceService",
            return_value=prices,
        ), patch(
            "services.portfolio_intelligence_service.FxRateService",
            return_value=fx,
        ):
            view = _db_only_goal_view(wealth)
        self.assertIsNotNone(view)
        current = current_wealth_from_portfolio_view(view)
        self.assertAlmostEqual(float(current.current_value_lower_bound), 20.0)
        self.assertTrue(current.valuation_complete)
        self.assertEqual(fx.remote_calls, 0)

    def test_snapshot_uses_same_conversion_semantics(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[
                _position("TSLA", "asset-TSLA", "acc-ml", 5),
                _position("TUPRS", "asset-TUPRS", "acc-tfk", 10),
            ],
            assets=[
                _asset("TSLA", "USD", "asset-TSLA"),
                _asset("TUPRS", "TRY", "asset-TUPRS"),
            ],
            quotes={
                "TSLA": _quote(100.0, "USD"),
                "TUPRS": _quote(80.0, "TRY"),
            },
            usdtry=40.0,
        )
        view = _build_view(wealth, prices, fx)
        current = current_wealth_from_portfolio_view(view)
        with patch(
            "services.wealth_snapshot_capture_service.CandidatePriceService",
            return_value=prices,
        ), patch(
            "services.portfolio_intelligence_service.FxRateService",
            return_value=fx,
        ):
            captured = capture_portfolio_snapshot(
                wealth,
                {"id": "pf-1", "name": "Ana Portföy", "base_currency": "USD"},
                dry_run=True,
                captured_at=datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc),
                snapshots=_snapshot_repo(),
            )
        self.assertEqual(captured.status, SnapshotCaptureStatus.CREATED)
        self.assertFalse(captured.written)
        self.assertAlmostEqual(
            captured.priced_market_value,
            float(current.current_value_lower_bound),
        )
        self.assertEqual(captured.valuation_complete, current.valuation_complete)
        self.assertAlmostEqual(captured.priced_market_value, 500.0 + 20.0)


class PortfolioIntelligenceConcentrationTests(unittest.TestCase):
    def test_concentration_includes_bist_when_priced(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[
                _position("TSLA", "asset-TSLA", "acc-ml", 1),
                _position("TUPRS", "asset-TUPRS", "acc-tfk", 10),
            ],
            assets=[
                _asset("TSLA", "USD", "asset-TSLA"),
                _asset("TUPRS", "TRY", "asset-TUPRS"),
            ],
            quotes={
                "TSLA": _quote(80.0, "USD"),
                "TUPRS": _quote(80.0, "TRY"),
            },
            usdtry=40.0,
        )
        view = _build_view(wealth, prices, fx)
        by_symbol = {row.symbol: row for row in view.priced_positions}
        self.assertIn("TUPRS", by_symbol)
        self.assertAlmostEqual(view.priced_total_market_value, 100.0)
        self.assertAlmostEqual(by_symbol["TUPRS"].weight_pct, 20.0)
        self.assertAlmostEqual(by_symbol["TSLA"].weight_pct, 80.0)


class DecisionIntelligenceGuardTests(unittest.TestCase):
    def test_incomplete_valuation_guard_while_evidence_missing(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 10)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(None, "TRY", available=False)},
            usdtry=None,
        )
        view = _build_view(wealth, prices, fx)
        current = current_wealth_from_portfolio_view(view)
        decision = build_portfolio_decision(
            view,
            as_of_date=AS_OF,
            current_wealth=current,
            fx_schedule=schedule_from_mapping(PLANNING_FX),
            conversion=planning_conversion(Decimal("51")),
            contribution_tracking_start=TRACKING_START,
        )
        ids = {row.id for row in decision.actions}
        self.assertIn("incomplete_valuation", ids)
        self.assertNotIn("contribution_plan_below_required", ids)
        action = next(row for row in decision.actions if row.id == "incomplete_valuation")
        self.assertIn("TUPRS", action.context["missing_price_symbols"])
        self.assertIn("TUPRS", action.context["missing_fx_symbols"])

    def test_required_contribution_non_authoritative_while_partial(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 10)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(80.0, "TRY")},
            usdtry=None,
        )
        view = _build_view(wealth, prices, fx)
        decision = build_portfolio_decision(
            view,
            as_of_date=AS_OF,
            fx_schedule=schedule_from_mapping(PLANNING_FX),
            conversion=planning_conversion(Decimal("51")),
            contribution_tracking_start=TRACKING_START,
        )
        self.assertIn("incomplete_valuation", {row.id for row in decision.actions})
        self.assertNotIn(
            "contribution_plan_below_required",
            {row.id for row in decision.actions},
        )


class VisnAndContractSafetyTests(unittest.TestCase):
    def test_midas_visn_absent_ml_visn_833_unchanged(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("VISN", "asset-VISN", "acc-ml", 833)],
            assets=[_asset("VISN", "USD", "asset-VISN")],
            quotes={"VISN": _quote(11.5922, "USD")},
            usdtry=40.0,
        )
        view = _build_view(wealth, prices, fx)
        visn_rows = [
            row
            for row in list(view.priced_positions)
            + list(view.unpriced_positions)
            + list(view.foreign_currency_positions)
            if row.symbol == "VISN"
        ]
        self.assertEqual(len(visn_rows), 1)
        self.assertEqual(visn_rows[0].account_id, "acc-ml")
        self.assertAlmostEqual(visn_rows[0].quantity, 833)
        self.assertFalse(any(row.account_id == "acc-midas" for row in visn_rows))

    def test_contribution_tracking_start_remains_2026_09_01(self) -> None:
        from services.wealth_contribution_intelligence import (
            build_contribution_intelligence,
        )
        from services.wealth_external_cash_flow import ContributionTrackingScope
        from services.wealth_goal_models import CurrentWealthSnapshot

        self.assertEqual(TRACKING_START.isoformat(), "2026-09-01")
        intel = build_contribution_intelligence(
            as_of_date=AS_OF,
            current=CurrentWealthSnapshot(
                currency="USD",
                current_value_lower_bound=Decimal("58515.97"),
                valuation_complete=False,
            ),
            transactions=[],
            account_ids=["acc-1"],
            conversion=planning_conversion(Decimal("51")),
            fx_schedule=schedule_from_mapping(PLANNING_FX),
            contribution_tracking_start=TRACKING_START,
        )
        self.assertEqual(intel.contribution_tracking_start, TRACKING_START)
        self.assertEqual(
            intel.monthly_tracking_scope,
            ContributionTrackingScope.NOT_TRACKED,
        )
        source = Path("services/wealth_external_cash_flow.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("contribution_tracking_start_date = date(2026, 8", source)

    def test_planning_fx_schedule_unchanged(self) -> None:
        schedule = schedule_from_mapping(PLANNING_FX)
        self.assertEqual(schedule.usdtry_for_year(2026), Decimal("51"))
        self.assertEqual(schedule.usdtry_for_year(2027), Decimal("59"))
        self.assertEqual(schedule.usdtry_for_year(2028), Decimal("66"))
        self.assertEqual(schedule.usdtry_for_year(2029), Decimal("73"))
        self.assertEqual(schedule.usdtry_for_year(2030), Decimal("80"))
        self.assertEqual(schedule.usdtry_for_year(2031), Decimal("87"))

    def test_no_provider_calls_on_db_only_valuation(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 10)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(80.0, "TRY")},
            usdtry=40.0,
        )
        fmp = MagicMock()
        with patch(
            "services.candidate_price_service.CandidatePriceService",
            return_value=prices,
        ), patch(
            "services.portfolio_intelligence_service.FxRateService",
            return_value=fx,
        ), patch("services.fmp_client.FMPClient", return_value=fmp):
            view = _db_only_goal_view(wealth)
        self.assertIsNotNone(view)
        fmp.quote.assert_not_called()
        fmp.search_symbol.assert_not_called()
        self.assertEqual(fx.remote_calls, 0)
        for path in VALUATION_PATHS:
            source = path.read_text(encoding="utf-8").lower()
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token.lower(), source)

    def test_bist_provider_symbol_mapping_is_is_suffix(self) -> None:
        for symbol, name in (
            ("TUPRS", "Türkiye Petrol Rafinerileri A.S."),
            ("ASELS", "Aselsan Elektronik Sanayi ve Ticaret A.S. Class B"),
            ("BIMAS", "BIM Birlesik Magazalar A.S."),
        ):
            mapping = select_bist_provider_mapping(
                symbol,
                [
                    {
                        "symbol": f"{symbol}.IS",
                        "name": name,
                        "currency": "TRY",
                        "exchange": "IST",
                    }
                ],
            )
            self.assertEqual(mapping["provider_symbol"], f"{symbol}.IS")
            self.assertEqual(mapping["currency"], "TRY")
            self.assertEqual(mapping["market"], "TR")


class CandidatePriceCurrencyTests(unittest.TestCase):
    def test_bist_candidate_price_stays_try(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = [
            {
                "symbol": "TUPRS",
                "market": "TR",
                "currency": "TRY",
                "current_price": 187.4,
                "source_updated_at": "2026-08-18T10:00:00+00:00",
                "data_source": "FMP",
            }
        ]
        with patch(
            "services.candidate_price_service.CandidateRepository",
            return_value=repo,
        ):
            quote = CandidatePriceService(MagicMock()).get_quote_for_asset(
                "TUPRS", "equity", "TRY", market="TR"
            )
        self.assertTrue(quote.available)
        self.assertEqual(quote.currency, "TRY")
        self.assertAlmostEqual(quote.price, 187.4)
        self.assertEqual(quote.source, "candidate_snapshot")
        self.assertEqual(quote.as_of, "2026-08-18T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
