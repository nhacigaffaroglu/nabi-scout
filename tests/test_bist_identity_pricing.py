from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.bist_symbol_mapping import (
    BIST_PORTFOLIO_SYMBOLS,
    canonical_bist_identity,
    normalize_bist_symbol,
)
from services.candidate_price_service import CandidatePriceService
from services.hybrid_exposure_allocation_policy import (
    HybridPortfolioMode,
    resolve_hybrid_allocation_policy,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.portfolio_security_decision_contract import (
    DECISION_CONSIDER_TOP_UP,
    PortfolioSecurityContext,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_master_contract import (
    IDENTIFIER_TYPE_TICKER,
    INSTRUMENT_EQUITY,
    INSTRUMENT_ETF,
    INSTRUMENT_UNKNOWN,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNKNOWN,
    SOURCE_BIST,
    SOURCE_CANONICAL_STATIC,
    SOURCE_PRECEDENCE,
    SOURCE_US_LISTING,
    SecurityFact,
)
from services.security_master_service import SecurityMasterService
from services.wealth_asset_classification import resolve_asset_metadata
from services.wealth_contract import ASSET_CLASS_CASH, ASSET_CLASS_EQUITY, ASSET_CLASS_ETF


PILOT = ("ASELS", "BIMAS", "TUPRS")
DECISION_ENGINE = Path("services/portfolio_security_decision_engine.py")


def _listing(symbol: str, *, cik: str = "1", exchange: str = "NASDAQ") -> dict:
    return {
        "symbol": symbol,
        "company_name": f"{symbol} Corporation",
        "exchange": exchange,
        "cik": cik,
        "is_etf": False,
    }


def _price_service(repo) -> CandidatePriceService:
    with patch(
        "services.candidate_price_service.CandidateRepository",
        return_value=repo,
    ):
        return CandidatePriceService(MagicMock())


def _bist_snapshot(symbol: str, *, price, as_of: str = "2026-08-19") -> dict:
    return {
        "id": f"snap-{symbol}",
        "symbol": symbol,
        "market": "TR",
        "asset_type": "equity",
        "current_price": price,
        "currency": "TRY",
        "company_name": f"{symbol} A.S.",
        "source_updated_at": as_of,
    }


def _healthy_8e(**overrides) -> PortfolioSecurityContext:
    payload = dict(
        symbol="CRM",
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
        si_state=STATE_ATTRACTIVE,
        si_score=72.0,
        si_confidence=0.8,
        si_data_quality="STRONG",
        si_as_of="2026-08-29",
        is_holding=True,
        quantity=10.0,
        market_value=2500.0,
        portfolio_weight=5.0,
        concentration_ceiling=CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
        instrument_type=INSTRUMENT_EQUITY,
        market="US",
        as_of="2026-08-29",
    )
    payload.update(overrides)
    return PortfolioSecurityContext(**payload)


class BistSourceIdentityTests(unittest.TestCase):
    def test_pilot_resolves_via_bist_listing_not_static_allowlist(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        for symbol in PILOT:
            with self.subTest(symbol=symbol):
                resolution = master.resolve_security(symbol)
                identity = canonical_bist_identity(symbol)
                self.assertIsNotNone(identity)
                self.assertEqual(resolution.status, RESOLUTION_RESOLVED)
                self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)
                self.assertEqual(resolution.source, SOURCE_BIST)
                self.assertEqual(resolution.facts[0].exchange, "IST")
                self.assertEqual(resolution.facts[0].metadata.get("market"), "TR")
                self.assertEqual(resolution.facts[0].metadata.get("country"), "TR")
                self.assertEqual(resolution.facts[0].metadata.get("currency"), "TRY")
                self.assertEqual(resolution.facts[0].symbol, symbol)

    def test_bist_beats_canonical_static(self) -> None:
        master = SecurityMasterService()
        resolution = master.resolve_security("ASELS")
        self.assertEqual(resolution.source, SOURCE_BIST)
        self.assertNotEqual(resolution.source, SOURCE_CANONICAL_STATIC)
        sources = {fact.source for fact in resolution.facts}
        self.assertIn(SOURCE_CANONICAL_STATIC, sources)

    def test_us_listing_still_outranks_bist(self) -> None:
        master = SecurityMasterService(include_canonical_static=False, include_bist_listing=False)
        master.ingest_listing_facts([_listing("AAPL", cik="320193")])
        master.upsert_security_fact(
            SecurityFact(
                "AAPL",
                IDENTIFIER_TYPE_TICKER,
                INSTRUMENT_EQUITY,
                SOURCE_BIST,
                "2026-08-30T00:00:00+00:00",
                symbol="AAPL",
                exchange="IST",
                metadata={"market": "TR", "country": "TR", "currency": "TRY"},
            )
        )
        resolution = master.resolve_security("AAPL")
        self.assertEqual(resolution.status, RESOLUTION_RESOLVED)
        self.assertEqual(resolution.source, SOURCE_US_LISTING)
        self.assertLess(SOURCE_PRECEDENCE[SOURCE_US_LISTING], SOURCE_PRECEDENCE[SOURCE_BIST])

    def test_same_rank_conflict_remains_fail_closed(self) -> None:
        master = SecurityMasterService(include_canonical_static=False, include_bist_listing=False)
        master.upsert_security_fact(
            SecurityFact("ASELS", IDENTIFIER_TYPE_TICKER, INSTRUMENT_EQUITY, "alpha", "2026-01-01")
        )
        master.upsert_security_fact(
            SecurityFact("ASELS", IDENTIFIER_TYPE_TICKER, INSTRUMENT_ETF, "beta", "2026-08-01")
        )
        resolution = master.resolve_security("ASELS")
        self.assertEqual(resolution.status, RESOLUTION_CONFLICT)
        self.assertEqual(resolution.instrument_type, INSTRUMENT_UNKNOWN)
        self.assertEqual(resolution.limitation, "SOURCE_CONFLICT")

    def test_name_does_not_invent_reit_or_fund(self) -> None:
        identity = canonical_bist_identity("ASELS")
        self.assertEqual(identity["instrument_type"], INSTRUMENT_EQUITY)
        self.assertNotIn("REIT", identity["issuer_name"].upper())
        self.assertNotEqual(identity["instrument_type"], INSTRUMENT_ETF)

    def test_unknown_suffix_is_not_guessed(self) -> None:
        self.assertIsNone(normalize_bist_symbol("FOO.IS"))
        self.assertIsNone(canonical_bist_identity("FOO.IS"))
        master = SecurityMasterService(include_canonical_static=False)
        self.assertEqual(master.resolve_security("FOO.IS").status, RESOLUTION_UNKNOWN)


class BistNormalizationTests(unittest.TestCase):
    def test_provider_forms_normalize_to_canonical(self) -> None:
        cases = {
            "ASELS": ("ASELS.IS", "ASELS.E", "ASELS.XIST", "asels.is"),
            "BIMAS": ("BIMAS.IS", "BIMAS.E", "BIMAS.XIST"),
            "TUPRS": ("TUPRS.IS", "TUPRS.E", "TUPRS.XIST"),
        }
        master = SecurityMasterService(include_canonical_static=False)
        for canonical, aliases in cases.items():
            for raw in aliases:
                with self.subTest(raw=raw):
                    self.assertEqual(normalize_bist_symbol(raw), canonical)
                    resolution = master.resolve_security(raw)
                    self.assertEqual(resolution.identifier, canonical)
                    self.assertEqual(resolution.source, SOURCE_BIST)
                    self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)

    def test_us_class_share_dot_is_not_treated_as_bist(self) -> None:
        self.assertIsNone(normalize_bist_symbol("BRK.B"))
        master = SecurityMasterService(include_canonical_static=False)
        self.assertEqual(master.resolve_security("BRK.B").identifier, "BRK-B")


class BistPersistedPriceTests(unittest.TestCase):
    def test_persisted_try_price_is_consumed(self) -> None:
        fixture_price = 403.0
        repo = MagicMock()
        repo.list_by_symbol.return_value = [_bist_snapshot("ASELS", price=fixture_price)]
        quote = _price_service(repo).get_quote_for_asset("ASELS", "equity", "TRY")
        self.assertTrue(quote.available)
        self.assertAlmostEqual(float(quote.price), fixture_price)
        self.assertEqual(quote.currency, "TRY")
        self.assertEqual(quote.as_of, "2026-08-19")
        self.assertEqual(quote.source, "candidate_snapshot")

    def test_provider_form_reads_canonical_snapshot(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = [_bist_snapshot("BIMAS", price=512.5)]
        quote = _price_service(repo).get_quote_for_asset("BIMAS.IS", "equity", "TRY")
        self.assertTrue(quote.available)
        self.assertEqual(quote.currency, "TRY")
        repo.list_by_symbol.assert_called_with("BIMAS")

    def test_missing_price_stays_missing(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = [_bist_snapshot("TUPRS", price=None)]
        quote = _price_service(repo).get_quote_for_asset("TUPRS", "equity", "TRY")
        self.assertFalse(quote.available)
        self.assertIsNone(quote.price)
        self.assertNotEqual(quote.price, 0)
        self.assertEqual(quote.error, "missing_price")
        self.assertEqual(quote.currency, "TRY")
        self.assertEqual(quote.source, "candidate_snapshot")

    def test_empty_rows_do_not_invent_price(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = []
        repo.get_by_symbol.return_value = None
        quote = _price_service(repo).get_quote_for_asset("ASELS", "equity", "TRY")
        self.assertFalse(quote.available)
        self.assertIsNone(quote.price)
        self.assertEqual(quote.error, "missing_price")


class SecurityFactsIdentityBridgeTests(unittest.TestCase):
    def test_identity_available_without_inventing_financials(self) -> None:
        facts = SecurityFactsService().build("ASELS", allow_sec_cache_replay=False)
        self.assertEqual(facts.symbol, "ASELS")
        self.assertEqual(facts.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(facts.exchange, "IST")
        self.assertEqual(facts.currency, "TRY")
        self.assertIn("security_master", facts.source)
        self.assertIsNone(facts.revenue)
        self.assertIsNone(facts.roic)
        self.assertIsNone(facts.pe)
        self.assertIsNone(facts.gross_margin)
        self.assertIn("revenue", facts.missing_critical_fields)
        self.assertLess(facts.completeness_pct, 20)

    def test_provider_form_bridges_to_canonical_symbol(self) -> None:
        facts = SecurityFactsService().build("TUPRS.E", allow_sec_cache_replay=False)
        self.assertEqual(facts.symbol, "TUPRS")
        self.assertEqual(facts.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(facts.currency, "TRY")
        self.assertIsNone(facts.net_income)

    def test_persisted_price_does_not_complete_financials(self) -> None:
        facts = SecurityFactsService().build(
            "BIMAS",
            candidate=_bist_snapshot("BIMAS", price=540.0),
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.price, 540.0)
        self.assertEqual(facts.currency, "TRY")
        self.assertIsNone(facts.revenue)
        self.assertIsNone(facts.market_cap)


class EightEBistEquitySupportedTests(unittest.TestCase):
    def test_pilot_symbols_are_no_longer_scope_blocked(self) -> None:
        for symbol in PILOT:
            with self.subTest(symbol=symbol):
                result = evaluate_portfolio_security_decision(
                    _healthy_8e(
                        symbol=symbol,
                        market="TR",
                        instrument_type=INSTRUMENT_EQUITY,
                        economic_exposure_status=HybridPortfolioMode.STRICT.value,
                    )
                )
                self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
                self.assertEqual(result.decision, DECISION_CONSIDER_TOP_UP)
                self.assertTrue(result.exposure_increase_allowed)

    def test_scope_uses_generic_equity_predicate(self) -> None:
        source = DECISION_ENGINE.read_text(encoding="utf-8")
        self.assertIn("supports_portfolio_decision", source)
        self.assertNotIn("if symbol in BIST_PORTFOLIO_SYMBOLS", source)
        self.assertIn("REASON_UNSUPPORTED_INSTRUMENT", source)
        self.assertEqual(BIST_PORTFOLIO_SYMBOLS, frozenset(PILOT))


class IdentityRegressionTests(unittest.TestCase):
    def test_aapl_remains_us_equity(self) -> None:
        master = SecurityMasterService()
        resolution = master.resolve_security("AAPL")
        self.assertEqual(resolution.status, RESOLUTION_RESOLVED)
        self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(resolution.source, SOURCE_CANONICAL_STATIC)
        self.assertNotEqual(resolution.source, SOURCE_BIST)
        asset_class, market, kind, status = resolve_asset_metadata("AAPL", currency="USD")
        self.assertEqual(asset_class, ASSET_CLASS_EQUITY)
        self.assertEqual(market, "US")
        self.assertEqual(kind, "equity")
        self.assertEqual(status, "RESOLVED")

    def test_crm_us_listing_unchanged(self) -> None:
        master = SecurityMasterService(include_canonical_static=False, include_bist_listing=False)
        master.ingest_listing_facts([_listing("CRM", cik="1108524")])
        resolution = master.resolve_security("CRM")
        self.assertEqual(resolution.source, SOURCE_US_LISTING)
        self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)
        asset_class, market, kind, status = resolve_asset_metadata("CRM", currency="USD")
        self.assertEqual((asset_class, market, kind, status), (ASSET_CLASS_EQUITY, "US", "equity", "RESOLVED"))

    def test_spus_remains_etf(self) -> None:
        master = SecurityMasterService()
        resolution = master.resolve_security("SPUS")
        self.assertNotEqual(resolution.source, SOURCE_BIST)
        self.assertNotEqual(resolution.instrument_type, INSTRUMENT_EQUITY)
        asset_class, market, kind, status = resolve_asset_metadata("SPUS", currency="USD")
        self.assertEqual(asset_class, ASSET_CLASS_ETF)
        self.assertEqual(kind, "etf")
        self.assertEqual(status, "RESOLVED")

    def test_cash_ticker_is_not_bist_and_listed_cash_is_equity(self) -> None:
        self.assertIsNone(normalize_bist_symbol("CASH"))
        master = SecurityMasterService()
        self.assertEqual(master.resolve_security("CASH").status, RESOLUTION_UNKNOWN)
        listed = SecurityMasterService(include_canonical_static=False)
        listed.ingest_listing_facts(
            [_listing("CASH", cik="907471", exchange="NASDAQ")]
        )
        resolution = listed.resolve_security("CASH")
        self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(resolution.source, SOURCE_US_LISTING)
        asset_class, _, kind, status = resolve_asset_metadata("CASH", currency="USD")
        self.assertEqual(asset_class, ASSET_CLASS_CASH)
        self.assertEqual(kind, "cash")
        self.assertEqual(status, "RESOLVED")

    def test_hybrid_and_8e_policy_untouched(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)


if __name__ == "__main__":
    unittest.main()
