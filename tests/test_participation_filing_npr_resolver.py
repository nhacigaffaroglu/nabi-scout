from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from services.candidate_pipeline_presentation import is_actionable_opportunity
from services.global_participation_reconciliation import assess_from_cached_evidence
from services.participation_business_contract import BusinessActivityEvidence
from services.participation_filing_npr_resolver import (
    CLASS_ATTRIBUTION_PRESENT_BUT_TOO_BROAD,
    CLASS_FILING_HAS_NO_USABLE_ATTRIBUTION,
    CLASS_MAPPING_AMBIGUOUS,
    CLASS_NPR_PROVEN_AMOUNT,
    CLASS_NPR_PROVEN_ZERO,
    CLASS_PARSER_LIMITATION,
    CLASS_PERIOD_MISMATCH,
    assess_with_filing_npr,
    resolve_npr_from_cached_filing,
)
from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from repositories.sec_filing_evidence_cache import SecFilingEvidenceCache
from services.sec_filing_evidence import build_filing_evidence
from services.sec_inline_xbrl_parser import deduplicate_facts, parse_inline_xbrl_document
from services.sec_participation_evidence_population import AssessedEquityIdentity
from tests.test_global_participation_reconciliation import _snapshot
from tests.test_participation_cached_evidence_resolver import _facts_payload
from tests.test_participation_inline_xbrl_attribution import CRM_MINIMAL_IXBRL


def _evidence(raw: str, *, symbol: str = "CRM") -> object:
    return build_filing_evidence(
        symbol=symbol,
        cik="1108524",
        accession="0001108524-26-000001",
        form="10-K",
        filing_date="2026-03-12",
        primary_document="crm.htm",
        raw_bytes=raw.encode("utf-8"),
        fiscal_year=2026,
    )


BROAD_IXBRL = CRM_MINIMAL_IXBRL.replace(
    "us-gaap:ProductOrServiceAxis",
    "us-gaap:StatementBusinessSegmentsAxis",
).replace(
    "us-gaap:SubscriptionAndSupportMember",
    "us-gaap:GoogleServicesMember",
).replace(
    "crm:ProfessionalServicesAndOtherMember",
    "us-gaap:GoogleCloudMember",
)

PROHIBITED_IXBRL = CRM_MINIMAL_IXBRL.replace(
    "crm:ProfessionalServicesAndOtherMember",
    "us-gaap:CasinoOperationsMember",
)

AMBIGUOUS_IXBRL = CRM_MINIMAL_IXBRL.replace(
    "crm:ProfessionalServicesAndOtherMember",
    "us-gaap:FinancialServicesMember",
)


