from __future__ import annotations

import unittest

from services.participation_filing_npr_resolver import (
    CLASS_NPR_PROVEN_ZERO,
    assess_with_filing_npr,
    resolve_npr_from_cached_filing,
)
from services.participation_business_contract import BusinessActivityEvidence
from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
)
from services.participation_revenue_attribution_contract import (
    MAPPING_AMBIGUOUS,
    MAPPING_NO_MATCH,
    PARTITION_COMPLETE,
    RevenueAttributionItem,
    RevenueAttributionView,
)
from services.participation_revenue_granularity import can_conclude_zero_prohibited_revenue
from services.participation_revenue_semantic_type import (
    SEMANTIC_BROAD_OPERATING_SEGMENT,
    SEMANTIC_CUSTOMER_INDUSTRY_REVENUE,
    SEMANTIC_FINANCE_INTEREST_INCOME,
    SEMANTIC_GEOGRAPHIC_REVENUE,
    SEMANTIC_MERCHANDISE_CATEGORY,
    SEMANTIC_OWN_ACTIVITY_REVENUE,
    SEMANTIC_UNKNOWN,
    classify_revenue_semantic_type,
)
from tests.test_global_participation_reconciliation import _snapshot
from tests.test_participation_cached_evidence_resolver import _facts_payload
from tests.test_participation_filing_npr_resolver import _evidence
from tests.test_participation_inline_xbrl_attribution import CRM_MINIMAL_IXBRL as CRM_IXBRL
from services.global_participation_reconciliation import assess_from_cached_evidence
from services.sec_company_facts_evidence import build_company_facts_evidence
from services.sec_financial_client import SECFinancialClient
from services.sec_participation_evidence_population import AssessedEquityIdentity


def _item(
    label: str,
    amount: float,
    *,
    axis: str,
    concept: str = "us-gaap:Revenues",
    mapping: str = MAPPING_NO_MATCH,
) -> RevenueAttributionItem:
    return RevenueAttributionItem(
        reported_label=label,
        normalized_label=label.lower(),
        concept=concept,
        axis=axis,
        member=label.replace(" ", "") + "Member",
        amount=amount,
        mapping_status=mapping,
        msci_category="",
        mapping_rule_id="test",
        rationale="test",
        source="https://sec.gov",
    )


ACN_INDUSTRY_IXBRL = """
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024">
  <xbrli:context id="c-consolidated">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001467373</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-09-01</xbrli:startDate><xbrli:endDate>2025-08-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-emea">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001467373</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-09-01</xbrli:startDate><xbrli:endDate>2025-08-31</xbrli:endDate></xbrli:period>
    <xbrli:segment>
      <xbrli:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">acn:EMEASegmentMember</xbrli:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:context id="c-fs">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001467373</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-09-01</xbrli:startDate><xbrli:endDate>2025-08-31</xbrli:endDate></xbrli:period>
    <xbrli:segment>
      <xbrli:explicitMember dimension="us-gaap:EquitySecuritiesByIndustryAxis">us-gaap:FinancialServicesSectorMember</xbrli:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-consolidated" unitRef="usd" scale="6" decimals="-6">100</ix:nonFraction>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-emea" unitRef="usd" scale="6" decimals="-6">100</ix:nonFraction>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-fs" unitRef="usd" scale="6" decimals="-6">40</ix:nonFraction>
</html>
"""

WMT_MERCH_IXBRL = """
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024">
  <xbrli:context id="c-consolidated">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000104169</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-02-01</xbrli:startDate><xbrli:endDate>2026-01-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-us">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000104169</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-02-01</xbrli:startDate><xbrli:endDate>2026-01-31</xbrli:endDate></xbrli:period>
    <xbrli:segment>
      <xbrli:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">wmt:WalmartUSMember</xbrli:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:context id="c-grocery">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000104169</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-02-01</xbrli:startDate><xbrli:endDate>2026-01-31</xbrli:endDate></xbrli:period>
    <xbrli:segment>
      <xbrli:explicitMember dimension="us-gaap:ProductOrServiceAxis">wmt:GroceryMember</xbrli:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-consolidated" unitRef="usd" scale="6" decimals="-6">100</ix:nonFraction>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-us" unitRef="usd" scale="6" decimals="-6">100</ix:nonFraction>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-grocery" unitRef="usd" scale="6" decimals="-6">60</ix:nonFraction>
</html>
"""

