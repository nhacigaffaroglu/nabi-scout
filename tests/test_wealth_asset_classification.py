from __future__ import annotations

import unittest
from pathlib import Path

from unittest.mock import MagicMock

from services.wealth_asset_classification import resolve_asset_metadata
from services.wealth_contract import ASSET_CLASS_EQUITY, ASSET_CLASS_ETF
from services.candidate_identity import (
    numeric_current_price,
    select_canonical_candidate,
)
from services.portfolio_candidate_onboarding_service import onboard_portfolio_symbol
from services.portfolio_management_service import PortfolioManagementService


class WealthAssetClassificationTests(unittest.TestCase):
    def test_visn_resolves_as_nasdaq_equity_not_etf(self) -> None:
        asset_class, market, kind, status = resolve_asset_metadata("VISN", currency="USD")
        self.assertEqual(asset_class, ASSET_CLASS_EQUITY)
        self.assertEqual(market, "US")
        self.assertEqual(kind, "equity")
        self.assertEqual(status, "RESOLVED")
        self.assertNotEqual(asset_class, ASSET_CLASS_ETF)
        self.assertNotEqual(kind, "etf")
        self.assertNotEqual(status, "REQUIRES_CONFIRMATION")

    def test_spre_and_spwo_resolve_as_etf(self) -> None:
        for symbol in ("SPRE", "SPWO"):
            asset_class, market, kind, status = resolve_asset_metadata(symbol, currency="USD")
            with self.subTest(symbol=symbol):
                self.assertEqual(asset_class, ASSET_CLASS_ETF)
                self.assertEqual(market, "US")
                self.assertEqual(kind, "etf")
                self.assertEqual(status, "RESOLVED")

    def test_turkish_equities_resolve_tr_market(self) -> None:
        for symbol in ("BIMAS", "ASELS", "TUPRS"):
            asset_class, market, kind, status = resolve_asset_metadata(symbol, currency="TRY")
            with self.subTest(symbol=symbol):
                self.assertEqual(asset_class, ASSET_CLASS_EQUITY)
                self.assertEqual(market, "TR")
                self.assertEqual(kind, "equity")
                self.assertEqual(status, "RESOLVED")

    def test_known_us_equities_unchanged(self) -> None:
        for symbol in ("MRVL", "TSLA", "UPS"):
            asset_class, market, kind, status = resolve_asset_metadata(symbol, currency="USD")
            with self.subTest(symbol=symbol):
                self.assertEqual(asset_class, ASSET_CLASS_EQUITY)
                self.assertEqual(market, "US")
                self.assertEqual(status, "RESOLVED")

    def test_turkish_funds_resolve_as_fund_tr_not_cash(self) -> None:
        from services.wealth_asset_classification import display_name_for
        from services.wealth_contract import ASSET_CLASS_CASH, ASSET_CLASS_FUND

        for symbol in ("AIS", "ZPE", "IAT"):
            asset_class, market, kind, status = resolve_asset_metadata(symbol, currency="TRY")
            with self.subTest(symbol=symbol):
                self.assertEqual(asset_class, ASSET_CLASS_FUND)
                self.assertEqual(market, "TR")
                self.assertEqual(kind, "fund")
                self.assertEqual(status, "RESOLVED")
                self.assertNotEqual(asset_class, ASSET_CLASS_CASH)
                self.assertNotEqual(kind, "cash")
                self.assertTrue(display_name_for(symbol))

        spus, spus_market, spus_kind, _ = resolve_asset_metadata("SPUS", currency="USD")
        self.assertEqual(spus, ASSET_CLASS_ETF)
        self.assertEqual(spus_market, "US")
        self.assertEqual(spus_kind, "etf")


