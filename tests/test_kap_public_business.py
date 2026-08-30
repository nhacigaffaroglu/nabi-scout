from __future__ import annotations

import unittest
from pathlib import Path

from services.bist_business_bridge import BistBusinessIdentityError
from services.bist_business_contract import CATEGORY_UNKNOWN, READINESS_PARTIAL
from services.bist_business_normalization import (
    SHARE_CURRENCY_MISMATCH,
    SHARE_PERIOD_MISMATCH,
)
from services.kap_public_business_bridge import (
    build_public_bist_business_bundle,
    cross_check_with_1e,
    inventory_participation_financial_gaps,
    public_participation_readiness,
    raw_segments_from_public,
    shadow_business_screen,
)
from services.kap_public_business_contract import (
    BREAKDOWN_GEOGRAPHICAL,
    BREAKDOWN_OPERATING_SEGMENT,
    BREAKDOWN_SINGLE_SEGMENT,
    COVERAGE_CURRENCY_MISMATCH,
    COVERAGE_OK,
    COVERAGE_PERIOD_INCOMPATIBLE,
    GAP_AVAILABLE_FROM_PUBLIC_KAP,
    GAP_METHODOLOGY_UNRESOLVED,
    GAP_REQUIRES_OTHER_PUBLIC_SOURCE,
    PILOT_PUBLIC_BUSINESS_SOURCES,
    SHADOW_RESULT_KIND,
    STRUCTURED_SEGMENT_NO,
    STRUCTURED_SEGMENT_YES,
)
from services.kap_public_business_parser import (
    observed_non_segment_template,
    observed_segment_taxonomy,
)
from services.kap_public_business_source import KapPublicBusinessSource
from services.kap_public_contract import SOURCE_UNAVAILABLE, KapPublicSourceError
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_master_contract import INSTRUMENT_EQUITY, SOURCE_BIST
from services.security_master_service import SecurityMasterService
from tests.fixtures.kap_public_business_pilot import (
    FIXTURE_DISCLAIMER,
    PILOT_PUBLIC_BUSINESS_REPORTS,
    asels_official_notes,
    bimas_official_notes,
    html_with_unverified_segment_taxonomy,
    html_without_segment_taxonomy,
    remainder_notes,
    tuprs_official_notes,
    unknown_named_notes,
)


SOURCE = Path("services/kap_public_business_source.py")
PARSER = Path("services/kap_public_business_parser.py")
BRIDGE = Path("services/kap_public_business_bridge.py")
OLD_BRIDGE = Path("services/bist_business_bridge.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")

ASELS_1E_REVENUE = 88_494_252_000.0
BIMAS_1E_REVENUE = 449_695_235_000.0
TUPRS_1E_REVENUE = 662_788_010_000.0


def _doc(notes: str, *, symbol: str, disclosure_id: str, html: str = "", **kwargs):
    source = KapPublicBusinessSource(allow_live=False, cache_dir=Path("/tmp/nabi-kap-biz"))
    return source.extract_from_official_notes(
        notes,
        symbol=symbol,
        disclosure_id=disclosure_id,
        html=html,
        period=kwargs.get("period", "YTD"),
        period_end=kwargs.get("period_end", "2026-06-30"),
        period_start=kwargs.get("period_start", "2026-01-01"),
    )