class FilingNprResolverTests(unittest.TestCase):
    def test_product_partition_can_safe_zero(self) -> None:
        result = resolve_npr_from_cached_filing(
            _evidence(CRM_MINIMAL_IXBRL),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertTrue(result.parser_success)
        self.assertTrue(result.period_match)
        self.assertEqual(result.npr_amount, 0.0)
        self.assertTrue(result.safe_zero)
        self.assertEqual(result.classification, CLASS_NPR_PROVEN_ZERO)
        self.assertGreaterEqual(result.coverage or 0, 0.98)
        self.assertAlmostEqual(result.attributed_revenue or 0, 41_525_000_000.0)
        self.assertAlmostEqual(result.canonical_revenue or 0, 41_525_000_000.0)
        self.assertEqual(result.provenance[0][0], "source_type")
        resolver_src = Path(
            "services/participation_filing_npr_resolver.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('if symbol == "', resolver_src)

    def test_period_mismatch_does_not_emit_npr(self) -> None:
        result = resolve_npr_from_cached_filing(
            _evidence(CRM_MINIMAL_IXBRL),
            canonical_period="2024-12-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertFalse(result.period_match)
        self.assertIsNone(result.npr_amount)
        self.assertEqual(result.classification, CLASS_PERIOD_MISMATCH)

    def test_missing_is_not_zero(self) -> None:
        empty = "<html xmlns='http://www.w3.org/1999/xhtml'></html>"
        result = resolve_npr_from_cached_filing(
            _evidence(empty, symbol="NVDA"),
            canonical_period="2025-12-31",
            canonical_revenue=100.0,
        )
        self.assertIsNone(result.npr_amount)
        self.assertFalse(result.safe_zero)
        self.assertIn(
            result.classification,
            {CLASS_FILING_HAS_NO_USABLE_ATTRIBUTION, CLASS_PARSER_LIMITATION},
        )

    def test_broad_operating_segment_is_not_safe_zero(self) -> None:
        result = resolve_npr_from_cached_filing(
            _evidence(BROAD_IXBRL, symbol="GOOGL"),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertIsNone(result.npr_amount)
        self.assertFalse(result.safe_zero)
        self.assertIn(
            result.classification,
            {CLASS_ATTRIBUTION_PRESENT_BUT_TOO_BROAD, CLASS_FILING_HAS_NO_USABLE_ATTRIBUTION},
        )

    def test_dimensions_and_duplicates_are_preserved_not_summed(self) -> None:
        doc = parse_inline_xbrl_document(CRM_MINIMAL_IXBRL)
        deduped = deduplicate_facts(doc.facts, doc.contexts)
        self.assertEqual(len(deduped), 3)
        dimensional = [
            fact
            for fact in deduped
            if doc.contexts[fact.context_id].dimensions
        ]
        self.assertEqual(len(dimensional), 2)

    def test_ambiguous_mapping_stays_unresolved(self) -> None:
        result = resolve_npr_from_cached_filing(
            _evidence(AMBIGUOUS_IXBRL, symbol="ACN"),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertTrue(result.mapping_ambiguous)
        self.assertIsNone(result.npr_amount)
        self.assertFalse(result.safe_zero)
        self.assertEqual(result.classification, CLASS_MAPPING_AMBIGUOUS)
        self.assertIn("ambiguous under MSCI taxonomy", " ".join(result.limitations))
        self.assertGreater(result.candidate_count, 0)
        ambiguous_items = [
            item
            for item in (result.attribution.items if result.attribution else ())
            if item.mapping_status == "AMBIGUOUS"
        ]
        self.assertTrue(ambiguous_items)
        for item in ambiguous_items:
            self.assertFalse(item.included_in_npr_calculation)
            self.assertFalse(item.included_in_safe_zero_partition)
            self.assertTrue(item.ambiguity_reason)
            self.assertEqual(item.accession, "0001108524-26-000001")
            self.assertEqual(item.period, "2026-01-31")
        coverage = result.evidence_coverage
        self.assertIsNotNone(coverage)
        self.assertGreater(coverage.ambiguous_revenue, 0)
        self.assertEqual(coverage.mapped_prohibited_revenue, 0.0)
        self.assertLess(
            coverage.mapped_permissible_revenue,
            coverage.ambiguous_revenue + coverage.mapped_permissible_revenue,
        )

    def test_explicit_prohibited_amount_is_derived(self) -> None:
        result = resolve_npr_from_cached_filing(
            _evidence(PROHIBITED_IXBRL, symbol="TEST"),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertEqual(result.npr_amount, 2_137_000_000.0)
        self.assertFalse(result.safe_zero)
        self.assertEqual(result.classification, CLASS_NPR_PROVEN_AMOUNT)

    def test_offline_replay_uses_cached_bytes_only(self) -> None:
        raw = CRM_MINIMAL_IXBRL.encode("utf-8")
        with TemporaryDirectory() as tmp:
            cache = SecFilingEvidenceCache(root=Path(tmp))
            stored, created = cache.store_if_new(
                symbol="CRM",
                cik="1108524",
                accession="0001108524-26-000001",
                form="10-K",
                filing_date="2026-03-12",
                primary_document="crm.htm",
                raw_bytes=raw,
                fiscal_year=2026,
            )
            self.assertTrue(created)
            replayed = cache.get_by_digest(stored.content_digest)
            self.assertIsNotNone(replayed)
            result = resolve_npr_from_cached_filing(
                replayed,
                canonical_period="2026-01-31",
                canonical_revenue=41_525_000_000.0,
            )
            self.assertEqual(result.classification, CLASS_NPR_PROVEN_ZERO)
            self.assertEqual(cache.verify_digest(stored.content_digest), stored.content_digest)


class FilingParticipationAndFirewallTests(unittest.TestCase):
    def test_proven_zero_can_pass_npr_without_writing(self) -> None:
        resolution = resolve_npr_from_cached_filing(
            _evidence(CRM_MINIMAL_IXBRL),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        assessed = assess_with_filing_npr(
            symbol="CRM",
            financial_inputs=ParticipationFinancialInputs(
                symbol="CRM",
                total_debt=1.0,
                total_assets=100.0,
                cash=10.0,
                cash_and_interest_bearing_securities=10.0,
                accounts_receivable=5.0,
                total_revenue=41_525_000_000.0,
                non_permissible_revenue=None,
            ),
            business_evidence=BusinessActivityEvidence(
                symbol="CRM",
                sic_code="7372",
                sector="technology",
                industry="software - application",
                source="sec+candidate_record",
            ),
            filing_resolution=resolution,
        )
        self.assertEqual(resolution.classification, CLASS_NPR_PROVEN_ZERO)
        self.assertIn(assessed["status"], {PARTICIPATION_STATUS_UYGUN, PARTICIPATION_STATUS_KONTROL_ET})

    def test_kontrol_et_is_not_actionable(self) -> None:
        self.assertFalse(
            is_actionable_opportunity(
                {
                    "symbol": "NVDA",
                    "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
                    "decision": "GÜÇLÜ ADAY",
                    "current_price": 10.0,
                    "data_completeness": 90,
                    "last_scanned_at": "2026-08-01T00:00:00+00:00",
                    "research_status": "TAMAMLANDI",
                }
            )
        )

    def test_approved_anchor_not_replaced_by_weaker_cache_only(self) -> None:
        from services.sec_company_facts_evidence import build_company_facts_evidence
        from services.sec_financial_client import SECFinancialClient

        evidence = build_company_facts_evidence(
            symbol="CRM",
            cik="0001108524",
            raw_payload=_facts_payload(),
            http_status=200,
        )
        extracted = SECFinancialClient(contact_email="cache-replay@localhost").extract_financials(
            evidence.raw_payload
        )
        item = assess_from_cached_evidence(
            identity=AssessedEquityIdentity(
                symbol="CRM",
                cik="0001108524",
                cik_source="snapshot",
                fetchable=True,
            ),
            evidence=evidence,
            snapshot=_snapshot("CRM", "0001108524", PARTICIPATION_STATUS_UYGUN),
            extracted=extracted,
        )
        self.assertEqual(item.new_status, PARTICIPATION_STATUS_UYGUN)

    def test_rejected_fail_is_not_converted_to_uygun(self) -> None:
        from services.sec_company_facts_evidence import build_company_facts_evidence
        from services.sec_financial_client import SECFinancialClient

        payload = _facts_payload()
        payload["facts"]["us-gaap"]["LongTermDebtNoncurrent"] = {
            "units": {
                "USD": [
                    {
                        "form": "10-K",
                        "end": "2025-12-31",
                        "val": 400.0,
                        "filed": "2026-02-17",
                    }
                ]
            }
        }
        evidence = build_company_facts_evidence(
            symbol="AAPL",
            cik="0000320193",
            raw_payload=payload,
            http_status=200,
        )
        extracted = SECFinancialClient(contact_email="cache-replay@localhost").extract_financials(
            evidence.raw_payload
        )
        snapshot = _snapshot("AAPL", "0000320193", PARTICIPATION_STATUS_UYGUN_DEGIL)
        snapshot["assessment_payload"]["financial_inputs"]["non_permissible_revenue"] = None
        item = assess_from_cached_evidence(
            identity=AssessedEquityIdentity(
                symbol="AAPL",
                cik="0000320193",
                cik_source="snapshot",
                fetchable=True,
            ),
            evidence=evidence,
            snapshot=snapshot,
            extracted=extracted,
        )
        self.assertNotEqual(item.new_status, PARTICIPATION_STATUS_UYGUN)


if __name__ == "__main__":
    unittest.main()