DE_FINANCE_IXBRL = """
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024">
  <xbrli:context id="c-consolidated">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000315189</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-11-03</xbrli:startDate><xbrli:endDate>2025-11-02</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-product">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000315189</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-11-03</xbrli:startDate><xbrli:endDate>2025-11-02</xbrli:endDate></xbrli:period>
    <xbrli:segment>
      <xbrli:explicitMember dimension="us-gaap:ProductOrServiceAxis">us-gaap:ProductMember</xbrli:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:context id="c-finance">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000315189</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-11-03</xbrli:startDate><xbrli:endDate>2025-11-02</xbrli:endDate></xbrli:period>
    <xbrli:segment>
      <xbrli:explicitMember dimension="us-gaap:ProductOrServiceAxis">us-gaap:FinancialServiceMember</xbrli:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:context id="c-seg">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000315189</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-11-03</xbrli:startDate><xbrli:endDate>2025-11-02</xbrli:endDate></xbrli:period>
    <xbrli:segment>
      <xbrli:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">de:FinancialServicesSegmentMember</xbrli:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-consolidated" unitRef="usd" scale="6" decimals="-6">100</ix:nonFraction>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-product" unitRef="usd" scale="6" decimals="-6">80</ix:nonFraction>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-finance" unitRef="usd" scale="6" decimals="-6">20</ix:nonFraction>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-seg" unitRef="usd" scale="6" decimals="-6">20</ix:nonFraction>
  <ix:nonFraction name="us-gaap:InterestIncomeNonoperating" contextRef="c-consolidated" unitRef="usd" scale="6" decimals="-6">5</ix:nonFraction>
</html>
"""

GEO_IXBRL = CRM_IXBRL.replace(
    "us-gaap:ProductOrServiceAxis",
    "us-gaap:StatementGeographicalAxis",
).replace(
    "us-gaap:SubscriptionAndSupportMember",
    "srt:NorthAmericaMember",
).replace(
    "crm:ProfessionalServicesAndOtherMember",
    "srt:EuropeMember",
)