class PublicSourceTests(unittest.TestCase):
    def test_live_notes_are_opt_in(self) -> None:
        source = KapPublicBusinessSource(allow_live=False, cache_dir=Path("/tmp/nabi-kap-biz-empty"))
        with self.assertRaises(KapPublicSourceError) as raised:
            source.fetch_official_notes("9999999", symbol="ASELS")
        self.assertEqual(str(raised.exception), SOURCE_UNAVAILABLE)

    def test_official_document_metadata(self) -> None:
        doc = _doc(tuprs_official_notes(), symbol="TUPRS", disclosure_id="1643116")
        self.assertEqual(doc.symbol, "TUPRS")
        self.assertEqual(doc.disclosure_id, "1643116")
        self.assertTrue(doc.source_url.startswith("https://kap.org.tr/tr/Bildirim/"))
        self.assertEqual(doc.period, "YTD")
        self.assertEqual(doc.period_end, "2026-06-30")
        self.assertEqual(doc.currency, "TRY")
        self.assertEqual(doc.unit_label, "1.000 TL")
        self.assertEqual(doc.unit_scale, 1_000)
        self.assertIn("TUPRS", PILOT_PUBLIC_BUSINESS_SOURCES)
        self.assertEqual(PILOT_PUBLIC_BUSINESS_SOURCES["ASELS"]["activity_report_id"], "1643140")

    def test_no_paid_api_or_auth(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("api_key", source)
        self.assertNotIn("NABI_KAP_API_KEY", source)
        self.assertNotIn("Authorization", source)
        self.assertIn("TEST-ONLY", FIXTURE_DISCLAIMER)


class StructuredSegmentAndExtractionTests(unittest.TestCase):
    def test_structured_taxonomy_absent_on_public_fr(self) -> None:
        html = html_without_segment_taxonomy()
        self.assertEqual(observed_segment_taxonomy(html), ())
        self.assertIn(
            "kap-fr_RevenueFromFinanceSectorOperations",
            observed_non_segment_template(html),
        )
        doc = _doc(
            asels_official_notes(),
            symbol="ASELS",
            disclosure_id="1643141",
            html=html,
        )
        self.assertEqual(doc.structured_segment_taxonomy, STRUCTURED_SEGMENT_NO)
        self.assertTrue(doc.narrative_fallback_used)

    def test_unverified_taxonomy_is_observed_not_mapped(self) -> None:
        html = html_with_unverified_segment_taxonomy()
        self.assertEqual(
            observed_segment_taxonomy(html),
            ("ifrs-full_RevenueFromExternalCustomers",),
        )
        doc = _doc(
            tuprs_official_notes(),
            symbol="TUPRS",
            disclosure_id="1643116",
            html=html,
        )
        self.assertEqual(doc.structured_segment_taxonomy, STRUCTURED_SEGMENT_YES)
        self.assertTrue(all(item.segment_code is None for item in raw_segments_from_public(doc)[0]))

    def test_tuprs_operating_segments(self) -> None:
        doc = _doc(tuprs_official_notes(), symbol="TUPRS", disclosure_id="1643116")
        names = [item.segment_name for item in doc.segments]
        self.assertEqual(names, ["Rafinaj", "Elektrik"])
        self.assertEqual(doc.segments[0].raw_revenue, 659_045_615.0)
        self.assertEqual(doc.segments[1].raw_revenue, 3_742_395.0)
        self.assertEqual(doc.official_total_revenue, 662_788_010.0)
        self.assertTrue(all(item.breakdown_kind == BREAKDOWN_OPERATING_SEGMENT for item in doc.segments))
        self.assertNotEqual(doc.official_total_revenue, 386_420_235.0)

    def test_asels_geographic_fallback(self) -> None:
        doc = _doc(asels_official_notes(), symbol="ASELS", disclosure_id="1643141")
        names = [item.segment_name for item in doc.segments]
        self.assertEqual(names, ["Yurt içi satışlar", "Yurt dışı satışlar"])
        self.assertEqual(doc.official_total_revenue, 88_494_252.0)
        self.assertTrue(all(item.breakdown_kind == BREAKDOWN_GEOGRAPHICAL for item in doc.segments))

    def test_bimas_single_segment(self) -> None:
        doc = _doc(bimas_official_notes(), symbol="BIMAS", disclosure_id="1651656")
        self.assertEqual(len(doc.segments), 1)
        self.assertEqual(doc.segments[0].breakdown_kind, BREAKDOWN_SINGLE_SEGMENT)
        self.assertEqual(doc.segments[0].raw_revenue, 449_695_235.0)
        self.assertEqual(doc.limitation, "SINGLE_REPORTABLE_SEGMENT")


class MappingShareAndCoverageTests(unittest.TestCase):
    def test_unknown_segment_is_not_classified(self) -> None:
        doc = _doc(unknown_named_notes(), symbol="TUPRS", disclosure_id="1643116")
        bundle = build_public_bist_business_bundle(doc)
        self.assertEqual(bundle.segments[0].canonical_category, CATEGORY_UNKNOWN)
        self.assertEqual(bundle.segments[0].mapping_rule, "UNKNOWN_UNMAPPED_CODE")
        self.assertEqual(bundle.segments[0].segment_name, "CasinoBank")

    def test_revenue_share_from_document_total(self) -> None:
        bundle = build_public_bist_business_bundle(
            _doc(tuprs_official_notes(), symbol="TUPRS", disclosure_id="1643116")
        )
        shares = {item.segment_name: item.revenue_share for item in bundle.segments}
        self.assertAlmostEqual(shares["Rafinaj"], 659_045_615.0 / 662_788_010.0 * 100.0)
        self.assertAlmostEqual(shares["Elektrik"], 3_742_395.0 / 662_788_010.0 * 100.0)
        self.assertEqual(bundle.readiness, READINESS_PARTIAL)
        self.assertAlmostEqual(bundle.unknown_share, 100.0)

    def test_period_mismatch_share_and_coverage(self) -> None:
        doc = _doc(
            tuprs_official_notes(),
            symbol="TUPRS",
            disclosure_id="1643116",
        )
        coverage = cross_check_with_1e(
            doc,
            financial_total_revenue=TUPRS_1E_REVENUE,
            financial_period="FY",
            financial_currency="TRY",
        )
        self.assertEqual(coverage.status, COVERAGE_PERIOD_INCOMPATIBLE)
        self.assertFalse(coverage.used_1e_denominator_for_shares)
        self.assertIsNone(coverage.coverage_ratio)
        segments, totals = raw_segments_from_public(doc)
        assert totals is not None
        from services.bist_business_bridge import build_bist_business_bundle
        from services.bist_business_contract import BistRawBusinessTotals

        fy_totals = BistRawBusinessTotals(
            symbol=totals.symbol,
            total_revenue=totals.total_revenue,
            currency=totals.currency,
            period="FY",
            period_end="2025-12-31",
            source=totals.source,
            source_document_id=totals.source_document_id,
            as_of="2025-12-31",
        )
        bundle = build_bist_business_bundle("TUPRS", segments, fy_totals)
        self.assertEqual(bundle.segments[0].share_limitation, SHARE_PERIOD_MISMATCH)
        self.assertIsNone(bundle.segments[0].revenue_share)

    def test_currency_mismatch(self) -> None:
        doc = _doc(bimas_official_notes(), symbol="BIMAS", disclosure_id="1651656")
        coverage = cross_check_with_1e(
            doc,
            financial_total_revenue=BIMAS_1E_REVENUE,
            financial_period="YTD",
            financial_currency="USD",
        )
        self.assertEqual(coverage.status, COVERAGE_CURRENCY_MISMATCH)
        self.assertFalse(coverage.used_1e_denominator_for_shares)
        segments, totals = raw_segments_from_public(doc)
        assert totals is not None
        from services.bist_business_bridge import build_bist_business_bundle
        from services.bist_business_contract import BistRawBusinessTotals

        usd_totals = BistRawBusinessTotals(
            symbol=totals.symbol,
            total_revenue=totals.total_revenue,
            currency="USD",
            period=totals.period,
            period_end=totals.period_end,
            source=totals.source,
            source_document_id=totals.source_document_id,
            as_of=totals.as_of,
        )
        bundle = build_bist_business_bundle("BIMAS", segments, usd_totals)
        self.assertEqual(bundle.segments[0].share_limitation, SHARE_CURRENCY_MISMATCH)

    def test_revenue_coverage_remainder(self) -> None:
        doc = _doc(remainder_notes(), symbol="TUPRS", disclosure_id="1643116")
        coverage = cross_check_with_1e(
            doc,
            financial_total_revenue=120_000_000_000.0,
            financial_period="YTD",
            financial_currency="TRY",
        )
        self.assertEqual(coverage.status, COVERAGE_OK)
        self.assertAlmostEqual(coverage.coverage_ratio, 100_000_000_000.0 / 120_000_000_000.0)
        self.assertAlmostEqual(coverage.unexplained_remainder, 20_000_000_000.0)
        self.assertFalse(coverage.used_1e_denominator_for_shares)

    def test_matching_1e_coverage(self) -> None:
        for symbol, notes, total in (
            ("ASELS", asels_official_notes(), ASELS_1E_REVENUE),
            ("BIMAS", bimas_official_notes(), BIMAS_1E_REVENUE),
            ("TUPRS", tuprs_official_notes(), TUPRS_1E_REVENUE),
        ):
            doc = _doc(notes, symbol=symbol, disclosure_id=PILOT_PUBLIC_BUSINESS_REPORTS[symbol])
            coverage = cross_check_with_1e(
                doc,
                financial_total_revenue=total,
                financial_period="YTD",
                financial_currency="TRY",
            )
            self.assertEqual(coverage.status, COVERAGE_OK, symbol)
            self.assertAlmostEqual(coverage.coverage_ratio, 1.0, places=6)
            self.assertAlmostEqual(coverage.unexplained_remainder, 0.0, places=3)


class BridgeShadowAndSafetyTests(unittest.TestCase):
    def test_business_evidence_from_bist(self) -> None:
        from services.bist_business_bridge import business_evidence_from_bist

        bundle = build_public_bist_business_bundle(
            _doc(tuprs_official_notes(), symbol="TUPRS", disclosure_id="1643116")
        )
        evidence = business_evidence_from_bist(bundle)
        self.assertEqual(evidence.symbol, "TUPRS")
        self.assertEqual(len(evidence.revenue_segments), 2)
        self.assertTrue(all(item.category == CATEGORY_UNKNOWN for item in evidence.revenue_segments))
        self.assertIsNone(evidence.sector)
        self.assertIsNone(evidence.industry)

    def test_shadow_business_screen(self) -> None:
        bundle = build_public_bist_business_bundle(
            _doc(asels_official_notes(), symbol="ASELS", disclosure_id="1643141")
        )
        shadow = shadow_business_screen(bundle)
        self.assertEqual(shadow.result_kind, SHADOW_RESULT_KIND)
        self.assertEqual(shadow.symbol, "ASELS")
        self.assertFalse(shadow.persisted)
        self.assertTrue(shadow.not_participation_status)
        self.assertNotEqual(shadow.overall_outcome, "Uygun")
        payload = shadow.to_dict()
        self.assertEqual(payload["result_kind"], SHADOW_RESULT_KIND)
        self.assertNotIn("Uygun", str(payload))

    def test_no_final_verdict_persistence(self) -> None:
        bundle = build_public_bist_business_bundle(
            _doc(bimas_official_notes(), symbol="BIMAS", disclosure_id="1651656")
        )
        ready = public_participation_readiness(bundle)
        self.assertFalse(ready.final_participation_ready)
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertNotIn("ParticipationAssessmentRepository", source)
        self.assertNotIn("Uygun", source)
        self.assertNotIn("evaluate_business_activity", OLD_BRIDGE.read_text(encoding="utf-8"))
        self.assertNotIn("evaluate_business_activity", PARSER.read_text(encoding="utf-8"))
        self.assertNotIn("evaluate_business_activity", SOURCE.read_text(encoding="utf-8"))

    def test_us_isolation(self) -> None:
        doc = _doc(asels_official_notes(), symbol="ASELS", disclosure_id="1643141")
        from dataclasses import replace

        for ticker in ("AAPL", "CRM"):
            with self.assertRaises(BistBusinessIdentityError):
                build_public_bist_business_bundle(replace(doc, symbol=ticker))
        master = SecurityMasterService()
        self.assertNotEqual(master.resolve_security("AAPL").source, SOURCE_BIST)
        self.assertNotEqual(master.resolve_security("CRM").source, SOURCE_BIST)

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
        self.assertNotIn("NABI_TEST.BIZ", PARSER.read_text(encoding="utf-8"))
        self.assertNotIn("NABI_TEST.BIZ", SOURCE.read_text(encoding="utf-8"))

    def test_financial_gap_inventory(self) -> None:
        observed = (
            "ifrs-full_CashAndCashEquivalents",
            "ifrs-full_CurrentTradeReceivables",
            "ifrs-full_LongtermBorrowings",
            "kap-fr_OtherCurrentFinancialInvestments",
        )
        gaps = {item.field: item for item in inventory_participation_financial_gaps(observed)}
        self.assertEqual(gaps["accounts_receivable"].status, GAP_AVAILABLE_FROM_PUBLIC_KAP)
        self.assertEqual(gaps["cash_and_interest_bearing_securities"].status, GAP_METHODOLOGY_UNRESOLVED)
        self.assertEqual(gaps["non_permissible_revenue"].status, GAP_METHODOLOGY_UNRESOLVED)
        self.assertEqual(gaps["interest_bearing_debt"].status, GAP_METHODOLOGY_UNRESOLVED)
        self.assertEqual(gaps["market_capitalization"].status, GAP_REQUIRES_OTHER_PUBLIC_SOURCE)
        self.assertEqual(gaps["average_market_cap_24m"].status, GAP_REQUIRES_OTHER_PUBLIC_SOURCE)
        self.assertEqual(set(PILOT_PUBLIC_BUSINESS_REPORTS), {"ASELS", "BIMAS", "TUPRS"})


if __name__ == "__main__":
    unittest.main()
