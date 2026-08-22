from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from repositories.fx_rate_repository import FxRateRepository
from services.bist_price_onboarding_service import persist_validated_bist_quote
from services.bist_symbol_mapping import twelve_data_bist_request
from services.current_market_data import (
    AlphaVantageCurrentMarketData,
    FmpCurrentMarketData,
    TwelveDataCurrentMarketData,
    fetch_equity_quote,
    fetch_fx_rate,
    phase_a_activation_allowed,
)
from services.current_market_data_contract import (
    PROVIDER_ALPHA_VANTAGE,
    PROVIDER_FMP,
    PROVIDER_TWELVE_DATA,
    EquityQuoteResult,
    FxRateResult,
    ProviderFailureClass,
    persistence_source,
)
from services.fmp_client import FMPError
from services.twelve_data_client import TwelveDataClient, TwelveDataError
from services.wealth_goal_models import current_wealth_from_portfolio_view
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


def _plan_restricted() -> FMPError:
    return FMPError(
        "FMP endpoint erişimi reddedildi: quote",
        error_class="plan_restricted",
        status_code=402,
        endpoint="quote",
    )


def _td_quote(symbol: str, price: str, *, currency="TRY", exchange="BIST", mic="XIST"):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "mic_code": mic,
        "currency": currency,
        "close": price,
        "datetime": "2026-08-19",
        "timestamp": 1755612266,
    }


def _ok_equity(symbol: str, price: float) -> EquityQuoteResult:
    return EquityQuoteResult(
        ok=True,
        canonical_symbol=symbol,
        provider=PROVIDER_TWELVE_DATA,
        provider_symbol=f"{symbol}@XIST",
        price=price,
        currency="TRY",
        as_of="2026-08-19",
        retrieved_at="2026-08-19T12:00:00+00:00",
        exchange="XIST",
    )


def _ok_fx(rate: float) -> FxRateResult:
    return FxRateResult(
        ok=True,
        base_currency="USD",
        quote_currency="TRY",
        rate=rate,
        provider=PROVIDER_TWELVE_DATA,
        as_of="2026-08-19T12:00:00+00:00",
        retrieved_at="2026-08-19T12:00:00+00:00",
    )


class TwelveDataSecretTests(unittest.TestCase):
    def test_secret_loads_without_exposure(self) -> None:
        with patch.dict("os.environ", {"TWELVE_DATA_API_KEY": "super-secret-td-key"}):
            client = TwelveDataClient.from_env()
        self.assertEqual(client.api_key, "super-secret-td-key")
        err = TwelveDataError("Twelve Data istek hatası.", error_class="auth")
        self.assertNotIn("super-secret-td-key", str(err))
        source = Path("services/twelve_data_client.py").read_text(encoding="utf-8")
        self.assertNotIn("super-secret-td-key", source)
        self.assertIn("TWELVE_DATA_API_KEY", source)
        self.assertIn("apikey=REDACTED", source)


class TwelveDataMappingTests(unittest.TestCase):
    def test_tuprs_xist_mapping(self) -> None:
        self.assertEqual(twelve_data_bist_request("TUPRS"), {"symbol": "TUPRS", "mic_code": "XIST"})

    def test_asels_xist_mapping(self) -> None:
        self.assertEqual(twelve_data_bist_request("ASELS"), {"symbol": "ASELS", "mic_code": "XIST"})

    def test_bimas_xist_mapping(self) -> None:
        self.assertEqual(twelve_data_bist_request("BIMAS"), {"symbol": "BIMAS", "mic_code": "XIST"})


