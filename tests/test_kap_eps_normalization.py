from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest

from services.bist_eod_bulletin import parse_thb_csv, thb_download_url
from services.bist_official_market_facts import (
    attach_official_nominal_market_cap,
    market_facts_from_thb_bulletin,
)
from services.bist_si_readiness import DIM_MOMENTUM, DIM_VALUATION, STATUS_BLOCKED, audit_bist_si_readiness
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.kap_capital_structure import parse_kap_capital_structure_html
from services.kap_eps_normalization import (
    BASIS_ONE_TRY,
    BASIS_UNRESOLVED,
    asels_anomaly_classification,
    classify_eps_basis,
    existing_method_allows_invented_eps,
)
from services.kap_eps_taxonomy_audit import CLASS_DERIVABLE_UNDER_EXISTING_METHOD
from services.kap_financial_bridge import build_kap_normalized_bundle, kap_security_facts_payload
from services.kap_public_bridge import ingest_public_kap_financials, structured_payloads_from_public
from services.kap_public_parser import parse_public_kap_html
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
from tests.fixtures.kap_eps_fy_rows import (
    asels_unresolved_eps_html,
    bimas_tam_tl_eps_html,
    diluted_preferred_html,
    hundred_shares_of_one_kr_html,
    official_nested_empty_parent_eps_html,
    tuprs_headers_only_html,
    tuprs_one_kr_eps_html,
    ytd_eps_html,
)
from tests.fixtures.kap_financial_pilot import asels_raw_lines