class SemanticClassifierTests(unittest.TestCase):
    def test_customer_industry_is_not_own_activity(self) -> None:
        result = classify_revenue_semantic_type(
            _item(
                "Financial Services Sector",
                40.0,
                axis="EquitySecuritiesByIndustryAxis",
                mapping=MAPPING_AMBIGUOUS,
            )
        )
        self.assertEqual(result.semantic_type, SEMANTIC_CUSTOMER_INDUSTRY_REVENUE)
        self.assertNotEqual(result.semantic_type, SEMANTIC_OWN_ACTIVITY_REVENUE)

    def test_geography_is_not_activity(self) -> None:
        result = classify_revenue_semantic_type(
            _item("North America", 10.0, axis="StatementGeographicalAxis")
        )
        self.assertEqual(result.semantic_type, SEMANTIC_GEOGRAPHIC_REVENUE)

    def test_operating_segment_named_financial_is_broad_not_interest(self) -> None:
        result = classify_revenue_semantic_type(
            _item(
                "Financial Services Segment",
                20.0,
                axis="StatementBusinessSegmentsAxis",
                mapping=MAPPING_AMBIGUOUS,
            )
        )
        self.assertEqual(result.semantic_type, SEMANTIC_BROAD_OPERATING_SEGMENT)
        self.assertNotEqual(result.semantic_type, SEMANTIC_FINANCE_INTEREST_INCOME)

    def test_interest_concept_is_finance_interest(self) -> None:
        result = classify_revenue_semantic_type(
            _item(
                "InterestIncomeNonoperating",
                5.0,
                axis="",
                concept="us-gaap:InterestIncomeNonoperating",
            )
        )
        self.assertEqual(result.semantic_type, SEMANTIC_FINANCE_INTEREST_INCOME)

    def test_uncertain_axis_is_unknown(self) -> None:
        result = classify_revenue_semantic_type(
            _item("Award Type", 1.0, axis="AwardTypeAxis")
        )
        self.assertEqual(result.semantic_type, SEMANTIC_UNKNOWN)

    def test_geography_partition_is_not_activity(self) -> None:
        resolved = resolve_npr_from_cached_filing(
            _evidence(GEO_IXBRL, symbol="MSFT"),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        geo = [
            item
            for item in resolved.retained_items
            if item["semantic_type"] == SEMANTIC_GEOGRAPHIC_REVENUE
        ]
        self.assertTrue(geo)
        self.assertTrue(all(not item["included_in_npr_calculation"] for item in geo))
        self.assertFalse(resolved.safe_zero)
        self.assertIsNone(resolved.npr_amount)

    def test_semantic_type_retained_with_provenance(self) -> None:
        resolved = resolve_npr_from_cached_filing(
            _evidence(CRM_IXBRL),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertTrue(resolved.retained_items)
        for item in resolved.retained_items:
            self.assertEqual(item["semantic_type"], SEMANTIC_OWN_ACTIVITY_REVENUE)
            self.assertTrue(item["semantic_reason"])
            self.assertEqual(item["accession"], "0001108524-26-000001")
            self.assertEqual(item["period"], "2026-01-31")


class SemanticSafetyTests(unittest.TestCase):
    def test_merchandise_does_not_support_safe_zero(self) -> None:
        items = (
            _item("Grocery", 60.0, axis="ProductOrServiceAxis"),
            _item("General Merchandise", 40.0, axis="ProductOrServiceAxis"),
        )
        view = RevenueAttributionView(
            symbol="WMT",
            cik="1",
            methodology="msci_islamic_index_series",
            methodology_version="2025-05",
            screening_period="2026-01-31",
            filing_accession="0001",
            filing_form="10-K",
            filing_date="2026-03-13",
            filing_url="https://sec.gov",
            primary_document="w.htm",
            denominator_name="Revenues",
            denominator_value=100.0,
            currency="USD",
            selected_axis="ProductOrServiceAxis",
            partition_status=PARTITION_COMPLETE,
            partition_sum=100.0,
            partition_coverage=1.0,
            items=items,
            prohibited_revenue=0.0,
            status="SUCCESS",
        )
        self.assertFalse(can_conclude_zero_prohibited_revenue(view).allowed)
        self.assertEqual(
            classify_revenue_semantic_type(items[0]).semantic_type,
            SEMANTIC_MERCHANDISE_CATEGORY,
        )

    def test_finance_interest_does_not_bypass_methodology(self) -> None:
        resolved = resolve_npr_from_cached_filing(
            _evidence(DE_FINANCE_IXBRL, symbol="DE"),
            canonical_period="2025-11-02",
            canonical_revenue=100_000_000.0,
        )
        interest = [
            item
            for item in resolved.retained_items
            if item["semantic_type"] == SEMANTIC_FINANCE_INTEREST_INCOME
        ]
        self.assertTrue(interest)
        self.assertTrue(all(not item["included_in_npr_calculation"] for item in interest))
        self.assertTrue(all(not item["included_in_safe_zero_partition"] for item in interest))
        self.assertIsNone(resolved.npr_amount)
        self.assertFalse(resolved.safe_zero)

    def test_existing_safe_zero_unchanged_for_own_activity(self) -> None:
        resolved = resolve_npr_from_cached_filing(
            _evidence(CRM_IXBRL),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertEqual(resolved.classification, CLASS_NPR_PROVEN_ZERO)
        self.assertEqual(resolved.npr_amount, 0.0)
        self.assertTrue(resolved.safe_zero)

    def test_ambiguous_evidence_remains_visible(self) -> None:
        resolved = resolve_npr_from_cached_filing(
            _evidence(ACN_INDUSTRY_IXBRL, symbol="ACN"),
            canonical_period="2025-08-31",
            canonical_revenue=100_000_000.0,
        )
        labels = {item["label"] for item in resolved.retained_items}
        self.assertTrue(any("Financial" in label for label in labels))
        self.assertIsNone(resolved.npr_amount)


class PilotAcceptanceTests(unittest.TestCase):
    def test_acn_customer_industry_is_not_own_finance(self) -> None:
        resolved = resolve_npr_from_cached_filing(
            _evidence(ACN_INDUSTRY_IXBRL, symbol="ACN"),
            canonical_period="2025-08-31",
            canonical_revenue=100_000_000.0,
        )
        industry = [
            item
            for item in resolved.retained_items
            if item["semantic_type"] == SEMANTIC_CUSTOMER_INDUSTRY_REVENUE
        ]
        self.assertTrue(industry)
        self.assertTrue(all(not item["included_in_npr_calculation"] for item in industry))
        assessed = assess_with_filing_npr(
            symbol="ACN",
            financial_inputs=ParticipationFinancialInputs(symbol="ACN", total_revenue=100.0),
            business_evidence=BusinessActivityEvidence(symbol="ACN", source="test"),
            filing_resolution=resolved,
        )
        self.assertEqual(assessed["status"], PARTICIPATION_STATUS_KONTROL_ET)

    def test_wmt_merchandise_and_banners_do_not_safe_zero(self) -> None:
        resolved = resolve_npr_from_cached_filing(
            _evidence(WMT_MERCH_IXBRL, symbol="WMT"),
            canonical_period="2026-01-31",
            canonical_revenue=100_000_000.0,
        )
        types = {item["semantic_type"] for item in resolved.retained_items}
        self.assertIn(SEMANTIC_BROAD_OPERATING_SEGMENT, types)
        self.assertIn(SEMANTIC_MERCHANDISE_CATEGORY, types)
        self.assertFalse(resolved.safe_zero)
        self.assertIsNone(resolved.npr_amount)
        assessed = assess_with_filing_npr(
            symbol="WMT",
            financial_inputs=ParticipationFinancialInputs(symbol="WMT", total_revenue=100.0),
            business_evidence=BusinessActivityEvidence(symbol="WMT", source="test"),
            filing_resolution=resolved,
        )
        self.assertEqual(assessed["status"], PARTICIPATION_STATUS_KONTROL_ET)

    def test_de_preserves_operating_versus_interest_evidence(self) -> None:
        resolved = resolve_npr_from_cached_filing(
            _evidence(DE_FINANCE_IXBRL, symbol="DE"),
            canonical_period="2025-11-02",
            canonical_revenue=100_000_000.0,
        )
        by_type: dict[str, list[str]] = {}
        for item in resolved.retained_items:
            by_type.setdefault(item["semantic_type"], []).append(item["label"])
        self.assertIn(SEMANTIC_BROAD_OPERATING_SEGMENT, by_type)
        self.assertIn(SEMANTIC_FINANCE_INTEREST_INCOME, by_type)
        self.assertTrue(
            any("Financial" in label for label in by_type.get(SEMANTIC_BROAD_OPERATING_SEGMENT, ()))
            or any(item["semantic_type"] == SEMANTIC_UNKNOWN for item in resolved.retained_items)
        )
        self.assertNotEqual(resolved.classification, CLASS_NPR_PROVEN_ZERO)
        assessed = assess_with_filing_npr(
            symbol="DE",
            financial_inputs=ParticipationFinancialInputs(symbol="DE", total_revenue=100.0),
            business_evidence=BusinessActivityEvidence(symbol="DE", source="test"),
            filing_resolution=resolved,
        )
        self.assertEqual(assessed["status"], PARTICIPATION_STATUS_KONTROL_ET)

    def test_approved_anchor_not_regressed(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