class TwelveDataAdapterTests(unittest.TestCase):
    def test_bist_try_quote_normalization(self) -> None:
        td = MagicMock()
        td.quote.return_value = _td_quote("TUPRS", "204.5")
        result = TwelveDataCurrentMarketData(td).get_equity_quote(
            "TUPRS", expected_currency="TRY", market="TR"
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.canonical_symbol, "TUPRS")
        self.assertEqual(result.provider, PROVIDER_TWELVE_DATA)
        self.assertEqual(result.currency, "TRY")
        self.assertEqual(result.exchange, "XIST")
        self.assertAlmostEqual(result.price, 204.5)
        td.quote.assert_called_once_with("TUPRS", mic_code="XIST")

    def test_wrong_exchange_rejected(self) -> None:
        td = MagicMock()
        td.quote.return_value = _td_quote("TUPRS", "204.5", exchange="NASDAQ", mic="XNAS")
        result = TwelveDataCurrentMarketData(td).get_equity_quote(
            "TUPRS", expected_currency="TRY", market="TR"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, ProviderFailureClass.INVALID_SYMBOL_MAPPING)
        self.assertIsNone(result.price)

    def test_wrong_currency_rejected(self) -> None:
        td = MagicMock()
        td.quote.return_value = _td_quote("ASELS", "90", currency="USD")
        result = TwelveDataCurrentMarketData(td).get_equity_quote(
            "ASELS", expected_currency="TRY", market="TR"
        )
        self.assertEqual(result.failure_class, ProviderFailureClass.CURRENCY_MISMATCH)

    def test_invalid_price_rejected(self) -> None:
        td = MagicMock()
        td.quote.return_value = _td_quote("BIMAS", "0")
        result = TwelveDataCurrentMarketData(td).get_equity_quote(
            "BIMAS", expected_currency="TRY", market="TR"
        )
        self.assertEqual(result.failure_class, ProviderFailureClass.MALFORMED_PRICE)

    def test_usdtry_normalization(self) -> None:
        td = MagicMock()
        td.exchange_rate.return_value = {"symbol": "USD/TRY", "rate": 47.93, "timestamp": 1755612266}
        result = TwelveDataCurrentMarketData(td).get_fx_rate("USD", "TRY")
        self.assertTrue(result.ok)
        self.assertFalse(result.inverted)
        self.assertAlmostEqual(result.rate, 47.93)
        td.exchange_rate.assert_called_once_with("USD/TRY")

    def test_provenance_twelve_data(self) -> None:
        self.assertEqual(persistence_source(PROVIDER_TWELVE_DATA), "TWELVE_DATA")
        td = MagicMock()
        td.quote.return_value = _td_quote("TUPRS", "200")
        result = TwelveDataCurrentMarketData(td).get_equity_quote(
            "TUPRS", expected_currency="TRY", market="TR"
        )
        self.assertEqual(result.provider, PROVIDER_TWELVE_DATA)


class TwelveDataFallbackChainTests(unittest.TestCase):
    def test_fmp_success_stops_fallback(self) -> None:
        fmp = MagicMock()
        fmp.quote.return_value = {
            "symbol": "TUPRS.IS",
            "price": 180.5,
            "currency": "TRY",
            "exchange": "IST",
        }
        td = MagicMock()
        av = MagicMock()
        result = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(td), AlphaVantageCurrentMarketData(av)],
            skip_provider_names=(PROVIDER_ALPHA_VANTAGE,),
        )
        self.assertEqual(result.provider, PROVIDER_FMP)
        td.quote.assert_not_called()
        av.global_quote.assert_not_called()

    def test_fmp_plan_restricted_calls_twelve_data(self) -> None:
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        td = MagicMock()
        td.quote.return_value = _td_quote("TUPRS", "181.25")
        result = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(td)],
        )
        self.assertEqual(result.provider, PROVIDER_TWELVE_DATA)
        td.quote.assert_called_once()

    def test_twelve_data_valid_does_not_call_alpha_vantage(self) -> None:
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        td = MagicMock()
        td.quote.return_value = _td_quote("ASELS", "90")
        av = MagicMock()
        fetch_equity_quote(
            "ASELS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(td), AlphaVantageCurrentMarketData(av)],
            skip_provider_names=(PROVIDER_ALPHA_VANTAGE,),
        )
        av.global_quote.assert_not_called()

    def test_twelve_data_fx_fail_falls_back_to_alpha_vantage(self) -> None:
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        td = MagicMock()
        td.exchange_rate.side_effect = RuntimeError("td fx down")
        av = MagicMock()
        av.currency_exchange_rate.return_value = {
            "1. From_Currency Code": "USD",
            "3. To_Currency Code": "TRY",
            "5. Exchange Rate": "47.9",
            "6. Last Refreshed": "2026-08-19 15:04:26",
        }
        result = fetch_fx_rate(
            "USD",
            "TRY",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(td), AlphaVantageCurrentMarketData(av)],
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, PROVIDER_ALPHA_VANTAGE)
        self.assertAlmostEqual(result.rate, 47.9)
        av.currency_exchange_rate.assert_called()

    def test_bist_twelve_data_fail_does_not_use_alpha_vantage(self) -> None:
        fmp = MagicMock()
        fmp.quote.side_effect = _plan_restricted()
        td = MagicMock()
        td.quote.side_effect = RuntimeError("td equity down")
        av = MagicMock()
        av.global_quote.return_value = {
            "01. symbol": "TUPRS.IS",
            "05. price": "999",
            "07. latest trading day": "2026-08-19",
        }
        result = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
            fallbacks=[TwelveDataCurrentMarketData(td), AlphaVantageCurrentMarketData(av)],
            skip_provider_names=(PROVIDER_ALPHA_VANTAGE,),
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.price)
        av.global_quote.assert_not_called()

    def test_planning_fx_never_used(self) -> None:
        source = Path("services/current_market_data.py").read_text(encoding="utf-8")
        self.assertNotIn("usdtry_for_year", source)
        self.assertNotIn("wealth_planning_fx", source)


