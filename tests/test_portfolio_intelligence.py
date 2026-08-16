import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.fmp_client import FMPError
from services.nabi_intelligence_facade import InvestmentIntelligenceView
from services.portfolio_intelligence_contract import PriceQuote
from services.portfolio_intelligence_engine import (
    compute_cost_basis,
    compute_market_value,
    compute_unrealized_pl,
    rollup_portfolio_intelligence,
    value_position,
)
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.wealth_core_service import WealthCoreService
from services.wealth_price_service import WealthPriceService, is_cash_asset


class PortfolioIntelligenceEngineTests(unittest.TestCase):
    def _row(
        self,
        *,
        symbol="AAPL",
        asset_class="equity",
        currency="USD",
        quantity=10.0,
        average_cost=100.0,
        price=120.0,
    ):
        quote = PriceQuote(
            price=price,
            currency=currency,
            available=True,
            source="test",
        )
        return value_position(
            position={
                "id": "pos-1",
                "account_id": "acc-1",
                "asset_id": "asset-1",
                "quantity": quantity,
                "average_cost": average_cost,
                "cost_currency": currency,
            },
            asset={
                "symbol": symbol,
                "asset_class": asset_class,
                "currency": currency,
            },
            account={"name": "Brokerage"},
            base_currency="USD",
            quote=quote,
        )

    def test_valuation_math(self) -> None:
        self.assertAlmostEqual(compute_cost_basis(10, 100), 1000.0)
        self.assertAlmostEqual(compute_market_value(10, 120), 1200.0)
        self.assertAlmostEqual(compute_unrealized_pl(1200, 1000), 200.0)

        row = self._row()
        self.assertAlmostEqual(row.cost_basis, 1000.0)
        self.assertAlmostEqual(row.market_value, 1200.0)
        self.assertAlmostEqual(row.unrealized_pl, 200.0)

    def test_cash_nominal_valuation(self) -> None:
        service = WealthPriceService(fmp_client=None)
        quote = service.get_quote_for_asset("CASH", "cash", "USD")
        self.assertTrue(quote.available)
        self.assertAlmostEqual(float(quote.price), 1.0)

        row = value_position(
            position={
                "id": "pos-cash",
                "account_id": "acc-1",
                "asset_id": "asset-cash",
                "quantity": 5000.0,
                "average_cost": 1.0,
                "cost_currency": "USD",
            },
            asset={"symbol": "CASH", "asset_class": "cash", "currency": "USD"},
            account={"name": "Cash"},
            base_currency="USD",
            quote=quote,
        )
        self.assertTrue(row.is_cash)
        self.assertAlmostEqual(row.market_value, 5000.0)

    def test_missing_price_excluded_from_totals(self) -> None:
        quote = PriceQuote(
            price=None,
            currency=None,
            available=False,
            source="fmp",
            error="missing_price",
        )
        row = value_position(
            position={
                "id": "pos-1",
                "account_id": "acc-1",
                "asset_id": "asset-1",
                "quantity": 5,
                "average_cost": 50,
                "cost_currency": "USD",
            },
            asset={"symbol": "UNKNOWN", "asset_class": "equity", "currency": "USD"},
            account={"name": "Brokerage"},
            base_currency="USD",
            quote=quote,
        )
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=[row],
            price_provider="fmp",
            unique_price_symbols_fetched=1,
            valuation_errors=[],
        )
        self.assertEqual(view.priced_total_market_value, 0.0)
        self.assertEqual(view.unpriced_position_count, 1)
        self.assertIsNone(row.market_value)

    def test_weighted_rollups_and_concentration(self) -> None:
        rows = [
            self._row(symbol="AAPL", quantity=10, average_cost=100, price=100),
            self._row(symbol="MSFT", quantity=5, average_cost=200, price=200),
        ]
        rows[1] = value_position(
            position={
                "id": "pos-2",
                "account_id": "acc-1",
                "asset_id": "asset-2",
                "quantity": 5,
                "average_cost": 200,
                "cost_currency": "USD",
            },
            asset={"symbol": "MSFT", "asset_class": "equity", "currency": "USD"},
            account={"name": "Brokerage"},
            base_currency="USD",
            quote=PriceQuote(price=200, currency="USD", available=True, source="test"),
        )
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=rows,
            price_provider="fmp",
            unique_price_symbols_fetched=2,
            valuation_errors=[],
        )
        self.assertAlmostEqual(view.priced_total_market_value, 2000.0)
        self.assertAlmostEqual(view.priced_positions[0].weight_pct, 50.0)
        self.assertAlmostEqual(view.health.largest_position_weight_pct, 50.0)
        self.assertAlmostEqual(view.health.top3_concentration_pct, 100.0)

    def test_mixed_currency_fail_safe(self) -> None:
        usd_row = self._row(symbol="AAPL", currency="USD")
        eur_row = value_position(
            position={
                "id": "pos-eur",
                "account_id": "acc-eur",
                "asset_id": "asset-eur",
                "quantity": 2,
                "average_cost": 100,
                "cost_currency": "EUR",
            },
            asset={"symbol": "SAP", "asset_class": "equity", "currency": "EUR"},
            account={"name": "EU Broker"},
            base_currency="USD",
            quote=PriceQuote(price=150, currency="EUR", available=True, source="test"),
        )
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=[usd_row, eur_row],
            price_provider="fmp",
            unique_price_symbols_fetched=2,
            valuation_errors=[],
        )
        self.assertTrue(view.mixed_currency_warning)
        self.assertFalse(view.fx_supported)
        self.assertEqual(view.foreign_currency_position_count, 1)
        self.assertAlmostEqual(view.priced_total_market_value, 1200.0)
        self.assertEqual(len(view.foreign_currency_positions), 1)
        self.assertAlmostEqual(view.health.priced_position_coverage_pct, 100.0)

    def test_position_weights_sum_to_one_hundred(self) -> None:
        rows = [
            self._row(symbol="AAPL", quantity=10, average_cost=100, price=100),
            value_position(
                position={
                    "id": "pos-2",
                    "account_id": "acc-1",
                    "asset_id": "asset-2",
                    "quantity": 5,
                    "average_cost": 200,
                    "cost_currency": "USD",
                },
                asset={"symbol": "MSFT", "asset_class": "equity", "currency": "USD"},
                account={"name": "Brokerage"},
                base_currency="USD",
                quote=PriceQuote(price=200, currency="USD", available=True, source="test"),
            ),
        ]
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=rows,
            price_provider="fmp",
            unique_price_symbols_fetched=2,
            valuation_errors=[],
        )
        weight_sum = sum(row.weight_pct or 0.0 for row in view.priced_positions)
        self.assertAlmostEqual(weight_sum, 100.0)

    def test_foreign_unpriced_included_in_unpriced_count(self) -> None:
        eur_row = value_position(
            position={
                "id": "pos-eur",
                "account_id": "acc-eur",
                "asset_id": "asset-eur",
                "quantity": 2,
                "average_cost": 100,
                "cost_currency": "EUR",
            },
            asset={"symbol": "SAP", "asset_class": "equity", "currency": "EUR"},
            account={"name": "EU Broker"},
            base_currency="USD",
            quote=PriceQuote(
                price=None,
                currency=None,
                available=False,
                source="fmp",
                error="missing_price",
            ),
        )
        view = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=[eur_row],
            price_provider="fmp",
            unique_price_symbols_fetched=1,
            valuation_errors=[],
        )
        self.assertEqual(view.unpriced_position_count, 1)
        self.assertAlmostEqual(view.health.priced_position_coverage_pct, 0.0)


