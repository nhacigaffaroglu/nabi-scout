from __future__ import annotations

import unittest
from pathlib import Path

from services.kap_financial_bridge import KapIdentityError
from services.kap_financial_normalization import map_account_code
from services.kap_public_bridge import (
    ingest_public_kap_financials,
    participation_inputs_from_public,
    raw_lines_from_public,
)
from services.kap_public_contract import (
    LIMITATION_METADATA,
    LIMITATION_SCALE,
    PUBLIC_DOWNLOAD_AVAILABLE,
    PUBLIC_PAGE_AVAILABLE,
    PUBLIC_STRUCTURED_DATA_AVAILABLE,
    SOURCE_PUBLIC_KAP,
    SOURCE_UNAVAILABLE,
    KapPublicSourceError,
)
from services.kap_public_parser import parse_public_kap_html
from services.kap_public_source import KapPublicFinancialSource, resolve_public_kap_access
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_master_contract import INSTRUMENT_EQUITY
from tests.fixtures.kap_public_pilot import (
    FIXTURE_DISCLAIMER,
    PILOT_PUBLIC_REPORTS,
    asels_public_html,
    compact_public_html,
    fy_public_html,
    missing_unit_html,
)


PARSER = Path("services/kap_public_parser.py")
SOURCE = Path("services/kap_public_source.py")
BRIDGE = Path("services/kap_public_bridge.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
NORM = Path("services/kap_financial_normalization.py")


def _doc(html: str, *, symbol: str = "ASELS", disclosure_id: str = "1643141"):
    return parse_public_kap_html(html, symbol=symbol, disclosure_id=disclosure_id)


class PublicAccessTests(unittest.TestCase):
    def test_public_path_is_unauthenticated(self) -> None:
        status = resolve_public_kap_access()
        self.assertEqual(status.page_access, PUBLIC_PAGE_AVAILABLE)
        self.assertEqual(status.download_access, PUBLIC_DOWNLOAD_AVAILABLE)
        self.assertEqual(status.structured_taxonomy, PUBLIC_STRUCTURED_DATA_AVAILABLE)
        self.assertFalse(status.authentication_required)
        self.assertFalse(status.paid_service_used)

    def test_live_fetch_is_opt_in(self) -> None:
        source = KapPublicFinancialSource(allow_live=False, cache_dir=Path("/tmp/nabi-kap-empty"))
        with self.assertRaises(KapPublicSourceError) as raised:
            source.fetch_report("9999999", symbol="ASELS")
        self.assertEqual(str(raised.exception), SOURCE_UNAVAILABLE)


class ParserAndMappingTests(unittest.TestCase):
    def test_taxonomy_not_labels(self) -> None:
        doc = _doc(asels_public_html())
        concepts = {row.concept for row in doc.rows}
        self.assertIn("ifrs-full_Revenue", concepts)
        self.assertIn("ifrs-full_CashAndCashEquivalents", concepts)
        self.assertIn("ifrs-full_Assets", concepts)
        self.assertNotIn("Hasılat", concepts)
        self.assertEqual(doc.presentation_currency, "TRY")
        self.assertEqual(doc.presentation_unit_label, "1.000 TL")
        self.assertEqual(doc.consolidation, "CONSOLIDATED")
        self.assertEqual(doc.source, SOURCE_PUBLIC_KAP)

    def test_period_semantics(self) -> None:
        interim = _doc(asels_public_html())
        revenue = [row for row in interim.rows if row.concept == "ifrs-full_Revenue"]
        kinds = {row.period_kind for row in revenue}
        self.assertIn("YTD", kinds)
        self.assertIn("Q", kinds)
        self.assertNotIn("FY", kinds)
        cash = next(row for row in interim.rows if row.concept == "ifrs-full_CashAndCashEquivalents")
        self.assertEqual(cash.period_kind, "YTD")
        self.assertEqual(cash.fact_nature, "POINT_IN_TIME")
        fy = _doc(fy_public_html(), disclosure_id="1554106")
        fy_rev = next(row for row in fy.rows if row.concept == "ifrs-full_Revenue")
        fy_assets = next(row for row in fy.rows if row.concept == "ifrs-full_Assets")
        self.assertEqual(fy_rev.period_kind, "FY")
        self.assertEqual(fy_assets.period_kind, "FY")

    def test_unknown_taxonomy_stays_unmapped(self) -> None:
        self.assertIsNone(map_account_code("ifrs-full_Inventories"))
        self.assertEqual(map_account_code("ifrs-full_Revenue"), ("revenue", "FLOW"))
        self.assertEqual(map_account_code("IFRS-FULL_ASSETS"), ("total_assets", "POINT_IN_TIME"))
        bundle = ingest_public_kap_financials(_doc(asels_public_html()))
        self.assertIn("IFRS-FULL_INVENTORIES", bundle.unmapped_account_codes)

    def test_missing_metadata_and_scale(self) -> None:
        with self.assertRaises(ValueError) as raised:
            _doc(missing_unit_html())
        self.assertEqual(str(raised.exception), LIMITATION_METADATA)
        bad = _doc(compact_public_html(unit="2.000 TL"))
        with self.assertRaises(KapPublicSourceError) as scale:
            raw_lines_from_public(bad)
        self.assertEqual(str(scale.exception), LIMITATION_SCALE)

    def test_real_mapping_and_current_period_only(self) -> None:
        doc = _doc(asels_public_html())
        cash = next(row for row in doc.rows if row.concept == "ifrs-full_CashAndCashEquivalents")
        self.assertEqual(cash.values, (39_468_926.0,))
        revenue = next(
            row
            for row in doc.rows
            if row.concept == "ifrs-full_Revenue" and row.period_kind == "YTD"
        )
        self.assertEqual(revenue.values, (88_494_252.0,))
        lines = raw_lines_from_public(doc)
        self.assertTrue(all(line.source == SOURCE_PUBLIC_KAP for line in lines))
        self.assertTrue(all(line.source_document_id == "1643141" for line in lines))


class BridgeAndSafetyTests(unittest.TestCase):
    def test_pipeline_without_verdict(self) -> None:
        fy = ingest_public_kap_financials(_doc(fy_public_html(), disclosure_id="1554106"))
        self.assertIsNotNone(fy.fact("revenue"))
        self.assertIsNotNone(fy.fact("total_assets"))
        self.assertIsNotNone(fy.fact("cash"))
        self.assertIsNone(fy.fact("total_debt"))
        inputs, missing = participation_inputs_from_public(
            _doc(fy_public_html(), disclosure_id="1554106")
        )
        self.assertEqual(inputs.total_revenue, 120_000_000_000.0)
        self.assertTrue(any("non_permissible_revenue" in item for item in missing))
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_financial_rules", source)
        self.assertNotIn("evaluate_business_activity", source)
        self.assertNotIn("Uygun", source)
        self.assertNotIn("ParticipationAssessmentRepository", source)

    def test_us_isolation(self) -> None:
        with self.assertRaises(KapIdentityError):
            ingest_public_kap_financials(_doc(asels_public_html(), symbol="AAPL"))
        with self.assertRaises(KapIdentityError):
            ingest_public_kap_financials(_doc(asels_public_html(), symbol="CRM"))

    def test_8e_unchanged(self) -> None:
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    si_state=STATE_ATTRACTIVE,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
        self.assertIn("BIST_PORTFOLIO_SYMBOLS", ENGINE.read_text(encoding="utf-8"))

    def test_no_label_guessing_or_paid_api(self) -> None:
        parser = PARSER.read_text(encoding="utf-8")
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("ifrs-full", parser)
        self.assertNotIn("Hasılat", parser)
        self.assertNotIn("api_key", source)
        self.assertNotIn("NABI_KAP_API_KEY", source)
        self.assertIn("PUBLIC_KAP", NORM.read_text(encoding="utf-8") + parser)
        self.assertIn("TEST-ONLY", FIXTURE_DISCLAIMER)
        self.assertEqual(set(PILOT_PUBLIC_REPORTS), {"ASELS", "BIMAS", "TUPRS"})


if __name__ == "__main__":
    unittest.main()
