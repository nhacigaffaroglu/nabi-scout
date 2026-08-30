from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest

from services.bist_eod_bulletin import parse_thb_csv, thb_download_url
from services.bist_official_market_facts import (
    CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS,
    CLASS_NOT_AVAILABLE,
    attach_official_nominal_market_cap,
    market_facts_from_thb_bulletin,
)
from services.bist_si_readiness import (
    DIM_MOMENTUM,
    DIM_VALUATION,
    STATUS_BLOCKED,
    STATUS_PARTIAL,
    audit_bist_si_readiness,
)
from services.borsa_quotation_basis import (
    CANONICAL_MARKET_CAP_DECISION,
    MARKET_CAP_DECISION_LEGAL_AND_PRICE,
    MARKET_CAP_DECISION_NOMINAL_AND_PRICE,
    QUOTE_NOMINAL_BASIS_TRY,
    SOURCE_PAY_PIYASASI_PROCEDURE,
    STATUS_ABSURD_LEGAL,
    canonical_market_cap_decision,
    derive_market_cap_from_official_nominal_capital_and_price,
    official_quotation_contract,
    quote_equivalent_units,
    reject_price_times_legal_shares,
)
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.kap_capital_structure import (
    ACCESS_NOT_PROGRAMMATICALLY_AVAILABLE,
    ACCESS_PUBLIC_RENDERED_BUT_PARSEABLE,
    EXCHANGE_NOT_TRADED,
    EXCHANGE_TRADED,
    company_general_url,
    legal_share_count,
    parse_bist_company_oids,
    parse_kap_capital_structure_html,
    parse_tr_number,
)
from services.kap_eps_taxonomy_audit import (
    CLASS_DERIVABLE_UNDER_EXISTING_METHOD,
    CLASS_DIRECT_OFFICIAL_EPS,
    CLASS_NOT_AVAILABLE as EPS_NOT_AVAILABLE,
    audit_kap_eps_taxonomy,
    existing_method_allows_invented_eps,
)
from services.kap_financial_bridge import build_kap_normalized_bundle, kap_security_facts_payload
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import AUTHORITY_SEC
from services.security_intelligence_engine import evaluate_security_intelligence
from services.security_master_contract import INSTRUMENT_EQUITY
from tests.fixtures.kap_financial_pilot import asels_raw_lines


