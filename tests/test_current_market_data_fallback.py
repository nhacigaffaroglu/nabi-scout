from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from repositories.fx_rate_repository import FxRateRepository
from services.bist_price_onboarding_service import onboard_bist_symbol
from services.bist_symbol_mapping import alpha_vantage_bist_provider_symbol
from services.current_market_data import (
    AlphaVantageCurrentMarketData,
    FmpCurrentMarketData,
    TwelveDataCurrentMarketData,
    fetch_equity_quote,
    fetch_fx_rate,
)
from services.current_market_data_contract import (
    PROVIDER_ALPHA_VANTAGE,
    PROVIDER_FMP,
    PROVIDER_TWELVE_DATA,
    ProviderFailureClass,
    persistence_source,
)
from services.fmp_client import FMPError
from services.fx_rate_refresh_service import FxRateRefreshService
from services.portfolio_decision_intelligence import build_portfolio_decision
from services.wealth_goal_models import ProjectionLimitation, current_wealth_from_portfolio_view
from services.wealth_goal_planning import planning_conversion
from services.wealth_planning_fx import schedule_from_mapping
from tests.test_current_valuation_integrity import (
    TRACKING_START,
    _asset,
    _build_view,
    _position,
    _quote,
    _wealth,
)


PLANNING_FX = {2026: 51, 2027: 59, 2028: 66, 2029: 73, 2030: 80, 2031: 87}


def _plan_restricted(endpoint: str = "quote") -> FMPError:
    return FMPError(
        f"FMP endpoint erişimi reddedildi: {endpoint}",
        error_class="plan_restricted",
        status_code=402,
        endpoint=endpoint,
    )


def _av_quote(symbol: str, price: str, *, currency=None, exchange=None, as_of="2026-08-19"):
    row = {
        "01. symbol": symbol,
        "05. price": price,
        "07. latest trading day": as_of,
    }
    if currency is not None:
        row["currency"] = currency
    if exchange is not None:
        row["exchange"] = exchange
    return row


def _av_fx(*, from_code: str, to_code: str, rate: str, as_of="2026-08-19 12:00:00"):
    return {
        "1. From_Currency Code": from_code,
        "3. To_Currency Code": to_code,
        "5. Exchange Rate": rate,
        "6. Last Refreshed": as_of,
    }


