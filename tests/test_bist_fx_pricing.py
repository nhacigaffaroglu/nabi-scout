from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock

from services.bist_price_onboarding_service import onboard_bist_symbol
from services.bist_symbol_mapping import select_bist_provider_mapping
from services.candidate_identity import select_canonical_candidate
from services.fx_conversion_engine import apply_fx_to_position_rows
from services.fx_rate_refresh_service import FxRateRefreshService
from services.fx_rate_service import FxRateService
from services.wealth_price_service import normalize_currency
from tests.test_wave4_wealth_os import _position_row


BIMAS_SEARCH = [
    {
        "symbol": "BIMT",
        "name": "Bitmis Corp.",
        "currency": "USD",
        "exchange": "OTC",
    },
    {
        "symbol": "BIMAS.IS",
        "name": "BIM Birlesik Magazalar A.S.",
        "currency": "TRY",
        "exchange": "IST",
    },
]


class BistSymbolMappingTests(unittest.TestCase):
    def test_bimas_maps_to_is_try_istanbul_not_us(self) -> None:
        mapping = select_bist_provider_mapping("BIMAS", BIMAS_SEARCH)
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping["provider_symbol"], "BIMAS.IS")
        self.assertEqual(mapping["currency"], "TRY")
        self.assertEqual(mapping["exchange"], "IST")
        self.assertEqual(mapping["market"], "TR")

    def test_asels_and_tuprs_is_suffix(self) -> None:
        for symbol, name in (
            ("ASELS", "Aselsan Elektronik Sanayi ve Ticaret A.S. Class B"),
            ("TUPRS", "Türkiye Petrol Rafinerileri A.S."),
        ):
            mapping = select_bist_provider_mapping(
                symbol,
                [{"symbol": f"{symbol}.IS", "name": name, "currency": "TRY", "exchange": "IST"}],
            )
            self.assertEqual(mapping["provider_symbol"], f"{symbol}.IS")
            self.assertEqual(mapping["market"], "TR")

    def test_usd_only_hit_is_rejected(self) -> None:
        mapping = select_bist_provider_mapping(
            "BIMAS",
            [{"symbol": "BIMAS", "name": "Fake", "currency": "USD", "exchange": "NASDAQ"}],
        )
        self.assertIsNone(mapping)


