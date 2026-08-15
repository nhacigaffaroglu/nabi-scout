from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.participation_business_evidence_enrichment import derive_non_permissible_revenue_amount
from services.participation_msci_revenue_mapper import map_revenue_member_to_msci
from services.participation_revenue_attribution_contract import (
    ATTRIBUTION_SUCCESS,
    MAPPING_NO_MATCH,
    PARTITION_COMPLETE,
    RevenueAttributionItem,
    RevenueAttributionView,
)
from services.sec_inline_xbrl_parser import (
    deduplicate_facts,
    parse_inline_xbrl_document,
    select_target_period_end,
)
from services.sec_primary_filing_resolver import resolve_latest_annual_filing


CRM_MINIMAL_IXBRL = """
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024">
  <xbrli:context id="c-consolidated">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001108524</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2025-02-01</xbrli:startDate>
      <xbrli:endDate>2026-01-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-subscription">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001108524</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2025-02-01</xbrli:startDate>
      <xbrli:endDate>2026-01-31</xbrli:endDate>
    </xbrli:period>
    <xbrli:segment>
      <xbrli:explicitMember dimension="us-gaap:ProductOrServiceAxis">us-gaap:SubscriptionAndSupportMember</xbrli:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:context id="c-professional">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001108524</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2025-02-01</xbrli:startDate>
      <xbrli:endDate>2026-01-31</xbrli:endDate>
    </xbrli:period>
    <xbrli:segment>
      <xbrli:explicitMember dimension="us-gaap:ProductOrServiceAxis">crm:ProfessionalServicesAndOtherMember</xbrli:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
      contextRef="c-consolidated" unitRef="usd" scale="6" decimals="-6">41525</ix:nonFraction>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
      contextRef="c-subscription" unitRef="usd" scale="6" decimals="-6">39388</ix:nonFraction>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
      contextRef="c-professional" unitRef="usd" scale="6" decimals="-6">2137</ix:nonFraction>
</html>
"""


class SECPrimaryFilingResolverTests(unittest.TestCase):
    def test_selects_latest_10k(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-Q", "10-K", "10-K/A"],
                    "accessionNumber": [
                        "0001-24-000001",
                        "0001-25-000010",
                        "0001-25-000011",
                    ],
                    "filingDate": ["2024-08-01", "2025-02-01", "2025-03-01"],
                    "reportDate": ["2024-06-30", "2025-01-31", "2025-01-31"],
                    "primaryDocument": ["q.htm", "k.htm", "ka.htm"],
                }
            }
        }
        filing = resolve_latest_annual_filing(submissions, cik="1108524")
        self.assertIsNotNone(filing)
        assert filing is not None
        self.assertEqual(filing.form, "10-K/A")
        self.assertEqual(filing.primary_document, "ka.htm")

    def test_rejects_10q_only(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-Q"],
                    "accessionNumber": ["0001-24-000001"],
                    "filingDate": ["2024-08-01"],
                    "reportDate": ["2024-06-30"],
                    "primaryDocument": ["q.htm"],
                }
            }
        }
        self.assertIsNone(resolve_latest_annual_filing(submissions, cik="1108524"))


class InlineXbrlParserTests(unittest.TestCase):
    def test_parse_facts_and_scale(self) -> None:
        doc = parse_inline_xbrl_document(CRM_MINIMAL_IXBRL)
        self.assertEqual(len(doc.facts), 3)
        values = sorted(f.normalized_value for f in doc.facts if f.normalized_value)
        self.assertEqual(values[0], 2_137_000_000.0)
        self.assertEqual(values[-1], 41_525_000_000.0)

    def test_annual_period_selection(self) -> None:
        doc = parse_inline_xbrl_document(CRM_MINIMAL_IXBRL)
        end = select_target_period_end(doc.contexts)
        self.assertEqual(end, "2026-01-31")

    def test_deduplicate_identical_facts(self) -> None:
        doc = parse_inline_xbrl_document(CRM_MINIMAL_IXBRL)
        deduped = deduplicate_facts(doc.facts, doc.contexts)
        self.assertEqual(len(deduped), 3)