class FallbackPolicyTests(unittest.TestCase):
    def test_fmp_success_does_not_call_fallback(self) -> None:
        fmp = MagicMock()
        fmp.quote.return_value = {
            "symbol": "TUPRS.IS",
            "price": 180.5,
            "currency": "TRY",
            "exchange": "IST",
            "timestamp": 1755600000,
        }
        av = MagicMock()
        result = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(MagicMock()), AlphaVantageCurrentMarketData(av)],
            skip_provider_names=(PROVIDER_ALPHA_VANTAGE,),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, PROVIDER_FMP)
        self.assertEqual(result.canonical_symbol, "TUPRS")
        self.assertEqual(result.provider_symbol, "TUPRS.IS")
        av.global_quote.assert_not_called()
        av.currency_exchange_rate.assert_not_called()
        fmp.quote.assert_called_once_with("TUPRS.IS")

    def test_fmp_plan_restricted_calls_fallback_equity(self) -> None:
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        td = MagicMock()
        td.quote.return_value = {
            "symbol": "TUPRS",
            "exchange": "BIST",
            "mic_code": "XIST",
            "currency": "TRY",
            "close": "181.25",
            "datetime": "2026-08-19",
        }
        av = MagicMock()
        result = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(td), AlphaVantageCurrentMarketData(av)],
            skip_provider_names=(PROVIDER_ALPHA_VANTAGE,),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, PROVIDER_TWELVE_DATA)
        self.assertEqual(result.canonical_symbol, "TUPRS")
        self.assertEqual(result.provider_symbol, "TUPRS@XIST")
        self.assertAlmostEqual(result.price, 181.25)
        self.assertEqual(result.currency, "TRY")
        td.quote.assert_called_once_with("TUPRS", mic_code="XIST")
        av.global_quote.assert_not_called()

    def test_fmp_plan_restricted_calls_fallback_fx(self) -> None:
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        av = MagicMock()
        av.currency_exchange_rate.return_value = _av_fx(
            from_code="USD",
            to_code="TRY",
            rate="41.5",
        )
        result = fetch_fx_rate(
            "USD",
            "TRY",
            primary=FmpCurrentMarketData(fmp),
            fallback=AlphaVantageCurrentMarketData(av),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, PROVIDER_ALPHA_VANTAGE)
        self.assertAlmostEqual(result.rate, 41.5)
        self.assertFalse(result.inverted)
        av.currency_exchange_rate.assert_called_once_with(
            from_currency="USD",
            to_currency="TRY",
        )

    def test_fallback_bist_try_accepted(self) -> None:
        td = MagicMock()
        td.quote.return_value = {
            "symbol": "ASELS",
            "exchange": "BIST",
            "mic_code": "XIST",
            "currency": "TRY",
            "close": "90.10",
        }
        result = TwelveDataCurrentMarketData(td).get_equity_quote(
            "ASELS",
            expected_currency="TRY",
            market="TR",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.currency, "TRY")
        self.assertAlmostEqual(result.price, 90.10)

    def test_fallback_wrong_currency_rejected_without_using_price(self) -> None:
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        td = MagicMock()
        td.quote.return_value = {
            "symbol": "BIMAS",
            "exchange": "BIST",
            "mic_code": "XIST",
            "currency": "USD",
            "close": "500.0",
        }
        av = MagicMock()
        result = fetch_equity_quote(
            "BIMAS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(td), AlphaVantageCurrentMarketData(av)],
            skip_provider_names=(PROVIDER_ALPHA_VANTAGE,),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, ProviderFailureClass.CURRENCY_MISMATCH)
        self.assertIsNone(result.price)
        av.global_quote.assert_not_called()

    def test_invalid_zero_negative_price_rejected(self) -> None:
        td = TwelveDataCurrentMarketData(MagicMock())
        for raw in ("0", "-12", "abc", ""):
            td._client.quote.return_value = {
                "symbol": "TUPRS",
                "exchange": "BIST",
                "mic_code": "XIST",
                "currency": "TRY",
                "close": raw,
            }
            result = td.get_equity_quote(
                "TUPRS",
                expected_currency="TRY",
                market="TR",
            )
            self.assertFalse(result.ok, raw)
            self.assertIn(
                result.failure_class,
                {
                    ProviderFailureClass.MALFORMED_PRICE,
                    ProviderFailureClass.UNSUPPORTED_SYMBOL,
                },
            )
            self.assertIsNone(result.price)

    def test_usdtry_normalization_is_try_per_usd(self) -> None:
        av = MagicMock()
        av.currency_exchange_rate.return_value = _av_fx(
            from_code="USD",
            to_code="TRY",
            rate="41.25",
        )
        result = AlphaVantageCurrentMarketData(av).get_fx_rate("USD", "TRY")
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.rate, 41.25)
        self.assertFalse(result.inverted)

    def test_tryusd_is_inverted_explicitly(self) -> None:
        av = MagicMock()

        def exchange(*, from_currency, to_currency):
            if from_currency == "USD" and to_currency == "TRY":
                raise RuntimeError("direct pair unavailable")
            if from_currency == "TRY" and to_currency == "USD":
                return _av_fx(from_code="TRY", to_code="USD", rate="0.025")
            raise AssertionError((from_currency, to_currency))

        av.currency_exchange_rate.side_effect = exchange
        result = AlphaVantageCurrentMarketData(av).get_fx_rate("USD", "TRY")
        self.assertTrue(result.ok)
        self.assertTrue(result.inverted)
        self.assertAlmostEqual(result.rate, 40.0)

    def test_malformed_primary_price_does_not_fallback(self) -> None:
        fmp = MagicMock()
        fmp.quote.return_value = {
            "symbol": "TUPRS.IS",
            "price": -1,
            "currency": "TRY",
            "exchange": "IST",
        }
        av = MagicMock()
        result = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(MagicMock()), AlphaVantageCurrentMarketData(av)],
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, ProviderFailureClass.MALFORMED_PRICE)
        av.global_quote.assert_not_called()

    def test_currency_mismatch_on_primary_does_not_fallback(self) -> None:
        fmp = MagicMock()
        fmp.quote.return_value = {
            "symbol": "TUPRS.IS",
            "price": 180.0,
            "currency": "USD",
            "exchange": "IST",
        }
        av = MagicMock()
        result = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(MagicMock()), AlphaVantageCurrentMarketData(av)],
        )
        self.assertEqual(result.failure_class, ProviderFailureClass.CURRENCY_MISMATCH)
        av.global_quote.assert_not_called()


