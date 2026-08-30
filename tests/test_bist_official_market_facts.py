from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from services.bist_eod_bulletin import parse_thb_csv, thb_download_url
from services.bist_official_market_facts import (
    CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS,
    CLASS_DIRECT_OFFICIAL,
    CLASS_INDEX_OR_MARKET_TOTAL,
    CLASS_NOT_AVAILABLE,
    CURRENCY_TRY,
    OFFICIAL_PUBLIC_MARKET_CAP_TOTALS,
    OFFICIAL_PUBLIC_PRICE_FILE,
    PAID_OR_CREDENTIALED,
    SHARE_COUNT_DECISION_BLOCKED,
    SHARE_COUNT_METHODOLOGY_UNRESOLVED,
    THB_NON_MARKET_CAP_FIELDS,
    canonical_multiple_readiness,
    classify_official_table,
    classify_share_count_evidence,
    derive_market_cap_from_official_components,
    market_facts_from_thb_bulletin,
    official_eod_series,
    parse_official_total_market_cap_csv,
    require_bist_symbol,
    share_count_decision,
    thb_headers_include_market_cap,
)
from services.bist_si_readiness import (
    DIM_MOMENTUM,
    DIM_VALUATION,
    STATUS_BLOCKED,
    audit_bist_si_readiness,
    inventory_kap_si_fields,
)
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.kap_financial_bridge import build_kap_normalized_bundle, kap_security_facts_payload
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_SI_MISSING,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import (
    AUTHORITY_BORSA_ISTANBUL,
    AUTHORITY_KAP,
    AUTHORITY_MIXED,
    AUTHORITY_SEC,
    PERIOD_FY,
    PERIOD_MIXED,
)
from services.security_intelligence_engine import evaluate_security_intelligence
from services.security_intelligence_service import SecurityIntelligenceService
from services.security_master_contract import INSTRUMENT_EQUITY
from tests.fixtures.kap_financial_pilot import asels_raw_lines