class PhaseAGateAndPersistenceTests(unittest.TestCase):
    def test_phase_a_partial_success_blocks_persistence(self) -> None:
        equities = [_ok_equity("TUPRS", 200), _ok_equity("ASELS", 90)]
        fx = _ok_fx(47.9)
        self.assertFalse(phase_a_activation_allowed(equities, fx))
        repo = MagicMock()
        if phase_a_activation_allowed(equities, fx):
            persist_validated_bist_quote(equities[0], repo)
        repo.upsert_by_symbol.assert_not_called()

    def test_complete_phase_a_permits_controlled_persistence(self) -> None:
        equities = [
            _ok_equity("TUPRS", 200),
            _ok_equity("ASELS", 90),
            _ok_equity("BIMAS", 500),
        ]
        fx = _ok_fx(47.9)
        self.assertTrue(phase_a_activation_allowed(equities, fx))
        repo = MagicMock()
        repo.list_by_symbol.return_value = [{"id": "c1", "symbol": "TUPRS", "current_price": 200}]
        repo.upsert_by_symbol.return_value = {
            "id": "c1",
            "symbol": "TUPRS",
            "current_price": 200,
            "currency": "TRY",
            "data_source": PROVIDER_TWELVE_DATA,
            "source_updated_at": "2026-08-19",
        }
        saved = persist_validated_bist_quote(equities[0], repo)
        payload = repo.upsert_by_symbol.call_args.args[0]
        self.assertEqual(payload["symbol"], "TUPRS")
        self.assertEqual(payload["currency"], "TRY")
        self.assertEqual(payload["data_source"], PROVIDER_TWELVE_DATA)
        self.assertEqual(saved["data_source"], PROVIDER_TWELVE_DATA)
        self.assertEqual(FxRateRepository.TABLE, "fx_rates")

    def test_persisted_bist_prices_clear_missing_price(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 1032)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(200.0, "TRY")},
            usdtry=None,
        )
        view = _build_view(wealth, prices, fx)
        current = current_wealth_from_portfolio_view(view)
        self.assertEqual(current.missing_price_symbols, ())
        self.assertIn("TUPRS", current.missing_fx_symbols)

    def test_persisted_usdtry_clears_missing_fx(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 1032)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(200.0, "TRY")},
            usdtry=47.9,
        )
        view = _build_view(wealth, prices, fx)
        current = current_wealth_from_portfolio_view(view)
        self.assertEqual(current.missing_fx_symbols, ())

    def test_full_evidence_can_clear_partial_valuation(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 1032)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(200.0, "TRY")},
            usdtry=47.9,
        )
        view = _build_view(wealth, prices, fx)
        current = current_wealth_from_portfolio_view(view)
        self.assertTrue(current.valuation_complete)

    def test_goal_center_uses_persisted_evidence(self) -> None:
        source = Path("components/wealth_goal_center_ui.py").read_text(encoding="utf-8")
        self.assertIn("CandidatePriceService", source)
        self.assertIn("nabi_client=None", source)
        wealth, prices, fx = _wealth(
            positions=[_position("TUPRS", "asset-TUPRS", "acc-tfk", 1032)],
            assets=[_asset("TUPRS", "TRY", "asset-TUPRS")],
            quotes={"TUPRS": _quote(200.0, "TRY")},
            usdtry=47.9,
        )
        view = _build_view(wealth, prices, fx)
        current = current_wealth_from_portfolio_view(view)
        self.assertNotAlmostEqual(float(current.current_value_lower_bound), 1032 * 200 / 51)
        self.assertAlmostEqual(float(current.current_value_lower_bound), 1032 * 200 / 47.9, places=4)

    def test_snapshot_valuation_contract_remains_identical(self) -> None:
        capture = Path("services/wealth_snapshot_capture_service.py").read_text(encoding="utf-8")
        self.assertIn("CandidatePriceService", capture)
        self.assertNotIn("TwelveDataClient", capture)
        self.assertNotIn("FxRateRefreshService", capture)

    def test_visn_integrity_unchanged(self) -> None:
        wealth, prices, fx = _wealth(
            positions=[_position("VISN", "asset-VISN", "acc-ml", 833)],
            assets=[_asset("VISN", "USD", "asset-VISN")],
            quotes={"VISN": _quote(11.5922, "USD")},
            usdtry=47.9,
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
        self.assertEqual(intel.monthly_tracking_scope, ContributionTrackingScope.NOT_TRACKED)


if __name__ == "__main__":
    unittest.main()