class ProvenanceAndPersistenceTests(unittest.TestCase):
    def test_fallback_provider_stored_as_provenance(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.side_effect = [[], [{"id": "c1", "symbol": "TUPRS", "current_price": 181.25}]]
        repo.upsert_by_symbol.return_value = {
            "id": "c1",
            "symbol": "TUPRS",
            "market": "TR",
            "currency": "TRY",
            "current_price": 181.25,
            "company_name": "Tüpraş",
        }
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        td = MagicMock()
        td.quote.return_value = {
            "symbol": "TUPRS",
            "exchange": "BIST",
            "mic_code": "XIST",
            "currency": "TRY",
            "close": "181.25",
        }
        result = onboard_bist_symbol(
            "TUPRS",
            fmp_client=fmp,
            candidate_repo=repo,
            twelve_data_client=td,
            alpha_vantage_client=MagicMock(),
        )
        payload = repo.upsert_by_symbol.call_args.args[0]
        self.assertTrue(result["persisted"])
        self.assertEqual(payload["symbol"], "TUPRS")
        self.assertEqual(payload["data_source"], PROVIDER_TWELVE_DATA)
        self.assertNotEqual(payload["data_source"], PROVIDER_FMP)
        self.assertEqual(payload["currency"], "TRY")
        self.assertEqual(payload["market"], "TR")
        self.assertIn("provider_symbol=TUPRS@XIST", payload["collector_notes"])
        self.assertEqual(result["provider"], PROVIDER_TWELVE_DATA)

    def test_canonical_symbol_unchanged_and_provider_symbol_adapter_local(self) -> None:
        self.assertEqual(alpha_vantage_bist_provider_symbol("TUPRS"), "TUPRS.IS")
        self.assertEqual(alpha_vantage_bist_provider_symbol("ASELS"), "ASELS.IS")
        self.assertEqual(alpha_vantage_bist_provider_symbol("BIMAS"), "BIMAS.IS")
        td = MagicMock()
        td.quote.return_value = {
            "symbol": "BIMAS",
            "exchange": "BIST",
            "mic_code": "XIST",
            "currency": "TRY",
            "close": "500",
        }
        result = TwelveDataCurrentMarketData(td).get_equity_quote(
            "BIMAS",
            expected_currency="TRY",
            market="TR",
        )
        self.assertEqual(result.canonical_symbol, "BIMAS")
        self.assertEqual(result.provider_symbol, "BIMAS@XIST")
        td.quote.assert_called_once_with("BIMAS", mic_code="XIST")

    def test_persistence_destination_unchanged(self) -> None:
        self.assertEqual(FxRateRepository.TABLE, "fx_rates")
        self.assertEqual(persistence_source(PROVIDER_FMP), "fmp_quote")
        self.assertEqual(persistence_source(PROVIDER_TWELVE_DATA), "TWELVE_DATA")
        client = MagicMock()
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        td = MagicMock()
        td.exchange_rate.return_value = {
            "symbol": "USD/TRY",
            "rate": 41.5,
            "timestamp": 1755612266,
        }
        av = MagicMock()
        service = FxRateRefreshService(
            client,
            fmp_client=fmp,
            twelve_data_client=td,
            alpha_vantage_client=av,
        )
        updated = service.refresh_pairs(pairs=(("USD", "TRY"),), rate_date=date(2026, 8, 19))
        self.assertEqual(updated, 1)
        client.table.assert_called_with("fx_rates")
        onboard_source = Path("services/bist_price_onboarding_service.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("candidate_repo.upsert_by_symbol", onboard_source)
        self.assertNotIn("bist_prices", onboard_source)
        self.assertNotIn("alpha_vantage_quotes", onboard_source)

    def test_planning_fx_and_cost_basis_never_used(self) -> None:
        market_source = Path("services/current_market_data.py").read_text(encoding="utf-8")
        for token in (
            "planning_fx",
            "usdtry_for_year",
            "average_cost",
            "cost_basis",
            "wealth_planning_fx",
        ):
            self.assertNotIn(token, market_source)
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        av = MagicMock()
        av.global_quote.side_effect = RuntimeError("av down")
        av.currency_exchange_rate.side_effect = RuntimeError("av down")
        td = MagicMock()
        td.quote.side_effect = RuntimeError("td down")
        td.exchange_rate.side_effect = RuntimeError("td down")
        equity = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(td), AlphaVantageCurrentMarketData(av)],
            skip_provider_names=(PROVIDER_ALPHA_VANTAGE,),
        )
        fx = fetch_fx_rate(
            "USD",
            "TRY",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(td), AlphaVantageCurrentMarketData(av)],
        )
        self.assertFalse(equity.ok)
        self.assertFalse(fx.ok)
        self.assertIsNone(equity.price)
        self.assertIsNone(fx.rate)
        self.assertNotEqual(fx.rate, 51)

    def test_us_fmp_valuation_path_unchanged(self) -> None:
        fmp = MagicMock()
        fmp.quote.return_value = {
            "symbol": "AAPL",
            "price": 190.0,
            "currency": "USD",
            "exchange": "NASDAQ",
        }
        av = MagicMock()
        result = fetch_equity_quote(
            "AAPL",
            expected_currency="USD",
            market="US",
            primary=FmpCurrentMarketData(fmp),
            fallback=AlphaVantageCurrentMarketData(av),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, PROVIDER_FMP)
        self.assertEqual(result.canonical_symbol, "AAPL")
        self.assertEqual(result.provider_symbol, "AAPL")
        self.assertEqual(result.currency, "USD")
        av.global_quote.assert_not_called()
        fmp.quote.assert_called_once_with("AAPL")