class CandidateOnboardingSemanticsTests(unittest.TestCase):
    def test_canonical_selection_prefers_priced_row(self) -> None:
        stub = {
            "id": "stub",
            "symbol": "TSLA",
            "market": "US",
            "company_name": "TSLA",
            "current_price": None,
            "data_source": "universe_expansion",
        }
        priced = {
            "id": "priced",
            "symbol": "TSLA",
            "market": "ABD",
            "company_name": "Tesla, Inc.",
            "current_price": 250.0,
            "data_source": "SEC + FMP",
        }
        selected = select_canonical_candidate([stub, priced])
        self.assertEqual(selected["id"], "priced")
        self.assertAlmostEqual(numeric_current_price(selected), 250.0)

    def test_missing_persisted_price_stays_none(self) -> None:
        self.assertIsNone(numeric_current_price(None))
        self.assertIsNone(numeric_current_price({"current_price": None}))
        self.assertIsNone(numeric_current_price({"current_price": 0}))

    def test_candidate_price_service_has_no_remote_providers(self) -> None:
        source = Path("services/candidate_price_service.py").read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertNotIn("fmpclient", lowered)
        self.assertNotIn("openai", lowered)
        self.assertNotIn("secfinancial", lowered)
        self.assertNotIn("alphavantage", lowered)

    def test_pi_service_does_not_construct_fmp_on_render(self) -> None:
        source = Path("services/portfolio_intelligence_service.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("FMPClient", source)
        self.assertNotIn("openai", source.lower())


class PortfolioSymbolOnboardingTests(unittest.TestCase):
    def test_already_priced_skips_collector_and_does_not_duplicate(self) -> None:
        existing = {
            "id": "priced",
            "symbol": "MRVL",
            "market": "ABD",
            "company_name": "Marvell Technology, Inc.",
            "current_price": 70.0,
            "asset_type": "Hisse",
        }
        repo = MagicMock()
        repo.list_by_symbol.return_value = [existing]
        collector = MagicMock()
        result = onboard_portfolio_symbol(
            "MRVL",
            collector=collector,
            candidate_repo=repo,
        )
        collector.collect.assert_not_called()
        repo.upsert_expansion_candidate.assert_not_called()
        repo.upsert_by_symbol.assert_not_called()
        self.assertEqual(result["status"], "already_priced")
        self.assertFalse(result["persisted"])
        self.assertEqual(result["fmp_calls"], 0)
        self.assertEqual(result["sec_calls"], 0)

    def test_new_symbol_uses_canonical_upsert_not_raw_insert(self) -> None:
        saved = {
            "id": "new",
            "symbol": "TSLA",
            "market": "ABD",
            "company_name": "Tesla, Inc.",
            "current_price": 250.0,
            "asset_type": "Hisse",
        }
        repo = MagicMock()
        repo.list_by_symbol.side_effect = [[], [saved]]
        repo.upsert_expansion_candidate.return_value = saved
        collector = MagicMock()
        collector.collect.return_value = {
            "candidate": {
                "symbol": "TSLA",
                "company_name": "Tesla, Inc.",
                "asset_type": "Hisse",
                "market": "ABD",
                "current_price": 250.0,
            },
            "endpoint_status": {"fmp_profile": "OK", "fmp_quote": "OK"},
            "errors": [],
        }
        result = onboard_portfolio_symbol(
            "TSLA",
            collector=collector,
            candidate_repo=repo,
        )
        collector.collect.assert_called_once_with("TSLA")
        repo.upsert_expansion_candidate.assert_called_once()
        repo.create.assert_not_called()
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(result["sec_calls"], 0)

    def test_missing_collector_price_does_not_persist(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = []
        collector = MagicMock()
        collector.collect.return_value = {
            "candidate": {
                "symbol": "UPS",
                "company_name": "United Parcel Service, Inc.",
                "asset_type": "Hisse",
                "market": "ABD",
                "current_price": None,
            },
            "endpoint_status": {"fmp_profile": "OK", "fmp_quote": "ERİŞİLEMEDİ"},
            "errors": ["FMP quote: fail"],
        }
        result = onboard_portfolio_symbol(
            "UPS",
            collector=collector,
            candidate_repo=repo,
        )
        repo.upsert_expansion_candidate.assert_not_called()
        self.assertEqual(result["status"], "no_price")
        self.assertIsNone(result["current_price"])
        self.assertEqual(
            result["failure_reason"],
            "collector_returned_no_numeric_current_price",
        )

    def test_visn_onboarding_forces_equity_asset_type(self) -> None:
        saved = {
            "id": "visn",
            "symbol": "VISN",
            "market": "ABD",
            "company_name": "VisionWave Holdings, Inc.",
            "current_price": 12.5,
            "asset_type": "Hisse",
        }
        repo = MagicMock()
        repo.list_by_symbol.side_effect = [[], [saved]]
        repo.upsert_expansion_candidate.return_value = saved
        collector = MagicMock()
        collector.collect.return_value = {
            "candidate": {
                "symbol": "VISN",
                "company_name": "VisionWave Holdings, Inc.",
                "asset_type": "ETF",
                "market": "ABD",
                "current_price": 12.5,
            },
            "endpoint_status": {},
            "errors": [],
        }
        result = onboard_portfolio_symbol(
            "VISN",
            collector=collector,
            candidate_repo=repo,
        )
        payload = repo.upsert_expansion_candidate.call_args.args[0]
        self.assertEqual(payload["asset_type"], "Hisse")
        self.assertEqual(result["provider_mismatch"]["provider"], "ETF")
        self.assertEqual(result["provider_mismatch"]["portfolio"], "Hisse")


class AddHoldingMarketResolutionTests(unittest.TestCase):
    def test_turkish_equity_registers_tr_market_not_us(self) -> None:
        wealth = MagicMock()
        wealth.register_asset.return_value = {"id": "asset-bimas"}
        wealth.post_transaction.return_value = {"id": "txn-1"}
        PortfolioManagementService(wealth).add_holding(
            account_id="acc-1",
            symbol="BIMAS",
            quantity=1,
            average_cost=10.0,
            currency="TRY",
            asset_class="equity",
            market="US",
        )
        kwargs = wealth.register_asset.call_args.kwargs
        self.assertEqual(kwargs["market"], "TR")
        self.assertEqual(kwargs["symbol"], "BIMAS")


if __name__ == "__main__":
    unittest.main()
