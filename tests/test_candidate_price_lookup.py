from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.candidate_price_service import (
    CandidatePriceService,
    numeric_current_price,
    select_persisted_price_candidate,
)
from services.portfolio_intelligence_service import PortfolioIntelligenceService


AVGO_US_STUB = {
    "id": "46af331c",
    "symbol": "AVGO",
    "market": "US",
    "asset_type": "equity",
    "current_price": None,
    "currency": "USD",
    "company_name": "AVGO",
}
AVGO_ABD_PRICED = {
    "id": "4eace4a1",
    "symbol": "AVGO",
    "market": "ABD",
    "asset_type": "Hisse",
    "current_price": 392.99,
    "currency": "USD",
    "company_name": "Broadcom Inc.",
}


class SelectPersistedPriceCandidateTests(unittest.TestCase):
    def test_avgo_prefers_priced_abd_over_us_stub(self) -> None:
        selected = select_persisted_price_candidate(
            [AVGO_US_STUB, AVGO_ABD_PRICED],
            preferred_market="US",
        )
        self.assertEqual(selected["id"], AVGO_ABD_PRICED["id"])
        self.assertAlmostEqual(numeric_current_price(selected), 392.99)

    def test_get_by_symbol_first_row_would_be_unpriced(self) -> None:
        first = [AVGO_US_STUB, AVGO_ABD_PRICED][0]
        self.assertIsNone(numeric_current_price(first))

    def test_ups_missing_candidate_stays_none(self) -> None:
        self.assertIsNone(select_persisted_price_candidate([]))

    def test_missing_price_never_zero(self) -> None:
        selected = select_persisted_price_candidate(
            [{"symbol": "UPS", "market": "US", "current_price": None}]
        )
        self.assertIsNone(numeric_current_price(selected))
        self.assertIsNone(numeric_current_price({"current_price": 0}))
        self.assertIsNone(numeric_current_price({"current_price": "0"}))
        self.assertIsNone(numeric_current_price({"current_price": ""}))


class CandidatePriceLookupServiceTests(unittest.TestCase):
    def _service(self, repo) -> CandidatePriceService:
        with patch(
            "services.candidate_price_service.CandidateRepository",
            return_value=repo,
        ):
            return CandidatePriceService(MagicMock())

    def test_avgo_manual_equity_resolves_persisted_price(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = [AVGO_US_STUB, AVGO_ABD_PRICED]
        service = self._service(repo)
        quote = service.get_quote_for_asset("AVGO", "equity", "USD", market="US")
        self.assertTrue(quote.available)
        self.assertAlmostEqual(float(quote.price), 392.99)
        self.assertEqual(quote.source, "candidate_snapshot")
        repo.get_by_symbol.assert_not_called()

    def test_ups_missing_price_is_explicit_none(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = []
        repo.get_by_symbol.return_value = None
        service = self._service(repo)
        quote = service.get_quote_for_asset("UPS", "equity", "USD")
        self.assertFalse(quote.available)
        self.assertIsNone(quote.price)
        self.assertNotEqual(quote.price, 0)
        self.assertEqual(quote.error, "missing_price")

    def test_legacy_get_by_symbol_fallback(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = []
        repo.get_by_symbol.return_value = {
            "current_price": 42.5,
            "currency": "USD",
        }
        service = self._service(repo)
        quote = service.get_quote_for_asset("AAPL", "equity", "USD")
        self.assertTrue(quote.available)
        self.assertAlmostEqual(float(quote.price), 42.5)

    def test_source_has_no_live_providers(self) -> None:
        source = Path("services/candidate_price_service.py").read_text(
            encoding="utf-8"
        )
        lowered = source.lower()
        self.assertNotIn("fmpclient", lowered)
        self.assertNotIn("openai", lowered)
        self.assertNotIn("secfinancial", lowered)
        self.assertNotIn("fmp_client", lowered)


class ManualHoldingPricePipelineTests(unittest.TestCase):
    def test_pi_render_prices_avgo_not_ups(self) -> None:
        repo = MagicMock()

        def list_by_symbol(symbol: str):
            if symbol == "AVGO":
                return [AVGO_US_STUB, AVGO_ABD_PRICED]
            return []

        repo.list_by_symbol.side_effect = list_by_symbol
        repo.get_by_symbol.return_value = None

        wealth = MagicMock()
        wealth.list_positions.return_value = [
            {
                "id": "pos-ups",
                "asset_id": "a-ups",
                "account_id": "acc",
                "quantity": 10,
                "average_cost": 102.17,
            },
            {
                "id": "pos-avgo",
                "asset_id": "a-avgo",
                "account_id": "acc",
                "quantity": 20,
                "average_cost": 305.58,
            },
        ]
        wealth.list_accounts.return_value = [
            {"id": "acc", "name": "TFK", "institution": "TFK"}
        ]
        wealth.list_assets.return_value = [
            {
                "id": "a-ups",
                "symbol": "UPS",
                "asset_class": "equity",
                "currency": "USD",
                "market": "US",
            },
            {
                "id": "a-avgo",
                "symbol": "AVGO",
                "asset_class": "equity",
                "currency": "USD",
                "market": "US",
            },
        ]

        with patch(
            "services.candidate_price_service.CandidateRepository",
            return_value=repo,
        ):
            price_service = CandidatePriceService(MagicMock())
            view = PortfolioIntelligenceService(wealth, price_service).build_view(
                {"id": "pf", "name": "Ana", "base_currency": "USD"},
                enrich_nabi=False,
            )

        by_symbol = {
            row.symbol: row
            for row in [*view.priced_positions, *view.unpriced_positions]
        }
        ups = by_symbol["UPS"]
        avgo = by_symbol["AVGO"]

        self.assertFalse(ups.price_available)
        self.assertIsNone(ups.price)
        self.assertIsNone(ups.market_value)
        self.assertIsNone(ups.unrealized_pl)
        self.assertIsNone(ups.weight_pct)

        self.assertTrue(avgo.price_available)
        self.assertAlmostEqual(float(avgo.price), 392.99)
        self.assertAlmostEqual(float(avgo.market_value), 20 * 392.99)
        self.assertIsNotNone(avgo.unrealized_pl)
        self.assertGreater(float(avgo.unrealized_pl), 0)
        self.assertEqual(view.unique_price_symbols_fetched, 2)

    def test_normal_render_does_not_instantiate_providers(self) -> None:
        with patch("services.fmp_client.FMPClient") as fmp:
            repo = MagicMock()
            repo.list_by_symbol.return_value = [AVGO_ABD_PRICED]
            with patch(
                "services.candidate_price_service.CandidateRepository",
                return_value=repo,
            ):
                service = CandidatePriceService(MagicMock())
                quote = service.get_quote_for_asset("AVGO", "equity", "USD")
            self.assertTrue(quote.available)
            fmp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