THB_FIXTURE = Path("tests/fixtures/bist_thb_eod_sample.csv")
TOTAL_MCAP_FIXTURE = Path("tests/fixtures/bist_official_total_market_cap.csv")
CONSTITUENT_FIXTURE = Path("tests/fixtures/bist_official_index_constituents.csv")
TRADING_DATE = date(2026, 8, 19)
SI_FIREWALL = Path("services/security_intelligence_contract.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
MARKET = Path("services/bist_official_market_facts.py")
FACTS = Path("services/security_facts_service.py")
SI_ENGINE = Path("services/security_intelligence_engine.py")


def _bulletin():
    return parse_thb_csv(
        THB_FIXTURE.read_text(encoding="utf-8"),
        source_file="thb202608191.csv",
        source_url=thb_download_url(TRADING_DATE),
    )


def _kap_payload(symbol: str = "ASELS"):
    return kap_security_facts_payload(build_kap_normalized_bundle(symbol, asels_raw_lines()))


class OfficialSourceParseTests(unittest.TestCase):
    def test_thb_parse_has_price_not_market_cap_or_shares(self) -> None:
        bulletin = _bulletin()
        facts = market_facts_from_thb_bulletin(bulletin, "ASELS")
        self.assertEqual(facts.price, 403.0)
        self.assertEqual(facts.currency, CURRENCY_TRY)
        self.assertEqual(facts.market_date, TRADING_DATE)
        self.assertEqual(facts.price_classification, CLASS_DIRECT_OFFICIAL)
        self.assertEqual(facts.market_cap_classification, CLASS_NOT_AVAILABLE)
        self.assertIsNone(facts.market_cap)
        self.assertIsNone(facts.shares_outstanding)
        self.assertEqual(facts.share_count_classification, SHARE_COUNT_METHODOLOGY_UNRESOLVED)
        self.assertEqual(facts.source, "BORSA_ISTANBUL")
        self.assertIn("thb", facts.source_url)
        raw = THB_FIXTURE.read_text(encoding="utf-8")
        headers = raw.splitlines()[1]
        self.assertFalse(thb_headers_include_market_cap(headers.split(";")))
        blob = raw.upper().replace("İ", "I")
        for blocked in THB_NON_MARKET_CAP_FIELDS:
            self.assertIn(blocked, blob)

    def test_total_market_cap_file_is_not_per_security(self) -> None:
        parsed = parse_official_total_market_cap_csv(
            TOTAL_MCAP_FIXTURE.read_text(encoding="utf-8")
        )
        self.assertFalse(parsed["per_security"])
        self.assertFalse(parsed["has_symbol_column"])
        self.assertEqual(parsed["classification"], CLASS_INDEX_OR_MARKET_TOTAL)
        self.assertEqual(parsed["source_url"], OFFICIAL_PUBLIC_MARKET_CAP_TOTALS["url"])
        self.assertIn("Toplam (Milyon TL)", parsed["headers"])
        self.assertNotIn("ASELS", TOTAL_MCAP_FIXTURE.read_text(encoding="utf-8"))

    def test_index_constituents_are_not_company_market_cap(self) -> None:
        text = CONSTITUENT_FIXTURE.read_text(encoding="utf-8")
        headers = text.splitlines()[0].split(";")
        classification = classify_official_table(
            headers=headers,
            has_symbol_column=True,
            title="Pay Endeks Raporu",
        )
        self.assertEqual(classification, CLASS_NOT_AVAILABLE)
        self.assertIn("ASELS.E", text)
        self.assertNotIn("PIYASA", text.upper())

    def test_official_catalog_documents_public_price_and_total_mcap(self) -> None:
        self.assertTrue(OFFICIAL_PUBLIC_PRICE_FILE["public"])
        self.assertFalse(OFFICIAL_PUBLIC_PRICE_FILE["authentication"])
        self.assertIsNone(OFFICIAL_PUBLIC_PRICE_FILE["market_cap_column"])
        self.assertFalse(OFFICIAL_PUBLIC_MARKET_CAP_TOTALS["per_security"])
        self.assertIn("datastore.borsaistanbul.com", PAID_OR_CREDENTIALED["datastore"])


class SymbolAndTryTests(unittest.TestCase):
    def test_symbol_normalization_and_series(self) -> None:
        self.assertEqual(require_bist_symbol("asels.e"), "ASELS")
        self.assertEqual(official_eod_series("bimas"), "BIMAS.E")
        with self.assertRaises(ValueError):
            require_bist_symbol("AAPL")
        with self.assertRaises(ValueError):
            require_bist_symbol("CRM")

    def test_try_currency_on_official_close(self) -> None:
        for symbol, expected in (("ASELS", 403.0), ("BIMAS", 416.5), ("TUPRS", 395.5)):
            facts = market_facts_from_thb_bulletin(_bulletin(), symbol)
            self.assertEqual(facts.currency, "TRY")
            self.assertEqual(facts.price, expected)
            self.assertEqual(facts.official_field, "CLOSING PRICE")


class ShareCountAndIssuedCapitalTests(unittest.TestCase):
    def test_issued_capital_money_is_not_share_count(self) -> None:
        result = classify_share_count_evidence(
            issued_capital_money=2_280_000_000.0,
            issued_capital_source="ifrs-full_IssuedCapital",
            assume_one_try_nominal=True,
        )
        self.assertIsNone(result["shares_outstanding"])
        self.assertEqual(result["classification"], SHARE_COUNT_METHODOLOGY_UNRESOLVED)

    def test_share_count_only_when_explicit_official_basis(self) -> None:
        direct = classify_share_count_evidence(
            share_quantity=4_560_000_000.0,
            share_quantity_source="official_issuer_share_quantity",
        )
        self.assertEqual(direct["classification"], CLASS_DIRECT_OFFICIAL)
        derived = classify_share_count_evidence(
            issued_capital_money=2_280_000_000.0,
            issued_capital_source="official_issued_capital",
            nominal_value_per_share=1.0,
            nominal_value_source="official_nominal_value",
        )
        self.assertEqual(derived["classification"], CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS)
        self.assertEqual(derived["shares_outstanding"], 2_280_000_000.0)
        ambiguous = classify_share_count_evidence(
            issued_capital_money=100.0,
            issued_capital_source="official_issued_capital",
            nominal_value_per_share=3.0,
            nominal_value_source="official_nominal_value",
        )
        self.assertEqual(ambiguous["classification"], SHARE_COUNT_METHODOLOGY_UNRESOLVED)
        self.assertEqual(
            share_count_decision(
                market_cap_classification=CLASS_NOT_AVAILABLE,
                share_count_classification=SHARE_COUNT_METHODOLOGY_UNRESOLVED,
            ),
            SHARE_COUNT_DECISION_BLOCKED,
        )

    def test_derived_mcap_requires_official_components(self) -> None:
        blocked = derive_market_cap_from_official_components(
            official_price=403.0,
            official_shares=2_280_000_000.0,
            price_source="thb",
            shares_source="guess",
            share_classification=SHARE_COUNT_METHODOLOGY_UNRESOLVED,
        )
        self.assertIsNone(blocked["market_cap"])
        ok = derive_market_cap_from_official_components(
            official_price=403.0,
            official_shares=1_000.0,
            price_source="thb",
            shares_source="official_share_quantity",
            share_classification=CLASS_DIRECT_OFFICIAL,
        )
        self.assertEqual(ok["classification"], CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS)
        self.assertEqual(ok["market_cap"], 403_000.0)


class CanonicalMultipleMethodologyTests(unittest.TestCase):
    def test_existing_pe_is_price_over_eps_not_mcap_over_income(self) -> None:
        facts = SecurityFactsService().build(
            "AAPL",
            sec_financials={"eps": 6.0, "net_income": 100.0, "financial_currency": "USD"},
            candidate={"current_price": 180.0, "market_cap": 3_000.0},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.pe, 30.0)
        pe = next(item for item in facts.provenance if item.field == "pe")
        self.assertEqual(pe.normalization, "PRICE_OVER_FY_EPS")
        self.assertEqual(pe.period_kind, PERIOD_MIXED)

    def test_existing_ps_and_pb_are_mcap_form(self) -> None:
        facts = SecurityFactsService().build(
            "AAPL",
            sec_financials={
                "revenue": 400.0,
                "equity": 50.0,
                "financial_currency": "USD",
            },
            candidate={"market_cap": 800.0},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.price_to_sales, 2.0)
        self.assertEqual(facts.price_to_book, 16.0)
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["price_to_sales"].normalization, "MCAP_OVER_FY_REVENUE")
        self.assertEqual(by_field["price_to_book"].normalization, "MCAP_OVER_FY_EQUITY")

    def test_zero_and_negative_denominators_follow_canonical_rules(self) -> None:
        zero = canonical_multiple_readiness(
            price=10.0,
            market_cap=100.0,
            eps=0.0,
            revenue=0.0,
            equity=0.0,
        )
        self.assertEqual(zero["pe"]["status"], "BLOCKED")
        self.assertEqual(zero["price_to_sales"]["status"], "BLOCKED")
        self.assertEqual(zero["price_to_book"]["status"], "BLOCKED")
        negative = SecurityFactsService().build(
            "AAPL",
            sec_financials={"eps": -2.0, "revenue": 10.0, "equity": -5.0, "financial_currency": "USD"},
            candidate={"current_price": 20.0, "market_cap": 40.0},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(negative.pe, -10.0)
        self.assertEqual(negative.price_to_sales, 4.0)
        self.assertEqual(negative.price_to_book, -8.0)


class SecurityFactsIntegrationTests(unittest.TestCase):
    def test_fy_financials_and_current_market_price_coexist(self) -> None:
        market = market_facts_from_thb_bulletin(_bulletin(), "ASELS")
        kap = _kap_payload("ASELS")
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=kap,
            bist_market_facts=market,
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.price, 403.0)
        self.assertEqual(facts.revenue, 120_000_000)
        self.assertEqual(facts.currency, "TRY")
        self.assertIsNone(facts.market_cap)
        self.assertIsNone(facts.pe)
        self.assertIsNone(facts.price_to_sales)
        self.assertIsNone(facts.price_to_book)
        self.assertIsNone(facts.eps)
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["revenue"].authority, AUTHORITY_KAP)
        self.assertEqual(by_field["revenue"].period_kind, PERIOD_FY)
        self.assertEqual(by_field["price"].authority, AUTHORITY_BORSA_ISTANBUL)
        self.assertEqual(by_field["price"].source_as_of, "2026-08-19")
        self.assertEqual(facts.authority_status, AUTHORITY_MIXED)
        self.assertEqual(facts.as_of, kap["financial_period_end"])
        self.assertNotIn("price", facts.missing_critical_fields)
        self.assertIn("market_cap", facts.missing_critical_fields)

    def test_stale_official_price_is_marked(self) -> None:
        market = market_facts_from_thb_bulletin(
            _bulletin(),
            "BIMAS",
            as_of=date(2026, 9, 30),
        )
        self.assertTrue(market.stale)
        facts = SecurityFactsService().build(
            "BIMAS",
            bist_market_facts=market,
            allow_sec_cache_replay=False,
        )
        self.assertTrue(facts.stale)
        self.assertEqual(facts.price, 416.5)
        self.assertEqual(facts.freshness_status, "STALE")

    def test_unofficial_candidate_mcap_does_not_enter_bist(self) -> None:
        facts = SecurityFactsService().build(
            "TUPRS",
            candidate={"current_price": 1.0, "market_cap": 99.0, "pe_ratio": 5.0},
            bist_market_facts=market_facts_from_thb_bulletin(_bulletin(), "TUPRS"),
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.price, 395.5)
        self.assertIsNone(facts.market_cap)
        self.assertIsNone(facts.pe)

    def test_official_mcap_unlocks_canonical_ps_pb_not_pe_without_eps(self) -> None:
        market = market_facts_from_thb_bulletin(_bulletin(), "ASELS")
        payload = market.to_dict()
        payload["market_cap"] = 240_000_000.0
        payload["market_cap_classification"] = CLASS_DIRECT_OFFICIAL
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=_kap_payload("ASELS"),
            bist_market_facts=payload,
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.market_cap, 240_000_000.0)
        self.assertEqual(facts.price_to_sales, 2.0)
        self.assertIsNone(facts.pe)
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["price_to_sales"].normalization, "MCAP_OVER_FY_REVENUE")