class ValuationIntegrityFallbackTests(unittest.TestCase):
    def test_both_providers_fail_keeps_partial_valuation(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 1032)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(None, "TRY", available=False)},
            usdtry=None,
        )
        view = _build_view(wealth, prices, fx)
        current = current_wealth_from_portfolio_view(view)
        self.assertFalse(current.valuation_complete)
        self.assertIn("TUPRS", current.missing_price_symbols)
        self.assertIn("TUPRS", current.missing_fx_symbols)
        decision = build_portfolio_decision(
            view,
            as_of_date=date(2026, 8, 19),
            current_wealth=current,
            fx_schedule=schedule_from_mapping(PLANNING_FX),
            conversion=planning_conversion(Decimal("51")),
            contribution_tracking_start=TRACKING_START,
        )
        self.assertIn("incomplete_valuation", {row.id for row in decision.actions})
        self.assertIn("PARTIAL_VALUATION", current.unvalued_symbols + ("PARTIAL_VALUATION",))
        self.assertEqual(ProjectionLimitation.PARTIAL_VALUATION.value, "PARTIAL_VALUATION")

    def test_successful_fallback_evidence_clears_missing_price_and_fx(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 1032)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(180.5, "TRY")},
            usdtry=41.5,
        )
        view = _build_view(wealth, prices, fx)
        current = current_wealth_from_portfolio_view(view)
        self.assertEqual(current.missing_price_symbols, ())
        self.assertEqual(current.missing_fx_symbols, ())
        self.assertTrue(current.valuation_complete)

    def test_visn_integrity_unchanged(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("VISN", "asset-VISN", "acc-ml", 833)],
            assets=[_asset("VISN", "USD", "asset-VISN")],
            quotes={"VISN": _quote(11.5922, "USD")},
            usdtry=41.5,
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
        self.assertEqual(TRACKING_START.isoformat(), "2026-09-01")
        from services.wealth_contribution_intelligence import build_contribution_intelligence
        from services.wealth_external_cash_flow import ContributionTrackingScope
        from services.wealth_goal_models import CurrentWealthSnapshot

        intel = build_contribution_intelligence(
            as_of_date=date(2026, 8, 19),
            current=CurrentWealthSnapshot(
                currency="USD",
                current_value_lower_bound=Decimal("58503.9676"),
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


if __name__ == "__main__":
    unittest.main()