THB_FIXTURE = Path("tests/fixtures/bist_thb_eod_sample.csv")
CAPITAL_ASELS = Path("tests/fixtures/kap_capital_structure_sample.html")
SI_FIREWALL = Path("services/security_intelligence_contract.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
FACTS = Path("services/security_facts_service.py")
BRIDGE = Path("services/kap_public_bridge.py")
NORM = Path("services/kap_eps_normalization.py")


def _doc(html: str, *, symbol: str, disclosure_id: str):
    return parse_public_kap_html(html, symbol=symbol, disclosure_id=disclosure_id, cached=True)


def _bulletin():
    return parse_thb_csv(
        THB_FIXTURE.read_text(encoding="utf-8"),
        source_file="thb202608191.csv",
        source_url=thb_download_url(date(2026, 8, 19)),
    )


class TypedDimensionExtractionTests(unittest.TestCase):
    def test_concept_is_taxonomy_id_not_label(self) -> None:
        doc = _doc(bimas_tam_tl_eps_html(), symbol="BIMAS", disclosure_id="1570150")
        eps_rows = [row for row in doc.rows if "Earnings" in row.concept]
        self.assertTrue(eps_rows)
        self.assertTrue(eps_rows[0].concept.startswith("ifrs-full_"))
        self.assertNotEqual(eps_rows[0].concept, eps_rows[0].raw_label)

    def test_nested_title_table_does_not_drop_typed_values(self) -> None:
        bundle = ingest_public_kap_financials(
            _doc(official_nested_empty_parent_eps_html(), symbol="BIMAS", disclosure_id="1570150")
        )
        eps = next(item for item in bundle.mapped if item.field == "eps")
        self.assertEqual(eps.normalized_value, 31.12)
        self.assertEqual(eps.raw_unit_scale, 1)

    def test_typed_dimension_values_are_not_statement_thousands(self) -> None:
        bundle = ingest_public_kap_financials(
            _doc(bimas_tam_tl_eps_html(), symbol="BIMAS", disclosure_id="1570150")
        )
        eps = next(item for item in bundle.mapped if item.field == "eps")
        self.assertEqual(eps.normalized_value, 31.12)
        self.assertEqual(eps.raw_unit_scale, 1)
        self.assertNotEqual(eps.normalized_value, 31.12 * 1000)
        self.assertEqual(eps.normalization_rule, BASIS_ONE_TRY)


class BasisAndAnomalyTests(unittest.TestCase):
    def test_one_try_and_one_kr_times_100(self) -> None:
        one_try = classify_eps_basis("Sürdürülen Faaliyetler Pay Başına Kazanç (Tam TL)")
        self.assertEqual(one_try["classification"], BASIS_ONE_TRY)
        kr100 = classify_eps_basis("Nominal değeri 1 Kr olan 100 adet pay başına kazanç")
        self.assertEqual(kr100["classification"], BASIS_ONE_TRY)
        self.assertEqual(kr100["canonical_factor"], Decimal("1"))
        kr = classify_eps_basis("Nominal değeri 1 kr. olan pay başına kazanç (zarar) (kr.)")
        self.assertEqual(kr["classification"], BASIS_ONE_TRY)
        self.assertEqual(kr["canonical_factor"], Decimal("1"))

    def test_asels_100x_is_not_auto_divided(self) -> None:
        self.assertEqual(asels_anomaly_classification(656.79), BASIS_UNRESOLVED)
        basis = classify_eps_basis("Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)")
        self.assertEqual(basis["classification"], BASIS_UNRESOLVED)
        bundle = ingest_public_kap_financials(
            _doc(asels_unresolved_eps_html(), symbol="ASELS", disclosure_id="1561039")
        )
        self.assertFalse(any(item.field == "eps" for item in bundle.mapped))
        source = NORM.read_text(encoding="utf-8")
        self.assertNotIn("reported / 100", source)
        self.assertNotIn('/ Decimal("100")', source)
        self.assertNotIn("/ Decimal('100')", source)

    def test_bimas_tam_tl_and_tuprs_one_kr(self) -> None:
        bimas = ingest_public_kap_financials(
            _doc(bimas_tam_tl_eps_html(), symbol="BIMAS", disclosure_id="1570150")
        )
        tuprs = ingest_public_kap_financials(
            _doc(tuprs_one_kr_eps_html(), symbol="TUPRS", disclosure_id="1554106")
        )
        missing = ingest_public_kap_financials(
            _doc(tuprs_headers_only_html(), symbol="TUPRS", disclosure_id="1554106")
        )
        self.assertEqual(next(item.normalized_value for item in bimas.mapped if item.field == "eps"), 31.12)
        self.assertEqual(next(item.normalized_value for item in tuprs.mapped if item.field == "eps"), 15.32)
        self.assertFalse(any(item.field == "eps" for item in missing.mapped))

    def test_hundred_share_basis_stays_same_number(self) -> None:
        bundle = ingest_public_kap_financials(
            _doc(hundred_shares_of_one_kr_html(), symbol="ASELS", disclosure_id="fixture")
        )
        self.assertEqual(next(item.normalized_value for item in bundle.mapped if item.field == "eps"), 6.56)


class SelectionAndPeriodTests(unittest.TestCase):
    def test_ifrs_diluted_preferred_over_basic(self) -> None:
        bundle = ingest_public_kap_financials(
            _doc(diluted_preferred_html(), symbol="BIMAS", disclosure_id="1570150")
        )
        eps = next(item for item in bundle.mapped if item.field == "eps")
        self.assertEqual(eps.normalized_value, 9.5)
        self.assertIn("DILUTED", eps.account_code or "")

    def test_ytd_eps_does_not_enter_fy_payload(self) -> None:
        payload = kap_security_facts_payload(
            ingest_public_kap_financials(_doc(ytd_eps_html(), symbol="BIMAS", disclosure_id="1651656"))
        )
        self.assertIsNone(payload.get("eps"))

    def test_no_ni_over_shares_invention(self) -> None:
        self.assertFalse(existing_method_allows_invented_eps())
        self.assertNotEqual(BASIS_ONE_TRY, CLASS_DERIVABLE_UNDER_EXISTING_METHOD)
        self.assertNotIn("net_income /", NORM.read_text(encoding="utf-8"))
        payloads = structured_payloads_from_public(
            _doc(asels_unresolved_eps_html(), symbol="ASELS", disclosure_id="1561039")
        )
        self.assertFalse(any(item.get("account_code", "").upper().find("EARNINGS") >= 0 and item.get("raw_value") == 6.5679 for item in payloads))


class SecurityFactsAndPeTests(unittest.TestCase):
    def test_canonical_pe_is_price_over_fy_eps(self) -> None:
        kap = kap_security_facts_payload(
            ingest_public_kap_financials(
                _doc(bimas_tam_tl_eps_html(), symbol="BIMAS", disclosure_id="1570150")
            )
        )
        facts = SecurityFactsService().build(
            "BIMAS",
            kap_financials=kap,
            bist_market_facts=market_facts_from_thb_bulletin(_bulletin(), "BIMAS"),
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.eps, 31.12)
        self.assertEqual(facts.price, 416.5)
        self.assertEqual(facts.pe, 416.5 / 31.12)
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["pe"].normalization, "PRICE_OVER_FY_EPS")
        self.assertEqual(by_field["eps"].normalization, BASIS_ONE_TRY)
        self.assertEqual(by_field["eps"].authority, "KAP")

    def test_asels_eps_blocked_so_pe_blocked(self) -> None:
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=kap_security_facts_payload(
                ingest_public_kap_financials(
                    _doc(asels_unresolved_eps_html(), symbol="ASELS", disclosure_id="1561039")
                )
            ),
            bist_market_facts=market_facts_from_thb_bulletin(_bulletin(), "ASELS"),
            allow_sec_cache_replay=False,
        )
        self.assertIsNone(facts.eps)
        self.assertIsNone(facts.pe)

    def test_full_valuation_when_mcap_and_eps_valid(self) -> None:
        market = attach_official_nominal_market_cap(
            market_facts_from_thb_bulletin(_bulletin(), "BIMAS"),
            parse_kap_capital_structure_html(
                Path("tests/fixtures/kap_capital_bimas_mismatch.html").read_text(encoding="utf-8"),
                symbol="BIMAS",
                source_url="https://kap.org.tr/tr/sirket-bilgileri/genel/x",
            ),
        )
        facts = SecurityFactsService().build(
            "BIMAS",
            kap_financials=kap_security_facts_payload(
                ingest_public_kap_financials(
                    _doc(bimas_tam_tl_eps_html(), symbol="BIMAS", disclosure_id="1570150")
                )
            ),
            bist_market_facts=market,
            allow_sec_cache_replay=False,
        )
        self.assertIsNotNone(facts.pe)
        self.assertIsNotNone(facts.price_to_sales)
        self.assertIsNotNone(facts.price_to_book)
        audit = audit_bist_si_readiness(facts)
        self.assertEqual(audit.dimensions[DIM_VALUATION], "READY")
        self.assertEqual(audit.dimensions[DIM_MOMENTUM], STATUS_BLOCKED)
        self.assertFalse(audit.persisted)
        view = evaluate_security_intelligence(facts)
        self.assertEqual(view.momentum.status, "INSUFFICIENT_DATA")