class ShadowValuationAndMomentumTests(unittest.TestCase):
    def test_valuation_and_momentum_remain_blocked_without_mcap_history(self) -> None:
        market = market_facts_from_thb_bulletin(_bulletin(), "ASELS")
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=_kap_payload("ASELS"),
            bist_market_facts=market,
            allow_sec_cache_replay=False,
        )
        before = SecurityFactsService().build(
            "ASELS",
            kap_financials=_kap_payload("ASELS"),
            allow_sec_cache_replay=False,
        )
        view_before = evaluate_security_intelligence(before)
        view_after = evaluate_security_intelligence(facts)
        self.assertEqual(view_before.valuation.status, "INSUFFICIENT_DATA")
        self.assertEqual(view_after.valuation.status, "INSUFFICIENT_DATA")
        self.assertIsNone(view_after.valuation.score)
        self.assertEqual(view_after.momentum.status, "INSUFFICIENT_DATA")
        self.assertIsNone(facts.return_3m)
        self.assertIsNone(facts.return_6m)
        self.assertIsNone(facts.return_1y)
        self.assertIsNone(facts.drawdown)
        audit = audit_bist_si_readiness(facts)
        self.assertEqual(audit.dimensions[DIM_VALUATION], STATUS_BLOCKED)
        self.assertEqual(audit.dimensions[DIM_MOMENTUM], STATUS_BLOCKED)
        self.assertFalse(audit.persisted)
        self.assertNotIn("return_3m", MARKET.read_text(encoding="utf-8"))
        source = MARKET.read_text(encoding="utf-8")
        self.assertNotIn("def compute_return", source)

    def test_data_quality_price_helps_completeness_without_claiming_ready(self) -> None:
        before = SecurityFactsService().build(
            "ASELS",
            kap_financials=_kap_payload("ASELS"),
            allow_sec_cache_replay=False,
        )
        after = SecurityFactsService().build(
            "ASELS",
            kap_financials=_kap_payload("ASELS"),
            bist_market_facts=market_facts_from_thb_bulletin(_bulletin(), "ASELS"),
            allow_sec_cache_replay=False,
        )
        self.assertGreater(after.completeness_pct or 0, before.completeness_pct or 0)
        self.assertIn("market_cap", after.missing_critical_fields)
        self.assertIn("pe", after.missing_critical_fields)
        inventory = inventory_kap_si_fields(
            build_kap_normalized_bundle("ASELS", asels_raw_lines())
        )
        self.assertEqual(inventory["market_cap"], "NOT_AVAILABLE")
        self.assertEqual(inventory["shares_outstanding"], "NOT_AVAILABLE")