class BistOnboardingTests(unittest.TestCase):
    def test_does_not_persist_without_price_and_does_not_use_abd(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = []
        fmp = MagicMock()
        fmp.search_symbol.return_value = BIMAS_SEARCH
        fmp.quote.side_effect = RuntimeError("FMP endpoint erişimi reddedildi: quote")
        result = onboard_bist_symbol("BIMAS", fmp_client=fmp, candidate_repo=repo)
        repo.upsert_by_symbol.assert_not_called()
        self.assertFalse(result["persisted"])
        self.assertEqual(result["status"], "no_price")
        self.assertEqual(result["provider_symbol"], "BIMAS.IS")
        self.assertNotEqual(result.get("market"), "ABD")
        self.assertNotEqual(result.get("market"), "US")

    def test_existing_abd_row_is_not_reused(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = [
            {"symbol": "BIMAS", "market": "ABD", "current_price": 12.0, "company_name": "BIMAS"}
        ]
        fmp = MagicMock()
        result = onboard_bist_symbol("BIMAS", fmp_client=fmp, candidate_repo=repo)
        fmp.quote.assert_not_called()
        repo.upsert_by_symbol.assert_not_called()
        self.assertEqual(result["status"], "us_contamination")

    def test_persists_tr_try_equity_when_quote_valid(self) -> None:
        saved = {
            "id": "bist-1",
            "symbol": "ASELS",
            "market": "TR",
            "currency": "TRY",
            "asset_type": "Hisse",
            "company_name": "Aselsan",
            "current_price": 180.5,
        }
        repo = MagicMock()
        repo.list_by_symbol.side_effect = [[], [saved]]
        repo.upsert_by_symbol.return_value = saved
        fmp = MagicMock()
        fmp.search_symbol.return_value = [
            {"symbol": "ASELS.IS", "name": "Aselsan", "currency": "TRY", "exchange": "IST"}
        ]
        fmp.quote.return_value = {
            "symbol": "ASELS.IS",
            "name": "Aselsan",
            "price": 180.5,
            "currency": "TRY",
            "exchange": "IST",
        }
        result = onboard_bist_symbol("ASELS", fmp_client=fmp, candidate_repo=repo)
        payload = repo.upsert_by_symbol.call_args.args[0]
        self.assertEqual(payload["symbol"], "ASELS")
        self.assertEqual(payload["market"], "TR")
        self.assertEqual(payload["currency"], "TRY")
        self.assertEqual(payload["asset_type"], "Hisse")
        self.assertNotEqual(payload["market"], "ABD")
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(result["duplicate_count"], 0)

    def test_canonical_tr_preferred_over_us_when_selecting(self) -> None:
        us = {"id": "us", "symbol": "TUPRS", "market": "US", "current_price": None, "company_name": "TUPRS"}
        tr = {
            "id": "tr",
            "symbol": "TUPRS",
            "market": "TR",
            "current_price": 170.0,
            "company_name": "Tüpraş",
        }
        selected = select_canonical_candidate([us, tr], preferred_market="TR")
        self.assertEqual(selected["id"], "tr")


class CurrencyAliasTests(unittest.TestCase):
    def test_tl_normalizes_to_try(self) -> None:
        self.assertEqual(normalize_currency("TL"), "TRY")
        self.assertEqual(normalize_currency("try"), "TRY")
        self.assertEqual(normalize_currency("USD"), "USD")


class FxDirectionTests(unittest.TestCase):
    def _fx_service(self, rates: dict, *, rate_date: str | None = None) -> FxRateService:
        service = FxRateService(MagicMock())

        def _get_rate(*, base_currency, quote_currency, on_or_before=None):
            key = (base_currency, quote_currency)
            if key not in rates:
                return None
            return {
                "base_currency": base_currency,
                "quote_currency": quote_currency,
                "rate": rates[key],
                "rate_date": rate_date or date.today().isoformat(),
                "source": "test",
                "data_quality": "good",
            }

        service.repo.get_rate = MagicMock(side_effect=_get_rate)
        return service

    def test_try_amount_divides_by_try_per_usd(self) -> None:
        fx = self._fx_service({("USD", "TRY"): 40.0})
        result = fx.convert_amount(amount=400.0, from_currency="TRY", to_currency="USD")
        self.assertTrue(result.converted)
        self.assertAlmostEqual(result.converted_amount, 10.0)
        self.assertAlmostEqual(result.rate_used, 40.0)

    def test_tl_alias_uses_try_rate(self) -> None:
        fx = self._fx_service({("USD", "TRY"): 40.0})
        result = fx.convert_amount(amount=800.0, from_currency="TL", to_currency="USD")
        self.assertTrue(result.converted)
        self.assertAlmostEqual(result.converted_amount, 20.0)

    def test_missing_fx_stays_unavailable_never_zero(self) -> None:
        fx = self._fx_service({})
        result = fx.convert_amount(amount=100.0, from_currency="TRY", to_currency="USD")
        self.assertTrue(result.unavailable)
        self.assertFalse(result.converted)
        self.assertIsNone(result.converted_amount)
        self.assertNotEqual(result.converted_amount, 0)

    def test_stale_rate_still_converts(self) -> None:
        stale_date = (date.today() - timedelta(days=8)).isoformat()
        fx = self._fx_service({("USD", "TRY"): 40.0}, rate_date=stale_date)
        result = fx.convert_amount(amount=40.0, from_currency="TRY", to_currency="USD")
        self.assertTrue(result.converted)
        self.assertTrue(result.stale)
        self.assertAlmostEqual(result.converted_amount, 1.0)

    def test_position_try_mv_converts_to_usd(self) -> None:
        rows = [_position_row(symbol="BIMAS", currency="TL", market_value=400.0, included=False)]
        fx = self._fx_service({("USD", "TRY"): 40.0})
        adjusted, totals = apply_fx_to_position_rows(rows, base_currency="USD", fx_service=fx)
        self.assertTrue(adjusted[0].fx_converted)
        self.assertAlmostEqual(adjusted[0].native_market_value, 400.0)
        self.assertAlmostEqual(adjusted[0].market_value, 10.0)
        self.assertAlmostEqual(adjusted[0].price, 100.0)
        self.assertEqual(adjusted[0].valuation_currency, "TRY")
        self.assertAlmostEqual(totals.converted_market_value, 10.0)
        self.assertTrue(adjusted[0].included_in_base_totals)

    def test_usdtry_fetch_uses_quote_per_base(self) -> None:
        fmp = MagicMock()

        def quote(symbol):
            if symbol == "USDTRY":
                return {"price": 40.0}
            if symbol == "TRYUSD":
                return {"price": 0.025}
            return {}

        fmp.quote.side_effect = quote
        service = FxRateRefreshService(MagicMock(), fmp_client=fmp)
        rate = service._fetch_rate("USD", "TRY")
        self.assertAlmostEqual(rate, 40.0)

    def test_inverts_when_only_inverse_pair_exists(self) -> None:
        fmp = MagicMock()

        def quote(symbol):
            if symbol == "USDEUR":
                return {}
            if symbol == "EURUSD":
                return {"price": 1.25}
            return {}

        fmp.quote.side_effect = quote
        service = FxRateRefreshService(MagicMock(), fmp_client=fmp)
        rate = service._fetch_rate("USD", "EUR")
        self.assertAlmostEqual(rate, 0.8)


class PiRenderIsolationTests(unittest.TestCase):
    def test_candidate_price_and_fx_services_have_no_remote_on_render(self) -> None:
        from pathlib import Path

        price_src = Path("services/candidate_price_service.py").read_text(encoding="utf-8")
        fx_src = Path("services/fx_rate_service.py").read_text(encoding="utf-8")
        pi_src = Path("services/portfolio_intelligence_service.py").read_text(encoding="utf-8")
        self.assertNotIn("FMPClient", price_src)
        self.assertNotIn("FMPClient", fx_src)
        self.assertNotIn("FMPClient", pi_src)
        self.assertIn("no remote calls on render", fx_src)


if __name__ == "__main__":
    unittest.main()