FIXTURES = Path("tests/fixtures")
ASELS_HTML = FIXTURES / "kap_capital_structure_sample.html"
BIMAS_HTML = FIXTURES / "kap_capital_bimas_mismatch.html"
TUPRS_HTML = FIXTURES / "kap_capital_tuprs_nominal.html"
SHELL_HTML = FIXTURES / "kap_company_ticker_shell.html"
OID_HTML = FIXTURES / "kap_bist_sirketler_oids.html"
EPS_HTML = FIXTURES / "kap_eps_taxonomy_sample.html"
EPS_HEADERS = FIXTURES / "kap_eps_headers_only.html"
THB_FIXTURE = FIXTURES / "bist_thb_eod_sample.csv"
MARKET = Path("services/bist_official_market_facts.py")
FACTS = Path("services/security_facts_service.py")
SI_FIREWALL = Path("services/security_intelligence_contract.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
QUOTATION = Path("services/borsa_quotation_basis.py")


def _bulletin():
    return parse_thb_csv(
        THB_FIXTURE.read_text(encoding="utf-8"),
        source_file="thb202608191.csv",
        source_url=thb_download_url(date(2026, 8, 19)),
    )


def _structure(symbol: str, path: Path):
    return parse_kap_capital_structure_html(
        path.read_text(encoding="utf-8"),
        symbol=symbol,
        source_url=company_general_url("fixture-oid"),
        observed_at="2026-08-30T00:00:00+00:00",
    )


class ParseAndAccessTests(unittest.TestCase):
    def test_asels_two_classes_one_try_nominal(self) -> None:
        parsed = _structure("ASELS", ASELS_HTML)
        self.assertEqual(parsed.access_classification, ACCESS_PUBLIC_RENDERED_BUT_PARSEABLE)
        self.assertEqual(parsed.issued_capital, Decimal("4560000000"))
        self.assertEqual(len(parsed.classes), 2)
        self.assertEqual(parsed.classes[0].share_class, "A")
        self.assertEqual(parsed.classes[0].nominal_value_per_share, Decimal("1"))
        self.assertEqual(parsed.classes[0].exchange_traded_flag, EXCHANGE_NOT_TRADED)
        self.assertEqual(parsed.classes[1].share_class, "B")
        self.assertEqual(parsed.classes[1].exchange_traded_flag, EXCHANGE_TRADED)
        self.assertEqual(parsed.class_total_nominal_sum, Decimal("4560000000"))
        self.assertIsNone(parsed.classes[0].legal_share_count)
        self.assertEqual(parsed.total_legal_share_count, Decimal("4560000000"))

    def test_bimas_class_total_mismatch_does_not_hardcode_pilots(self) -> None:
        parsed = _structure("BIMAS", BIMAS_HTML)
        self.assertEqual(parsed.issued_capital, Decimal("1200000000"))
        self.assertEqual(parsed.classes[0].class_total_nominal_value, Decimal("600000000"))
        self.assertIn("class_totals_do_not_match_issued_capital", parsed.notes)
        self.assertIsNone(parsed.total_legal_share_count)
        source = Path("services/kap_capital_structure.py").read_text(encoding="utf-8")
        self.assertNotIn("4560000000", source)
        self.assertNotIn("1926795598", source)

    def test_tuprs_fractional_nominal_and_nontraded_class(self) -> None:
        parsed = _structure("TUPRS", TUPRS_HTML)
        self.assertEqual(parsed.classes[0].nominal_value_per_share, Decimal("0.01"))
        self.assertEqual(parsed.classes[0].exchange_traded_flag, EXCHANGE_TRADED)
        self.assertEqual(parsed.classes[1].share_class, "C")
        self.assertEqual(parsed.classes[1].exchange_traded_flag, EXCHANGE_NOT_TRADED)
        self.assertEqual(parsed.classes[0].legal_share_count, Decimal("192679559799"))
        self.assertEqual(parsed.classes[1].legal_share_count, Decimal("1"))
        self.assertEqual(parsed.total_legal_share_count, Decimal("192679559800"))
        self.assertEqual(parsed.issued_capital, Decimal("1926795598"))

    def test_ticker_shell_is_not_programmatically_available(self) -> None:
        parsed = _structure("ASELS", SHELL_HTML)
        self.assertEqual(parsed.access_classification, ACCESS_NOT_PROGRAMMATICALLY_AVAILABLE)
        self.assertEqual(parsed.classes, ())

    def test_bist_sirketler_oids_and_try_normalization(self) -> None:
        oids = parse_bist_company_oids(OID_HTML.read_text(encoding="utf-8"))
        self.assertEqual(oids["ASELS"], "4028e4a1413b7ef401413bc2251e0047")
        self.assertEqual(parse_tr_number("4.560.000.000"), Decimal("4560000000"))
        self.assertEqual(parse_tr_number("0,01"), Decimal("0.01"))
        self.assertEqual(parse_tr_number("74,20"), Decimal("74.20"))
        self.assertEqual(parse_tr_number("2421818181.816"), Decimal("2421818181.816"))


class LegalVsQuoteUnitTests(unittest.TestCase):
    def test_legal_share_count_requires_integral_result(self) -> None:
        self.assertEqual(
            legal_share_count(Decimal("1926795597.99"), Decimal("0.01")),
            Decimal("192679559799"),
        )
        self.assertIsNone(legal_share_count(Decimal("2421818181.816"), Decimal("1")))

    def test_quote_units_are_issued_capital_over_one_try(self) -> None:
        self.assertEqual(QUOTE_NOMINAL_BASIS_TRY, Decimal("1"))
        self.assertEqual(quote_equivalent_units(Decimal("1926795598")), Decimal("1926795598"))
        contract = official_quotation_contract()
        self.assertEqual(contract["official_source"], SOURCE_PAY_PIYASASI_PROCEDURE)
        self.assertIn("1,00 TL (nominal) = 1 adet = 1 lot", contract["lot_definition"])
        self.assertEqual(canonical_market_cap_decision(), MARKET_CAP_DECISION_NOMINAL_AND_PRICE)
        self.assertNotEqual(CANONICAL_MARKET_CAP_DECISION, MARKET_CAP_DECISION_LEGAL_AND_PRICE)

    def test_no_price_times_raw_legal_shares(self) -> None:
        blocked = reject_price_times_legal_shares(
            official_price=396.0,
            legal_share_count=Decimal("192679559800"),
            quote_units=Decimal("1926795598"),
        )
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["status"], STATUS_ABSURD_LEGAL)
        self.assertEqual(blocked["absurd_multiple"], 100.0)
        self.assertGreater(
            blocked["legal_implied_market_cap"],
            50 * blocked["quote_implied_market_cap"],
        )
        derived = derive_market_cap_from_official_nominal_capital_and_price(
            official_price=396.0,
            issued_capital_try=Decimal("1926795598"),
            price_source="thb",
            capital_source="kap",
        )
        self.assertEqual(derived["decision"], MARKET_CAP_DECISION_NOMINAL_AND_PRICE)
        self.assertEqual(derived["quote_equivalent_units"], 1926795598.0)
        self.assertAlmostEqual(derived["market_cap"], 396.0 * 1926795598.0)
        self.assertNotAlmostEqual(derived["market_cap"], 396.0 * 192679559800.0)