class MSCIRevenueMapperTests(unittest.TestCase):
    def test_gaming_is_not_gambling(self) -> None:
        result = map_revenue_member_to_msci("Gaming")
        self.assertEqual(result.mapping_status, MAPPING_NO_MATCH)
        self.assertNotEqual(result.msci_category, "gambling")

    def test_casino_is_prohibited(self) -> None:
        result = map_revenue_member_to_msci("Casino operations")
        self.assertEqual(result.msci_category, "gambling")

    def test_advertising_not_prohibited(self) -> None:
        result = map_revenue_member_to_msci("Advertising revenue")
        self.assertEqual(result.mapping_status, MAPPING_NO_MATCH)

    def test_subscription_no_match(self) -> None:
        result = map_revenue_member_to_msci("Subscription and support")
        self.assertEqual(result.mapping_status, MAPPING_NO_MATCH)


class RevenueAttributionDerivationTests(unittest.TestCase):
    def _complete_view(self, *, prohibited: float = 0.0) -> RevenueAttributionView:
        items = (
            RevenueAttributionItem(
                reported_label="Subscription and support",
                normalized_label="subscription and support",
                concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                axis="ProductOrServiceAxis",
                member="SubscriptionAndSupportMember",
                amount=39_388_000_000.0,
                mapping_status=MAPPING_NO_MATCH,
                msci_category="",
                mapping_rule_id="msci.rev.nomatch.subscription",
                rationale="test",
                source="https://sec.gov",
            ),
        )
        return RevenueAttributionView(
            symbol="CRM",
            cik="1108524",
            methodology="msci_islamic_index_series",
            methodology_version="2025-05",
            screening_period="2026-01-31",
            filing_accession="0001108524-26-000060",
            filing_form="10-K",
            filing_date="2026-03-01",
            filing_url="https://sec.gov",
            primary_document="crm.htm",
            denominator_name="RevenueFromContractWithCustomerExcludingAssessedTax",
            denominator_value=41_525_000_000.0,
            currency="USD",
            selected_axis="ProductOrServiceAxis",
            partition_status=PARTITION_COMPLETE,
            partition_sum=41_525_000_000.0,
            partition_coverage=1.0,
            items=items,
            prohibited_revenue=prohibited,
            prohibited_ratio=prohibited / 41_525_000_000.0,
            status=ATTRIBUTION_SUCCESS,
            confidence="HIGH",
        )

    def test_complete_no_match_yields_zero_numerator(self) -> None:
        amount, warnings = derive_non_permissible_revenue_amount(
            41_525_000_000.0,
            (),
            revenue_attribution=self._complete_view(),
        )
        self.assertEqual(amount, 0.0)
        self.assertEqual(warnings, ())

    def test_incomplete_attribution_fail_closed(self) -> None:
        view = self._complete_view()
        view = RevenueAttributionView(
            **{
                **view.__dict__,
                "status": "FAIL_CLOSED",
                "limitations": ("SEC 10-K revenue partition incomplete.",),
            }
        )
        amount, warnings = derive_non_permissible_revenue_amount(
            41_525_000_000.0,
            (),
            revenue_attribution=view,
        )
        self.assertIsNone(amount)
        self.assertTrue(warnings)


class InlineXbrlAttributionEngineTests(unittest.TestCase):
    def test_crm_fixture_partition_complete(self) -> None:
        from services.participation_inline_xbrl_attribution import build_revenue_attribution_from_document
        from services.sec_primary_filing_resolver import SECPrimaryFilingRef

        doc = parse_inline_xbrl_document(CRM_MINIMAL_IXBRL)
        filing = SECPrimaryFilingRef(
            cik="1108524",
            form="10-K",
            fiscal_year=2026,
            filing_date="2026-03-01",
            accession_number="0001108524-26-000060",
            primary_document="crm-20260131.htm",
            filing_url="https://sec.gov",
            retrieved_at="2026-03-01T00:00:00+00:00",
        )
        view = build_revenue_attribution_from_document(
            doc,
            symbol="CRM",
            filing_ref=filing,
            methodology_id="msci_islamic_index_series",
            methodology_version="2025-05",
            preferred_period_end="2026-01-31",
        )
        self.assertEqual(view.partition_status, PARTITION_COMPLETE)
        self.assertAlmostEqual(view.partition_coverage or 0, 1.0, places=2)
        self.assertEqual(view.prohibited_revenue, 0.0)


if __name__ == "__main__":
    unittest.main()
