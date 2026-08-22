from __future__ import annotations

import inspect
import io
import unittest
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.request import Request

from services.bist_eod_bulletin import (
    BIST_EQUITY_CURRENCY,
    OFFICIAL_EOD_FIELD,
    BorsaIstanbulThbClient,
    candidate_trading_dates,
    official_equity_series,
    parse_thb_csv,
    resolve_latest_thb_bulletin,
    thb_download_url,
    thb_member_name,
)
from services.bist_price_onboarding_service import onboard_bist_symbol, persist_validated_bist_quote
from services.bist_symbol_mapping import (
    BORSA_ISTANBUL_EOD_PROVIDER_SERIES,
    borsa_istanbul_eod_series,
    canonical_bist_provider_mapping,
)
from services.current_market_data import (
    BorsaIstanbulEodMarketData,
    FmpCurrentMarketData,
    TwelveDataCurrentMarketData,
    fetch_equity_quote,
)
from services.current_market_data_contract import (
    PROVIDER_BORSA_ISTANBUL_EOD,
    PROVIDER_FMP,
    ProviderFailureClass,
    persistence_source,
)
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


FIXTURE = Path(__file__).parent / "fixtures" / "bist_thb_eod_sample.csv"
PLANNING_FX = {2026: 51, 2027: 59, 2028: 66, 2029: 73, 2030: 80, 2031: 87}
TRADING_DATE = date(2026, 8, 19)
EXPECTED = {
    "TUPRS": 395.5,
    "ASELS": 403.0,
    "BIMAS": 416.5,
}
VWAP = {
    "TUPRS": 387.639,
    "ASELS": 394.598,
    "BIMAS": 409.936,
}


def _fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _bulletin():
    return parse_thb_csv(
        _fixture_text(),
        source_file="thb202608191.csv",
        source_url=thb_download_url(TRADING_DATE),
    )