class OfficialMarketCapWireTests(unittest.TestCase):
    def test_thb_alone_still_has_no_market_cap(self) -> None:
        facts = market_facts_from_thb_bulletin(_bulletin(), "TUPRS")
        self.assertIsNone(facts.market_cap)
        self.assertEqual(facts.market_cap_classification, CLASS_NOT_AVAILABLE)

    def test_asels_one_try_and_tuprs_one_kurus_use_quote_units(self) -> None:
        asels = attach_official_nominal_market_cap(
            market_facts_from_thb_bulletin(_bulletin(), "ASELS"),
            _structure("ASELS", ASELS_HTML),
        )
        tuprs = attach_official_nominal_market_cap(
            market_facts_from_thb_bulletin(_bulletin(), "TUPRS"),
            _structure("TUPRS", TUPRS_HTML),
        )
        self.assertEqual(asels.market_cap_classification, CLASS_DERIVED_FROM_OFFICIAL_COMPONENTS)
        self.assertEqual(asels.shares_outstanding, 4_560_000_000.0)
        self.assertAlmostEqual(asels.market_cap, 403.0 * 4_560_000_000.0)
        self.assertEqual(tuprs.shares_outstanding, 1_926_795_598.0)
        self.assertAlmostEqual(tuprs.market_cap, 395.5 * 1_926_795_598.0)
        self.assertLess(tuprs.market_cap, 395.5 * 192_679_559_800.0 / 10)
        bimas = attach_official_nominal_market_cap(
            market_facts_from_thb_bulletin(_bulletin(), "BIMAS"),
            _structure("BIMAS", BIMAS_HTML),
        )
        self.assertAlmostEqual(bimas.market_cap, 416.5 * 1_200_000_000.0)

    def test_canonical_ps_pb_not_pe_without_eps(self) -> None:
        market = attach_official_nominal_market_cap(
            market_facts_from_thb_bulletin(_bulletin(), "ASELS"),
            _structure("ASELS", ASELS_HTML),
        )
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=kap_security_facts_payload(
                build_kap_normalized_bundle("ASELS", asels_raw_lines())
            ),
            bist_market_facts=market,
            allow_sec_cache_replay=False,
        )
        self.assertIsNotNone(facts.market_cap)
        self.assertIsNotNone(facts.price_to_sales)
        self.assertIsNotNone(facts.price_to_book)
        self.assertIsNone(facts.eps)
        self.assertIsNone(facts.pe)
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["price_to_sales"].normalization, "MCAP_OVER_FY_REVENUE")
        self.assertEqual(by_field["price_to_book"].normalization, "MCAP_OVER_FY_EQUITY")
        audit = audit_bist_si_readiness(facts)
        self.assertEqual(audit.dimensions[DIM_VALUATION], STATUS_PARTIAL)
        self.assertEqual(audit.dimensions[DIM_MOMENTUM], STATUS_BLOCKED)
        self.assertFalse(audit.persisted)
        view = evaluate_security_intelligence(facts)
        self.assertIsNone(facts.return_3m)
        self.assertEqual(view.momentum.status, "INSUFFICIENT_DATA")


