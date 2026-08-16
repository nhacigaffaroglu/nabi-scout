from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from services.asset_capability_contract import (
    capability_for_asset_class,
    route_report_page,
)
from services.fund_holdings_service import aggregate_fund_participation
from services.fund_intelligence_contract import FundHoldingRow
from services.fund_lookthrough_engine import build_portfolio_lookthrough
from services.fx_conversion_engine import apply_fx_to_position_rows
from services.fx_rate_service import FxRateService
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.participation_filter_service import PARTICIPATION_UNKNOWN
from services.portfolio_intelligence_contract import (
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
    PriceQuote,
)
from services.portfolio_intelligence_engine import rollup_portfolio_intelligence, value_position
from services.total_wealth_service import compute_total_wealth_metrics
from services.wave4_monitor_detectors import detect_fx_stale_events, detect_missing_price_events


def _position_row(
    *,
    symbol: str = "AAPL",
    asset_class: str = "equity",
    currency: str = "USD",
    market_value: float = 1000.0,
    included: bool = True,
) -> PositionValuationRow:
    return PositionValuationRow(
        position_id="p1",
        account_id="a1",
        asset_id="as1",
        symbol=symbol,
        asset_class=asset_class,
        account_name="Broker",
        quantity=10.0,
        average_cost=90.0,
        valuation_currency=currency,
        price=100.0,
        price_available=True,
        market_value=market_value,
        cost_basis=900.0,
        unrealized_pl=100.0,
        weight_pct=None,
        is_cash=asset_class == "cash",
        included_in_base_totals=included,
    )


class AssetCapabilityTests(unittest.TestCase):
    def test_equity_routes_company_report(self) -> None:
        profile = capability_for_asset_class("equity")
        self.assertTrue(profile.company_report_eligible)
        self.assertEqual(route_report_page("equity"), "company_report")

    def test_etf_routes_fund_report(self) -> None:
        profile = capability_for_asset_class("etf")
        self.assertTrue(profile.fund_report_eligible)
        self.assertFalse(profile.company_report_eligible)
        self.assertEqual(route_report_page("etf"), "fund_report")

    def test_gold_not_equity_routing(self) -> None:
        profile = capability_for_asset_class("gold")
        self.assertEqual(route_report_page("gold"), "asset_detail")
        self.assertNotEqual(profile.pricing_method, "candidate_snapshot")

    def test_cash_not_researchable(self) -> None:
        profile = capability_for_asset_class("cash")
        self.assertEqual(profile.research_capability, "not_applicable")


class FxConversionTests(unittest.TestCase):
    def _fx_service(self, rates: dict) -> FxRateService:
        client = MagicMock()
        service = FxRateService(client)

        def _get_rate(*, base_currency, quote_currency, on_or_before=None):
            key = (base_currency, quote_currency)
            if key not in rates:
                return None
            return {
                "base_currency": base_currency,
                "quote_currency": quote_currency,
                "rate": rates[key],
                "rate_date": date.today().isoformat(),
                "source": "test",
                "data_quality": "good",
            }

        service.repo.get_rate = MagicMock(side_effect=_get_rate)
        return service

    def test_converts_foreign_position(self) -> None:
        rows = [_position_row(currency="EUR", market_value=100.0, included=False)]
        fx = self._fx_service({("USD", "EUR"): 0.5})
        adjusted, totals = apply_fx_to_position_rows(rows, base_currency="USD", fx_service=fx)
        self.assertTrue(adjusted[0].fx_converted)
        self.assertAlmostEqual(adjusted[0].market_value, 200.0)
        self.assertEqual(totals.converted_market_value, 200.0)

    def test_missing_rate_excluded(self) -> None:
        rows = [_position_row(currency="EUR", market_value=100.0, included=False)]
        fx = FxRateService(MagicMock())
        fx.repo.get_rate = MagicMock(return_value=None)
        adjusted, totals = apply_fx_to_position_rows(rows, base_currency="USD", fx_service=fx)
        self.assertTrue(adjusted[0].fx_unavailable)
        self.assertEqual(totals.unconverted_market_value, 100.0)

    def test_fx_service_has_zero_remote_calls_on_render(self) -> None:
        fx = FxRateService(MagicMock())
        fx.repo.get_rate = MagicMock(return_value=None)
        fx.convert_amount(amount=100.0, from_currency="EUR", to_currency="USD")
        self.assertEqual(fx.remote_calls, 0)