class IsolationSafetyTests(unittest.TestCase):
    def test_us_eps_semantics_and_8e_unchanged(self) -> None:
        aapl = SecurityFactsService().build(
            "AAPL",
            sec_financials={"eps": 6.0, "revenue": 400.0, "equity": 80.0, "financial_currency": "USD"},
            candidate={"current_price": 180.0, "market_cap": 800.0},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(aapl.eps, 6.0)
        self.assertEqual(aapl.pe, 30.0)
        by_field = {item.field: item for item in aapl.provenance}
        self.assertEqual(by_field["eps"].authority, AUTHORITY_SEC)
        crm = SecurityFactsService().build("CRM", allow_sec_cache_replay=False)
        self.assertNotEqual(crm.currency, "TRY")
        raw_asels = SecurityFactsService().build(
            "ASELS",
            kap_financials=kap_security_facts_payload(
                build_kap_normalized_bundle("ASELS", asels_raw_lines())
            ),
            allow_sec_cache_replay=False,
        )
        self.assertIsNone(raw_asels.eps)
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
        self.assertNotIn("api_key", BRIDGE.read_text(encoding="utf-8"))
        weights = Path("services/security_intelligence_engine.py").read_text(encoding="utf-8")
        self.assertIn('("pe", inverse(facts.pe, 12, 40), 0.50)', weights)


if __name__ == "__main__":
    unittest.main()