class EpsAuditTests(unittest.TestCase):
    def test_direct_official_eps_is_not_ingested(self) -> None:
        valued = audit_kap_eps_taxonomy(
            EPS_HTML.read_text(encoding="utf-8"),
            symbol="ASELS",
        )
        empty = audit_kap_eps_taxonomy(
            EPS_HEADERS.read_text(encoding="utf-8"),
            symbol="TUPRS",
        )
        self.assertTrue(valued.basic_exposed)
        self.assertTrue(valued.diluted_exposed)
        self.assertEqual(valued.classification, CLASS_DIRECT_OFFICIAL_EPS)
        self.assertEqual(valued.existing_parser_valued_rows, 0)
        self.assertEqual(empty.classification, EPS_NOT_AVAILABLE)
        self.assertFalse(existing_method_allows_invented_eps())
        self.assertNotEqual(valued.classification, CLASS_DERIVABLE_UNDER_EXISTING_METHOD)
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=kap_security_facts_payload(
                build_kap_normalized_bundle("ASELS", asels_raw_lines())
            ),
            allow_sec_cache_replay=False,
        )
        self.assertIsNone(facts.eps)
        self.assertIsNone(facts.pe)


class IsolationSafetyTests(unittest.TestCase):
    def test_us_and_participation_and_8e_unchanged(self) -> None:
        market = attach_official_nominal_market_cap(
            market_facts_from_thb_bulletin(_bulletin(), "ASELS"),
            _structure("ASELS", ASELS_HTML),
        )
        aapl = SecurityFactsService().build(
            "AAPL",
            sec_financials={"eps": 6.0, "revenue": 400.0, "equity": 80.0, "financial_currency": "USD"},
            candidate={"current_price": 180.0, "market_cap": 800.0},
            bist_market_facts=market,
            allow_sec_cache_replay=False,
        )
        self.assertEqual(aapl.price, 180.0)
        self.assertEqual(aapl.market_cap, 800.0)
        self.assertEqual(aapl.pe, 30.0)
        by_field = {item.field: item for item in aapl.provenance}
        self.assertEqual(by_field["eps"].authority, AUTHORITY_SEC)
        crm = SecurityFactsService().build("CRM", allow_sec_cache_replay=False)
        self.assertNotEqual(crm.currency, "TRY")
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
            self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
        self.assertNotIn("BIST_SI_ENABLED", SI_FIREWALL.read_text(encoding="utf-8"))
        self.assertNotIn("8e_enabled", ENGINE.read_text(encoding="utf-8"))
        self.assertNotIn("resolve_latest_thb_bulletin", FACTS.read_text(encoding="utf-8"))
        self.assertNotIn("api_key", MARKET.read_text(encoding="utf-8"))
        self.assertNotIn("api_key", QUOTATION.read_text(encoding="utf-8"))
        self.assertNotIn("def persist", MARKET.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