class IsolationSafetyTests(unittest.TestCase):
    def test_us_valuation_providers_unchanged(self) -> None:
        aapl = SecurityFactsService().build(
            "AAPL",
            sec_financials={"eps": 6.0, "revenue": 400.0, "equity": 80.0, "financial_currency": "USD"},
            candidate={"current_price": 180.0, "market_cap": 800.0},
            bist_market_facts=market_facts_from_thb_bulletin(_bulletin(), "ASELS"),
            allow_sec_cache_replay=False,
        )
        self.assertEqual(aapl.price, 180.0)
        self.assertEqual(aapl.market_cap, 800.0)
        self.assertEqual(aapl.pe, 30.0)
        self.assertNotEqual(aapl.price, 403.0)
        by_field = {item.field: item for item in aapl.provenance}
        self.assertEqual(by_field["eps"].authority, AUTHORITY_SEC)
        self.assertNotEqual(by_field["price"].authority, AUTHORITY_BORSA_ISTANBUL)
        crm = SecurityFactsService().build("CRM", allow_sec_cache_replay=False)
        self.assertNotEqual(crm.currency, "TRY")
        self.assertIsNone(crm.price)

    def test_participation_and_8e_unchanged(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
            self.assertIn(REASON_SI_MISSING, result.blocking_reasons)
        self.assertNotIn("BIST_SI_ENABLED", SI_FIREWALL.read_text(encoding="utf-8"))
        self.assertNotIn("8e_enabled", ENGINE.read_text(encoding="utf-8"))
        self.assertNotIn("BistValuationEngine", FACTS.read_text(encoding="utf-8"))
        weights = SI_ENGINE.read_text(encoding="utf-8")
        self.assertIn('("pe", inverse(facts.pe, 12, 40), 0.50)', weights)
        self.assertIn('("price_to_sales", inverse(facts.price_to_sales, 1.5, 10), 0.25)', weights)
        self.assertIn('("price_to_book", inverse(facts.price_to_book, 1.5, 10), 0.25)', weights)

    def test_no_persistence_and_no_live_default(self) -> None:
        facts = SecurityFactsService().build(
            "ASELS",
            bist_market_facts=market_facts_from_thb_bulletin(_bulletin(), "ASELS"),
            allow_sec_cache_replay=False,
        )
        view = SecurityIntelligenceService().evaluate(facts)
        self.assertFalse(hasattr(view, "persisted") and getattr(view, "persisted"))
        source = FACTS.read_text(encoding="utf-8")
        self.assertIn("No live provider calls by default", source)
        self.assertNotIn("resolve_latest_thb_bulletin", source)
        self.assertNotIn("api_key", MARKET.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
