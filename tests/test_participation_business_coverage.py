import unittest

from services.participation_business_contract import BusinessActivityEvidence
from services.participation_business_coverage import (
    COVERAGE_INSUFFICIENT,
    COVERAGE_NO_PROHIBITED_SUFFICIENT,
    COVERAGE_PROHIBITED_FOUND,
    evaluate_business_activity_coverage,
)
from services.participation_business_evidence_enrichment import derive_non_permissible_revenue_amount
from services.participation_business_engine import evaluate_business_activity
from services.participation_intelligence_contract import RULE_OUTCOME_INSUFFICIENT_DATA, RULE_OUTCOME_PASS
from services.sec_financial_client import SECFinancialClient


class BusinessCoverageTests(unittest.TestCase):
    def test_insufficient_without_sic_sector_description(self) -> None:
        evidence = BusinessActivityEvidence(
            symbol="TEST",
            reported_total_revenue=1_000_000.0,
        )
        result = evaluate_business_activity_coverage(
            evidence,
            methodology_id="msci_islamic_index_series",
        )
        self.assertEqual(result.state, COVERAGE_INSUFFICIENT)

    def test_no_keyword_absence_is_not_sufficient_coverage(self) -> None:
        evidence = BusinessActivityEvidence(
            symbol="TEST",
            sic_code="7372",
            sector="Technology",
            source="sec_submissions+candidate_record",
            reported_total_revenue=1_000_000.0,
            evidence_refs=(("sic_code", "7372"), ("sector", "Technology")),
        )
        result = evaluate_business_activity_coverage(
            evidence,
            methodology_id="msci_islamic_index_series",
        )
        self.assertEqual(result.state, COVERAGE_INSUFFICIENT)

    def test_sufficient_coverage_without_prohibited_segments(self) -> None:
        evidence = BusinessActivityEvidence(
            symbol="TEST",
            sic_code="7372",
            sector="Technology",
            industry="Software - Application",
            business_description=(
                "Provides cloud software applications for customer relationship "
                "management and enterprise automation."
            ),
            source="sec_submissions+fmp_profile+candidate_record",
            reported_total_revenue=1_000_000.0,
            evidence_refs=(
                ("sic_code", "7372"),
                ("sector", "Technology"),
                ("industry", "Software - Application"),
            ),
        )
        result = evaluate_business_activity_coverage(
            evidence,
            methodology_id="msci_islamic_index_series",
        )
        self.assertEqual(result.state, COVERAGE_NO_PROHIBITED_SUFFICIENT)

    def test_prohibited_description_blocks_coverage(self) -> None:
        evidence = BusinessActivityEvidence(
            symbol="TEST",
            sic_code="7372",
            sector="Technology",
            industry="Software",
            business_description="Operates casinos and gaming facilities globally.",
            source="sec_submissions+fmp_profile",
            reported_total_revenue=1_000_000.0,
            evidence_refs=(("sic_code", "7372"), ("sector", "Technology")),
        )
        result = evaluate_business_activity_coverage(
            evidence,
            methodology_id="msci_islamic_index_series",
        )
        self.assertEqual(result.state, COVERAGE_PROHIBITED_FOUND)

    def test_coverage_does_not_infer_zero_prohibited_revenue(self) -> None:
        evidence = BusinessActivityEvidence(
            symbol="TEST",
            sic_code="7372",
            sector="Technology",
            industry="Software - Application",
            business_description=(
                "Provides cloud software applications for customer relationship "
                "management and enterprise automation."
            ),
            source="sec_submissions+fmp_profile",
            reported_total_revenue=1_000_000.0,
            evidence_refs=(("sic_code", "7372"), ("sector", "Technology")),
        )
        amount, warnings = derive_non_permissible_revenue_amount(
            1_000_000.0,
            (),
            methodology_id="msci_islamic_index_series",
            business_evidence=evidence,
        )
        self.assertIsNone(amount)
        self.assertTrue(warnings)

    def test_coverage_revenue_rule_insufficient_without_segments(self) -> None:
        evidence = BusinessActivityEvidence(
            symbol="TEST",
            sic_code="7372",
            sector="Technology",
            industry="Software - Application",
            business_description=(
                "Provides cloud software applications for customer relationship "
                "management and enterprise automation."
            ),
            source="sec_submissions+fmp_profile",
            reported_total_revenue=1_000_000.0,
            evidence_refs=(("sic_code", "7372"), ("sector", "Technology")),
        )
        screen = evaluate_business_activity("msci_islamic_index_series", evidence)
        revenue_rule = next(
            rule for rule in screen.rule_results if "non_permissible_revenue" in rule.rule_id
        )
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)


class SECSubmissionsSICTests(unittest.TestCase):
    def test_resolve_entity_metadata_uses_submissions_when_companyfacts_missing_sic(
        self,
    ) -> None:
        client = SECFinancialClient(contact_email="test@example.com")
        client._submissions_cache["0001108524"] = {
            "sic": "7372",
            "sicDescription": "Services-Prepackaged Software",
            "name": "Salesforce, Inc.",
        }
        metadata, evidence = client.resolve_entity_metadata(
            {"entityName": "Salesforce, Inc."},
            cik="1108524",
        )
        self.assertEqual(metadata["sic_code"], "7372")
        self.assertIn(("sic_source", "sec_submissions"), evidence)


class LiveRegressionTests(unittest.TestCase):
    def test_aapl_verdict_remains_uygun_degil(self) -> None:
        from services.participation_financial_engine import evaluate_financial_rules
        from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN_DEGIL
        from services.participation_intelligence_service import build_combined_methodology_assessment
        from services.participation_business_contract import BusinessActivityScreenResult
        from tests.test_participation_aapl_forensic import _aapl_like_sec_financials
        from services.participation_sec_input_resolver import build_participation_inputs_from_sec

        resolution = build_participation_inputs_from_sec("AAPL", _aapl_like_sec_financials(), cik="320193")
        financial = evaluate_financial_rules("msci_islamic_index_series", resolution.inputs)
        business = BusinessActivityScreenResult(
            symbol="AAPL",
            methodology_id="msci_islamic_index_series",
            methodology_version="2024-10",
            rule_results=(),
            overall_outcome="INSUFFICIENT_DATA",
            business_rules_evaluated=False,
            methodology_complete=False,
            warnings=(),
        )
        assessment = build_combined_methodology_assessment(financial, business)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)


if __name__ == "__main__":
    unittest.main()