class FundLookThroughTests(unittest.TestCase):
    def test_partial_coverage_adds_unknown(self) -> None:
        holdings = (
            FundHoldingRow(
                underlying_symbol="MSFT",
                underlying_name="Microsoft",
                weight_pct=60.0,
                asset_type="equity",
                participation_status=PARTICIPATION_STATUS_UYGUN,
                research_status=None,
            ),
        )
        exposure = aggregate_fund_participation(holdings, coverage_pct=60.0)
        self.assertAlmostEqual(exposure.uygun_weight_pct, 60.0)
        self.assertAlmostEqual(exposure.unknown_weight_pct, 40.0)
        self.assertFalse(exposure.insufficient_evidence)

    def test_no_fake_halal_without_holdings(self) -> None:
        exposure = aggregate_fund_participation((), coverage_pct=None)
        self.assertTrue(exposure.insufficient_evidence)
        self.assertEqual(exposure.uygun_weight_pct, 0.0)

    def test_lookthrough_no_double_count(self) -> None:
        fund_service = MagicMock()
        fund_service.get_snapshot.return_value = MagicMock(
            holdings=(
                FundHoldingRow(
                    underlying_symbol="AAPL",
                    underlying_name="Apple",
                    weight_pct=100.0,
                    asset_type="equity",
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_status=None,
                ),
            ),
            coverage_pct=100.0,
        )
        view = build_portfolio_lookthrough(
            positions=[
                {
                    "symbol": "SPY",
                    "asset_class": "etf",
                    "weight_pct": 20.0,
                    "market_value": 2000.0,
                },
                {
                    "symbol": "AAPL",
                    "asset_class": "equity",
                    "weight_pct": 80.0,
                    "market_value": 8000.0,
                    "participation_status": PARTICIPATION_STATUS_UYGUN,
                },
            ],
            fund_service=fund_service,
            total_market_value=10000.0,
        )
        economic_keys = {row.key for row in view.economic_allocation}
        self.assertIn("AAPL", economic_keys)
        self.assertNotIn("SPY", economic_keys)


class MultiAssetLedgerTests(unittest.TestCase):
    def test_value_position_respects_asset_class(self) -> None:
        row = value_position(
            position={"id": "1", "account_id": "a", "quantity": 5, "average_cost": 10},
            asset={"symbol": "GLD", "asset_class": "gold", "currency": "USD"},
            account={"name": "Broker"},
            base_currency="USD",
            quote=PriceQuote(price=None, currency="USD", available=False, source="manual"),
        )
        self.assertFalse(row.price_available)
        self.assertEqual(row.asset_class, "gold")


class TotalWealthTests(unittest.TestCase):
    def test_partial_total_when_unpriced(self) -> None:
        view = PortfolioIntelligenceView(
            portfolio_id="p",
            portfolio_name="Test",
            base_currency="USD",
            priced_total_market_value=1000.0,
            priced_total_cost_basis=900.0,
            priced_total_unrealized_pl=100.0,
            priced_position_count=1,
            unpriced_position_count=2,
            foreign_currency_position_count=0,
            total_position_count=3,
            mixed_currency_warning=False,
            fx_supported=True,
            priced_positions=[_position_row()],
            unpriced_positions=[],
            foreign_currency_positions=[],
            asset_class_allocation=[],
            account_allocation=[],
            health=PortfolioHealthMetrics(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=33.0,
            ),
            valuation_errors=[],
            price_provider="none",
            unique_price_symbols_fetched=0,
        )
        metrics = compute_total_wealth_metrics(view)
        self.assertTrue(metrics.partial_total)
        self.assertEqual(metrics.unpriced_count, 2)


class MonitorWave4Tests(unittest.TestCase):
    def test_fx_stale_dedupe_key(self) -> None:
        drafts = detect_fx_stale_events(
            user_id="u1",
            portfolio_id="p1",
            stale_pairs=("USD/EUR",),
        )
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].event_type, "FX_RATE_STALE")

    def test_missing_price_events(self) -> None:
        drafts = detect_missing_price_events(
            user_id="u1",
            portfolio_id="p1",
            symbols=("GLD",),
        )
        self.assertEqual(drafts[0].event_type, "ASSET_PRICE_MISSING")


class CandidatePriceRoutingTests(unittest.TestCase):
    def test_gold_skips_candidate_lookup(self) -> None:
        from services.candidate_price_service import CandidatePriceService

        svc = CandidatePriceService(MagicMock())
        quote = svc.get_quote_for_asset("GLD", "gold", "USD")
        self.assertFalse(quote.available)
        self.assertEqual(quote.error, "unsupported_pricing")
        self.assertEqual(svc.fetch_count, 0)


if __name__ == "__main__":
    unittest.main()