class WealthPriceServiceTests(unittest.TestCase):
    def test_provider_failure_returns_unavailable_not_zero(self) -> None:
        fmp = MagicMock()
        fmp.quote.side_effect = FMPError("rate limit", error_class="rate_limit")
        service = WealthPriceService(fmp)
        quote = service.get_quote_for_asset("AAPL", "equity", "USD")
        self.assertFalse(quote.available)
        self.assertIsNone(quote.price)

    def test_unique_symbol_prefetch_budget(self) -> None:
        fmp = MagicMock()
        fmp.quote.return_value = {"price": 10, "currency": "USD"}
        service = WealthPriceService(fmp)
        service.prefetch_assets(
            [
                ("AAPL", "equity", "USD"),
                ("AAPL", "equity", "USD"),
                ("MSFT", "equity", "USD"),
            ]
        )
        self.assertEqual(service.fetch_count, 2)
        self.assertEqual(fmp.quote.call_count, 2)

    def test_render_budget_aapl_two_accounts_msft_cash(self) -> None:
        fmp = MagicMock()
        fmp.quote.side_effect = lambda sym: {"price": 100, "currency": "USD", "symbol": sym}
        service = WealthPriceService(fmp)
        positions = [
            ("AAPL", "equity", "USD"),
            ("AAPL", "equity", "USD"),
            ("MSFT", "equity", "USD"),
            ("CASH", "cash", "USD"),
        ]
        service.prefetch_assets(positions)
        for item in positions:
            service.get_quote_for_asset(*item)
        self.assertEqual(fmp.quote.call_count, 2)
        self.assertEqual(service.fetch_count, 2)


class PortfolioIntelligenceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.wealth = WealthCoreService(MagicMock(), "user-a")
        self.price_service = WealthPriceService(fmp_client=None)

    def test_nabi_enrichment_does_not_alter_valuation(self) -> None:
        self.wealth.list_positions = MagicMock(
            return_value=[
                {
                    "id": "pos-1",
                    "account_id": "acc-1",
                    "asset_id": "asset-1",
                    "quantity": 10,
                    "average_cost": 100,
                    "cost_currency": "USD",
                }
            ]
        )
        self.wealth.list_accounts = MagicMock(
            return_value=[{"id": "acc-1", "name": "Brokerage"}]
        )
        self.wealth.list_assets = MagicMock(
            return_value=[
                {
                    "id": "asset-1",
                    "symbol": "AAPL",
                    "asset_class": "equity",
                    "currency": "USD",
                    "market": "US",
                }
            ]
        )

        quote = PriceQuote(price=120, currency="USD", available=True, source="test")
        self.price_service.get_quote_for_asset = MagicMock(return_value=quote)
        self.price_service.prefetch_assets = MagicMock()

        service_no_nabi = PortfolioIntelligenceService(self.wealth, self.price_service)
        view_plain = service_no_nabi.build_view(
            {"id": "pf-1", "name": "Main", "base_currency": "USD"},
            enrich_nabi=False,
        )

        intel = InvestmentIntelligenceView(
            symbol="AAPL",
            market="US",
            company_name="Apple",
            decision="İzle",
            nabi_score=99.0,
            participation_status="Uygun",
            participation_score=80,
            research_status="Aktif",
            sector_theme="Technology",
            industry="Consumer Electronics",
            country="US",
            candidate_id="cand-1",
            has_candidate=True,
            has_participation_snapshot=True,
        )
        service_with_nabi = PortfolioIntelligenceService(
            self.wealth,
            self.price_service,
            nabi_client=MagicMock(),
            intelligence_loader=lambda *_args, **_kwargs: intel,
        )
        view_enriched = service_with_nabi.build_view(
            {"id": "pf-1", "name": "Main", "base_currency": "USD"},
            enrich_nabi=True,
        )

        self.assertAlmostEqual(
            view_plain.priced_total_market_value,
            view_enriched.priced_total_market_value,
        )
        self.assertAlmostEqual(
            view_plain.priced_total_cost_basis,
            view_enriched.priced_total_cost_basis,
        )
        self.assertAlmostEqual(
            view_plain.priced_total_unrealized_pl,
            view_enriched.priced_total_unrealized_pl,
        )
        self.assertIsNotNone(view_enriched.priced_positions[0].nabi)
        self.assertEqual(view_enriched.priced_positions[0].nabi.nabi_score, 99.0)

    def test_provider_failure_yields_partial_view(self) -> None:
        self.wealth.list_positions = MagicMock(
            return_value=[
                {
                    "id": "pos-1",
                    "account_id": "acc-1",
                    "asset_id": "asset-1",
                    "quantity": 10,
                    "average_cost": 100,
                    "cost_currency": "USD",
                }
            ]
        )
        self.wealth.list_accounts = MagicMock(
            return_value=[{"id": "acc-1", "name": "Brokerage"}]
        )
        self.wealth.list_assets = MagicMock(
            return_value=[
                {
                    "id": "asset-1",
                    "symbol": "AAPL",
                    "asset_class": "equity",
                    "currency": "USD",
                }
            ]
        )
        fmp = MagicMock()
        fmp.quote.side_effect = FMPError("down", error_class="transient_http")
        service = PortfolioIntelligenceService(
            self.wealth,
            WealthPriceService(fmp),
        )
        view = service.build_view(
            {"id": "pf-1", "name": "Main", "base_currency": "USD"}
        )
        self.assertEqual(view.priced_position_count, 0)
        self.assertEqual(view.unpriced_position_count, 1)
        self.assertEqual(view.total_position_count, 1)


class PortfolioIntelligenceFirewallTests(unittest.TestCase):
    MODULES = (
        "services.wealth_price_service",
        "services.portfolio_intelligence_engine",
        "services.portfolio_intelligence_service",
        "services.portfolio_intelligence_contract",
    )
    FORBIDDEN = (
        "scanner_v",
        "nabi_score_v4",
        "decision_engine",
        "participation_business",
        "participation_financial",
        "participation_assessment_service",
        "manual_analysis_service",
        "investment_candidates",
    )

    def test_valuation_modules_have_no_forbidden_imports(self) -> None:
        for module_name in self.MODULES:
            module = __import__(module_name, fromlist=["*"])
            source = inspect.getsource(module)
            with self.subTest(module=module_name):
                for token in self.FORBIDDEN:
                    self.assertNotIn(token, source)

    def test_valuation_modules_do_not_write(self) -> None:
        for module_name in self.MODULES:
            source = Path(module_name.replace(".", "/") + ".py").read_text(
                encoding="utf-8"
            )
            with self.subTest(module=module_name):
                self.assertNotIn(".insert(", source)
                self.assertNotIn(".update(", source)
                self.assertNotIn(".delete(", source)
                self.assertNotIn(".upsert(", source)

    def test_is_cash_asset(self) -> None:
        self.assertTrue(is_cash_asset("CASH", "cash"))
        self.assertTrue(is_cash_asset("cash", "cash"))
        self.assertFalse(is_cash_asset("AAPL", "equity"))


if __name__ == "__main__":
    unittest.main()
