from __future__ import annotations

import inspect
import json
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.candidate_price_service import CandidatePriceService
from services.nabi_intelligence_facade import InvestmentIntelligenceView
from services.participation_filter_service import (
    PARTICIPATION_FILTER_ALL,
    PARTICIPATION_FILTER_UYGUN,
    PARTICIPATION_FILTER_UYGUN_ONLY,
    PARTICIPATION_UNKNOWN,
    candidate_participation_status,
    filter_candidates_by_participation,
    matches_participation_filter,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_intelligence_contract import PriceQuote
from services.portfolio_intelligence_engine import rollup_portfolio_intelligence, value_position
from services.portfolio_intelligence_enrichment_service import (
    build_portfolio_intelligence_dashboard,
    classify_research_coverage,
    infer_research_allowed_from_status,
)
from services.portfolio_intelligence_enrichment_contract import (
    RESEARCH_COVERAGE_AVAILABLE,
    RESEARCH_COVERAGE_NOT_EVALUATED,
    RESEARCH_COVERAGE_REVIEW,
    RESEARCH_COVERAGE_UNAVAILABLE,
)
from services.portfolio_intelligence_helpers import iter_all_position_rows
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_research_context import (
    assert_portfolio_research_context_safe,
    build_context_from_view,
    build_portfolio_research_context,
)
from services.wealth_exposure_bridge import build_wealth_exposure_context
from services.wealth_price_service import WealthPriceService


def _intel(
    *,
    symbol="AAPL",
    status=None,
    research_status="YENI",
    has_candidate=True,
    has_snapshot=False,
    sector="Technology",
):
    return InvestmentIntelligenceView(
        symbol=symbol,
        market="US",
        company_name=f"{symbol} Inc",
        decision=None,
        nabi_score=80.0,
        participation_status=status,
        participation_score=None,
        research_status=research_status,
        sector_theme=sector,
        industry="Software",
        country="US",
        candidate_id="c1" if has_candidate else None,
        has_candidate=has_candidate,
        has_participation_snapshot=has_snapshot,
    )


def _priced_row(
    symbol="AAPL",
    *,
    quantity=10.0,
    average_cost=100.0,
    price=120.0,
    nabi=None,
    position_id="pos-1",
):
    quote = PriceQuote(price=price, currency="USD", available=True, source="test")
    row = value_position(
        position={
            "id": position_id,
            "account_id": "acc-1",
            "asset_id": f"asset-{symbol}",
            "quantity": quantity,
            "average_cost": average_cost,
            "cost_currency": "USD",
        },
        asset={"symbol": symbol, "asset_class": "equity", "currency": "USD"},
        account={"name": "Brokerage"},
        base_currency="USD",
        quote=quote,
    )
    if nabi is not None:
        from services.portfolio_intelligence_contract import PositionValuationRow

        row = PositionValuationRow(
            position_id=row.position_id,
            account_id=row.account_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            asset_class=row.asset_class,
            account_name=row.account_name,
            quantity=row.quantity,
            average_cost=row.average_cost,
            valuation_currency=row.valuation_currency,
            price=row.price,
            price_available=row.price_available,
            market_value=row.market_value,
            cost_basis=row.cost_basis,
            unrealized_pl=row.unrealized_pl,
            weight_pct=row.weight_pct,
            is_cash=row.is_cash,
            included_in_base_totals=row.included_in_base_totals,
            nabi=nabi,
        )
    return row


class ParticipationFilterTests(unittest.TestCase):
    def test_uygun_only_filter(self) -> None:
        self.assertTrue(
            matches_participation_filter(
                PARTICIPATION_STATUS_UYGUN,
                PARTICIPATION_FILTER_UYGUN_ONLY,
            )
        )
        self.assertFalse(
            matches_participation_filter(
                PARTICIPATION_STATUS_KONTROL_ET,
                PARTICIPATION_FILTER_UYGUN_ONLY,
            )
        )

    def test_candidate_filter_does_not_change_status(self) -> None:
        rows = [
            {"participation_status": PARTICIPATION_STATUS_UYGUN, "symbol": "A"},
            {"participation_status": PARTICIPATION_STATUS_UYGUN_DEGIL, "symbol": "B"},
        ]
        filtered = filter_candidates_by_participation(rows, PARTICIPATION_FILTER_UYGUN)
        self.assertEqual([row["symbol"] for row in filtered], ["A"])
        self.assertEqual(
            candidate_participation_status(rows[1]),
            PARTICIPATION_STATUS_UYGUN_DEGIL,
        )

    def test_unknown_status(self) -> None:
        self.assertEqual(candidate_participation_status({}), PARTICIPATION_UNKNOWN)


class ResearchCoverageTests(unittest.TestCase):
    def test_uygun_değil_unavailable(self) -> None:
        key, _ = classify_research_coverage(
            _intel(status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        self.assertEqual(key, RESEARCH_COVERAGE_UNAVAILABLE)

    def test_kontrol_et_review(self) -> None:
        key, _ = classify_research_coverage(
            _intel(status=PARTICIPATION_STATUS_KONTROL_ET)
        )
        self.assertEqual(key, RESEARCH_COVERAGE_REVIEW)

    def test_completed_research_available(self) -> None:
        key, _ = classify_research_coverage(
            _intel(status=PARTICIPATION_STATUS_UYGUN, research_status="TAMAMLANDI")
        )
        self.assertEqual(key, RESEARCH_COVERAGE_AVAILABLE)

    def test_research_allowed_not_equated_to_halal(self) -> None:
        self.assertTrue(infer_research_allowed_from_status(PARTICIPATION_STATUS_UYGUN))
        self.assertFalse(
            infer_research_allowed_from_status(PARTICIPATION_STATUS_KONTROL_ET)
        )
        self.assertIsNone(infer_research_allowed_from_status(None))


class EnrichmentAnalyticsTests(unittest.TestCase):
    def test_dashboard_weights_and_allocations(self) -> None:
        rows = [
            _priced_row(
                "AAPL",
                quantity=10,
                price=100,
                nabi=_intel(symbol="AAPL", status=PARTICIPATION_STATUS_UYGUN),
            ),
            _priced_row(
                "MSFT",
                quantity=5,
                price=200,
                position_id="pos-2",
                nabi=_intel(
                    symbol="MSFT",
                    status=PARTICIPATION_STATUS_UYGUN,
                    sector="Technology",
                ),
            ),
        ]
        base = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=rows,
            price_provider="test",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        dashboard = build_portfolio_intelligence_dashboard(base)
        self.assertAlmostEqual(dashboard.base.priced_total_market_value, 2000.0)
        weight_sum = sum(
            row.valuation.weight_pct or 0.0
            for row in dashboard.enriched_positions
            if row.valuation.weight_pct is not None
        )
        self.assertAlmostEqual(weight_sum, 100.0)
        self.assertGreater(dashboard.participation_eligible_weight_pct, 0.0)
        self.assertGreaterEqual(len(dashboard.sector_allocation), 1)

    def test_partial_price_coverage(self) -> None:
        priced = _priced_row("AAPL", price=100, nabi=_intel(symbol="AAPL"))
        unpriced = value_position(
            position={
                "id": "pos-u",
                "account_id": "acc-1",
                "asset_id": "asset-u",
                "quantity": 1,
                "average_cost": 50,
                "cost_currency": "USD",
            },
            asset={"symbol": "UNKNOWN", "asset_class": "equity", "currency": "USD"},
            account={"name": "Brokerage"},
            base_currency="USD",
            quote=PriceQuote(
                price=None,
                currency=None,
                available=False,
                source="test",
                error="missing_price",
            ),
        )
        base = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=[priced, unpriced],
            price_provider="test",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        dashboard = build_portfolio_intelligence_dashboard(base)
        self.assertFalse(dashboard.coverage.price_data_complete)
        self.assertIn("fiyat", dashboard.coverage.limitations[0].lower())

    def test_attention_items_generated(self) -> None:
        rows = [
            _priced_row(
                "BIG",
                quantity=90,
                price=100,
                nabi=_intel(symbol="BIG", status=PARTICIPATION_STATUS_KONTROL_ET),
            ),
            _priced_row(
                "SMALL",
                quantity=1,
                price=100,
                position_id="pos-2",
                nabi=_intel(symbol="SMALL"),
            ),
        ]
        base = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=rows,
            price_provider="test",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        dashboard = build_portfolio_intelligence_dashboard(base)
        codes = {item.code for item in dashboard.attention_items}
        self.assertTrue(
            any(code.startswith("PARTICIPATION_REVIEW_") for code in codes)
        )


class WealthExposureBridgeFixTests(unittest.TestCase):
    def test_iterates_priced_positions(self) -> None:
        row = _priced_row("AAPL", quantity=10, price=100)
        base = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=[row],
            price_provider="test",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        exposure = build_wealth_exposure_context(base, "AAPL")
        self.assertTrue(exposure.held)
        self.assertEqual(len(list(iter_all_position_rows(base))), 1)


class PortfolioResearchContextTests(unittest.TestCase):
    def test_context_serializes_without_secrets(self) -> None:
        row = _priced_row("AAPL", nabi=_intel(symbol="AAPL"))
        base = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=[row],
            price_provider="test",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        context = build_context_from_view(base)
        payload = context.to_dict()
        assert_portfolio_research_context_safe(payload)
        serialized = json.dumps(payload)
        self.assertNotIn("api_key", serialized.lower())
        self.assertNotIn("secret", serialized.lower())

    def test_forbidden_key_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assert_portfolio_research_context_safe({"summary": {"api_key": "x"}})


class CandidatePriceServiceTests(unittest.TestCase):
    def test_uses_candidate_snapshot_not_fmp(self) -> None:
        client = MagicMock()
        repo = MagicMock()
        repo.get_by_symbol.return_value = {"current_price": 42.5, "currency": "USD"}
        with patch(
            "services.candidate_price_service.CandidateRepository",
            return_value=repo,
        ):
            service = CandidatePriceService(client)
            quote = service.get_quote_for_asset("AAPL", "equity", "USD")
        self.assertTrue(quote.available)
        self.assertAlmostEqual(float(quote.price), 42.5)
        self.assertEqual(quote.source, "candidate_snapshot")


class ProviderSafetyTests(unittest.TestCase):
    def test_portfolio_page_module_has_no_llm_imports(self) -> None:
        source = Path("pages/11_Portfolio_Intelligence.py").read_text(encoding="utf-8")
        self.assertNotIn("CompanyIntelligence", source)
        self.assertNotIn("FMPClient", source)
        self.assertNotIn("load_adviser_llm_config", source)

    def test_enrichment_has_no_provider_calls(self) -> None:
        source = Path(
            "services/portfolio_intelligence_enrichment_service.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("FMPClient", source)
        self.assertNotIn("openai", source.lower())

    def test_build_view_with_null_fmp_fetch_count_zero(self) -> None:
        wealth = MagicMock()
        wealth.list_positions.return_value = []
        wealth.list_accounts.return_value = []
        wealth.list_assets.return_value = []
        service = PortfolioIntelligenceService(
            wealth,
            WealthPriceService(fmp_client=None),
        )
        view = service.build_view(
            {"id": "pf", "name": "Main", "base_currency": "USD"},
            enrich_nabi=False,
        )
        self.assertEqual(view.unique_price_symbols_fetched, 0)


class WealthRlsMigrationContractTests(unittest.TestCase):
    MIGRATION_PATH = Path("database/migration_wealth_core_phase1.sql")

    def test_wealth_tables_user_scoped(self) -> None:
        sql = self.MIGRATION_PATH.read_text(encoding="utf-8").lower()
        for table in (
            "wealth_portfolios",
            "wealth_positions",
        ):
            with self.subTest(table=table):
                self.assertIn(f"create table if not exists public.{table}", sql)
                self.assertIn("auth.uid() = user_id", sql)


class ImportScriptTests(unittest.TestCase):
    def test_csv_format_documented(self) -> None:
        source = Path("scripts/import_portfolio.py").read_text(encoding="utf-8")
        self.assertIn("symbol,quantity,average_cost,currency", source)

    def test_idempotent_skip_logic(self) -> None:
        from services.portfolio_import_service import import_portfolio_rows

        wealth = MagicMock()
        wealth.list_assets.return_value = [{"id": "a1", "symbol": "AAPL"}]
        wealth.list_positions.return_value = [{"asset_id": "a1", "quantity": 10.0}]
        summary = import_portfolio_rows(
            wealth,
            [{"symbol": "AAPL", "quantity": 10.0, "average_cost": 100, "currency": "USD"}],
        )
        self.assertEqual(summary["skipped"], 1)
        wealth.post_transaction.assert_not_called()


class CompanyReportIntegrationTests(unittest.TestCase):
    def test_company_report_has_participation_filter(self) -> None:
        source = Path("pages/4_Company_Report.py").read_text(encoding="utf-8")
        self.assertIn("filter_candidates_by_participation", source)
        self.assertIn("build_symbol_portfolio_context", source)

    def test_portfolio_context_service_no_fmp(self) -> None:
        source = Path("services/portfolio_context_service.py").read_text(encoding="utf-8")
        self.assertIn("CandidatePriceService", source)
        self.assertNotIn("FMPClient", source)


if __name__ == "__main__":
    unittest.main()