def _zip_for(day: date, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(thb_member_name(day), text.encode("utf-8"))
    return buffer.getvalue()


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeOpener:
    def __init__(self, payloads: dict) -> None:
        self.payloads = payloads
        self.requested_urls = []

    def __call__(self, request: Request, timeout=None):
        url = request.full_url
        self.requested_urls.append(url)
        payload = self.payloads.get(url)
        if payload is None:
            raise HTTPError(url, 404, "Not Found", hdrs={}, fp=None)
        return _FakeResponse(payload)


def _provider(text: str = None, as_of: date = TRADING_DATE) -> BorsaIstanbulEodMarketData:
    opener = _FakeOpener({thb_download_url(as_of): _zip_for(as_of, text or _fixture_text())})
    client = BorsaIstanbulThbClient(opener=opener, as_of=as_of)
    return BorsaIstanbulEodMarketData(client)


class OfficialThbParserTests(unittest.TestCase):
    def test_parses_official_eod_file_and_field(self) -> None:
        bulletin = _bulletin()
        self.assertEqual(bulletin.trading_date, TRADING_DATE)
        self.assertEqual(bulletin.source_file, "thb202608191.csv")
        self.assertTrue(bulletin.source_url.startswith("https://borsaistanbul.com/data/thb/"))
        for symbol, price in EXPECTED.items():
            quote = bulletin.quotes[symbol]
            self.assertEqual(quote.canonical_symbol, symbol)
            self.assertEqual(quote.instrument_series, f"{symbol}.E")
            self.assertEqual(quote.official_field, OFFICIAL_EOD_FIELD)
            self.assertEqual(quote.currency, BIST_EQUITY_CURRENCY)
            self.assertAlmostEqual(quote.closing_price, price)
            self.assertNotAlmostEqual(quote.closing_price, VWAP[symbol])
            self.assertNotEqual(quote.instrument_series, symbol)

    def test_aof_rows_are_not_used_as_equity_eod(self) -> None:
        bulletin = _bulletin()
        self.assertIn("TUPRS", bulletin.quotes)
        self.assertAlmostEqual(bulletin.quotes["TUPRS"].closing_price, 395.5)
        self.assertNotIn("TUPRS.AOF", {row.instrument_series for row in bulletin.quotes.values()})

    def test_invalid_and_missing_prices_rejected(self) -> None:
        bulletin = _bulletin()
        self.assertEqual(bulletin.rejected["FAKE0"], "invalid_or_missing_closing_price")
        self.assertEqual(bulletin.rejected["FAKE1"], "invalid_or_missing_closing_price")
        self.assertNotIn("FAKE0", bulletin.quotes)
        self.assertNotIn("GARAN", bulletin.quotes)


class BorsaIstanbulEodProviderTests(unittest.TestCase):
    def test_tuprs_asels_bimas_quotes(self) -> None:
        provider = _provider()
        for symbol, price in EXPECTED.items():
            result = provider.get_equity_quote(symbol, expected_currency="TRY", market="TR")
            self.assertTrue(result.ok)
            self.assertEqual(result.canonical_symbol, symbol)
            self.assertEqual(result.provider_symbol, f"{symbol}.E")
            self.assertEqual(result.provider, PROVIDER_BORSA_ISTANBUL_EOD)
            self.assertEqual(result.currency, "TRY")
            self.assertEqual(result.as_of, "2026-08-19")
            self.assertAlmostEqual(result.price, price)
            self.assertEqual(result.exchange, "XIST")
            self.assertEqual(persistence_source(result.provider), "BORSA_ISTANBUL_EOD")
            self.assertTrue(result.retrieved_at)

    def test_persist_validated_official_eod_quote(self) -> None:
        result = _provider().get_equity_quote("TUPRS", expected_currency="TRY", market="TR")
        self.assertTrue(result.ok)
        repo = MagicMock()
        repo.list_by_symbol.return_value = [{"id": "c-tuprs", "symbol": "TUPRS"}]
        repo.upsert_by_symbol.return_value = {
            "id": "c-tuprs",
            "symbol": "TUPRS",
            "current_price": result.price,
            "currency": "TRY",
            "data_source": PROVIDER_BORSA_ISTANBUL_EOD,
            "source_updated_at": result.as_of,
        }
        saved = persist_validated_bist_quote(result, repo)
        payload = repo.upsert_by_symbol.call_args.args[0]
        self.assertEqual(payload["symbol"], "TUPRS")
        self.assertEqual(payload["currency"], "TRY")
        self.assertEqual(payload["market"], "TR")
        self.assertEqual(payload["data_source"], PROVIDER_BORSA_ISTANBUL_EOD)
        self.assertEqual(payload["source_updated_at"], "2026-08-19")
        self.assertEqual(payload["current_price"], result.price)
        self.assertEqual(saved["data_source"], PROVIDER_BORSA_ISTANBUL_EOD)
        self.assertNotIn("wealth_planning_fx", payload)

    def test_canonical_symbols_unchanged(self) -> None:
        for symbol in ("TUPRS", "ASELS", "BIMAS"):
            self.assertEqual(borsa_istanbul_eod_series(symbol), f"{symbol}.E")
            self.assertEqual(BORSA_ISTANBUL_EOD_PROVIDER_SERIES[symbol], f"{symbol}.E")
            self.assertEqual(official_equity_series(symbol), f"{symbol}.E")
            mapping = canonical_bist_provider_mapping(symbol)
            self.assertEqual(mapping["portfolio_symbol"], symbol)

    def test_invalid_price_rejected(self) -> None:
        result = _provider().get_equity_quote("FAKE0", expected_currency="TRY", market="TR")
        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, ProviderFailureClass.MALFORMED_PRICE)
        self.assertIsNone(result.price)

    def test_missing_symbol_rejected_cleanly(self) -> None:
        result = _provider().get_equity_quote("GARAN", expected_currency="TRY", market="TR")
        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, ProviderFailureClass.UNSUPPORTED_SYMBOL)
        self.assertEqual(result.error, "bist_thb_symbol_missing")
        self.assertEqual(result.canonical_symbol, "GARAN")

    def test_try_currency_and_usd_rejected(self) -> None:
        ok = _provider().get_equity_quote("TUPRS", expected_currency="TRY", market="TR")
        self.assertEqual(ok.currency, "TRY")
        bad = _provider().get_equity_quote("TUPRS", expected_currency="USD", market="TR")
        self.assertFalse(bad.ok)
        self.assertEqual(bad.failure_class, ProviderFailureClass.CURRENCY_MISMATCH)

    def test_does_not_provide_fx_or_planning_fx(self) -> None:
        fx = _provider().get_fx_rate("USD", "TRY")
        self.assertFalse(fx.ok)
        self.assertEqual(fx.failure_class, ProviderFailureClass.ENDPOINT_UNAVAILABLE)
        source = Path("services/bist_eod_bulletin.py").read_text(encoding="utf-8")
        self.assertNotIn("wealth_planning_fx", source)
        self.assertNotIn("planning_fx", source)

    def test_no_production_persistence_in_capability_mode(self) -> None:
        repo = MagicMock()
        provider = _provider()
        result = provider.get_equity_quote("TUPRS", expected_currency="TRY", market="TR")
        self.assertTrue(result.ok)
        repo.upsert_by_symbol.assert_not_called()
        repo.list_by_symbol.assert_not_called()
        self.assertFalse(hasattr(provider, "persist"))
        self.assertNotIn("BorsaIstanbulEodMarketData", inspect.getsource(onboard_bist_symbol))
        self.assertNotIn("BORSA_ISTANBUL_EOD", inspect.getsource(onboard_bist_symbol))

    def test_weekend_uses_previous_completed_trading_day(self) -> None:
        friday = date(2026, 8, 14)
        saturday = date(2026, 8, 15)
        sunday = date(2026, 8, 16)
        self.assertEqual(candidate_trading_dates(saturday, max_trading_days=1), [friday])
        self.assertEqual(candidate_trading_dates(sunday, max_trading_days=1), [friday])
        opener = _FakeOpener({thb_download_url(friday): _zip_for(friday, _fixture_text())})
        bulletin = resolve_latest_thb_bulletin(as_of=saturday, opener=opener)
        self.assertEqual(bulletin.trading_date, TRADING_DATE)
        self.assertEqual(opener.requested_urls, [thb_download_url(friday)])
        self.assertNotIn(thb_download_url(saturday), opener.requested_urls)

    def test_previous_weekday_used_when_today_unpublished(self) -> None:
        today = date(2026, 8, 19)
        previous = date(2026, 8, 18)
        opener = _FakeOpener({thb_download_url(previous): _zip_for(previous, _fixture_text())})
        bulletin = resolve_latest_thb_bulletin(as_of=today, opener=opener)
        self.assertEqual(opener.requested_urls[0], thb_download_url(today))
        self.assertEqual(opener.requested_urls[1], thb_download_url(previous))
        self.assertEqual(bulletin.source_file, thb_member_name(previous))

    def test_not_wired_as_fmp_or_twelve_data_dependency(self) -> None:
        fmp = MagicMock()
        td = MagicMock()
        result = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=_provider(),
            fallbacks=[FmpCurrentMarketData(fmp), TwelveDataCurrentMarketData(td)],
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, PROVIDER_BORSA_ISTANBUL_EOD)
        fmp.quote.assert_not_called()
        td.quote.assert_not_called()

    def test_existing_fmp_fallback_chain_unchanged(self) -> None:
        fmp = MagicMock()
        fmp.quote.return_value = {
            "symbol": "TUPRS.IS",
            "price": 180.5,
            "currency": "TRY",
            "exchange": "IST",
            "timestamp": 1755600000,
        }
        result = fetch_equity_quote(
            "TUPRS",
            expected_currency="TRY",
            market="TR",
            primary=FmpCurrentMarketData(fmp),
        )
        self.assertEqual(result.provider, PROVIDER_FMP)
        self.assertAlmostEqual(result.price, 180.5)

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


class CapabilityIsolationTests(unittest.TestCase):
    def test_onboard_still_starts_at_fmp_not_official_eod(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = []
        fmp = MagicMock()
        fmp.quote.side_effect = RuntimeError("should stay isolated in this test")
        source = inspect.getsource(onboard_bist_symbol)
        self.assertIn("FmpCurrentMarketData", source)
        self.assertNotIn("BorsaIstanbulEodMarketData", source)

    def test_public_url_pattern(self) -> None:
        url = thb_download_url(date(2026, 8, 19))
        self.assertEqual(
            url,
            "https://borsaistanbul.com/data/thb/2026/08/thb202608191.zip",
        )
        self.assertNotIn("verda.borsaistanbul.com", url)
        self.assertNotIn("yahoo", url.lower())
