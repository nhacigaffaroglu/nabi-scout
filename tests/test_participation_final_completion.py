import unittest
from datetime import date
from decimal import Decimal

from services.participation_assessment_service import assess_equity_participation
from services.participation_business_contract import BusinessActivityEvidence, BusinessRevenueEvidence
from services.participation_business_engine import evaluate_business_activity
from services.participation_business_evidence_enrichment import derive_non_permissible_revenue_amount
from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_financial_engine import evaluate_financial_rules
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
)
from services.participation_intelligence_service import build_combined_methodology_assessment
from services.participation_methodology_audit import audit_methodology
from services.participation_methodology_capabilities import build_methodology_capability_graph
from services.participation_methodology_registry import clear_registry_cache_for_tests
from services.participation_pass_logic import can_emit_uygun
from services.participation_revenue_segment_contract import RevenueSegmentEvidence
from services.participation_sec_segment_resolver import (
    merge_revenue_segment_sources,
    revenue_segments_to_business_evidence,
)
from services.participation_segment_classifier import classify_segment
from services.research_eligibility_service import evaluate_research_eligibility_from_assessment
from tests.test_participation_assessment_service import MockSECClient, sample_sec_financials


def complete_msci_financial_inputs(**overrides) -> ParticipationFinancialInputs:
    base = dict(
        symbol="TEST",
        as_of_date=date(2026, 1, 1),
        total_debt=30_000_000.0,
        cash=10_000_000.0,
        cash_and_interest_bearing_securities=15_000_000.0,
        accounts_receivable=15_000_000.0,
        total_assets=100_000_000.0,
        total_revenue=1_000_000_000.0,
        non_permissible_revenue=10_000_000.0,
    )
    base.update(overrides)
    return ParticipationFinancialInputs(**base)


def complete_msci_business_evidence(**overrides) -> BusinessActivityEvidence:
    base = dict(
        symbol="TEST",
        sector="Technology",
        industry="Software - Application",
        sic_code="7372",
        source="sec_entity_metadata+candidate_record",
        reported_total_revenue=1_000_000_000.0,
        revenue_segments=(
            BusinessRevenueEvidence(
                category="non_permissible",
                segment_name="Non-permissible income",
                revenue_pct=1.0,
                source="segment_disclosure",
                confidence="HIGH",
            ),
        ),
        evidence_refs=(
            ("sic_code", "7372"),
            ("sector", "Technology"),
            ("industry", "Software - Application"),
        ),
    )
    base.update(overrides)
    return BusinessActivityEvidence(**base)


class RevenueSegmentPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_cache_for_tests()

    def test_complete_segments_below_threshold(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            complete_msci_business_evidence(),
        )
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_PASS)

    def test_prohibited_ratio_above_threshold_fail(self) -> None:
        evidence = complete_msci_business_evidence(
            revenue_segments=(
                BusinessRevenueEvidence(
                    category="non_permissible",
                    segment_name="Non-permissible income",
                    revenue_pct=6.0,
                    source="segment_disclosure",
                ),
            ),
        )
        result = evaluate_business_activity("msci_islamic_index_series", evidence)
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_FAIL)

    def test_boundary_exactly_at_threshold_fail(self) -> None:
        evidence = complete_msci_business_evidence(
            revenue_segments=(
                BusinessRevenueEvidence(
                    category="non_permissible",
                    segment_name="Non-permissible income",
                    revenue_pct=5.0,
                    source="segment_disclosure",
                ),
            ),
        )
        result = evaluate_business_activity("msci_islamic_index_series", evidence)
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_FAIL)

    def test_unknown_segments_near_threshold_review(self) -> None:
        evidence = complete_msci_business_evidence(
            revenue_segments=(
                BusinessRevenueEvidence(
                    category="unknown",
                    segment_name="Other operations",
                    revenue_value=40_000_000.0,
                    source="sec",
                ),
                BusinessRevenueEvidence(
                    category="non_permissible",
                    segment_name="Non-permissible income",
                    revenue_value=40_000_000.0,
                    source="sec",
                ),
            ),
        )
        result = evaluate_business_activity("msci_islamic_index_series", evidence)
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertIn(
            revenue_rule.outcome,
            {RULE_OUTCOME_REVIEW_REQUIRED, RULE_OUTCOME_FAIL, RULE_OUTCOME_INSUFFICIENT_DATA},
        )

    def test_no_description_inference(self) -> None:
        amount, warnings = derive_non_permissible_revenue_amount(
            1_000_000.0,
            (),
        )
        self.assertIsNone(amount)
        self.assertTrue(warnings)

    def test_segment_classifier_non_permissible(self) -> None:
        segment = classify_segment(
            RevenueSegmentEvidence(
                segment_id="1",
                segment_name="Interest income segment",
                revenue_amount=100.0,
            ),
            prohibited_categories=("conventional_banking",),
        )
        self.assertEqual(segment.classification_code, "NON_PERMISSIBLE")

    def test_merge_duplicate_segment_names(self) -> None:
        merged = merge_revenue_segment_sources(
            (
                BusinessRevenueEvidence(
                    category="non_permissible",
                    segment_name="Gaming",
                    revenue_value=100.0,
                    source="sec",
                ),
            ),
            (
                BusinessRevenueEvidence(
                    category="non_permissible",
                    segment_name="gaming",
                    revenue_value=200.0,
                    source="sec",
                ),
            ),
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].revenue_value, 200.0)


class BusinessPositiveEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_cache_for_tests()

    def test_prohibited_sic_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            complete_msci_business_evidence(sic_code="7990"),
        )
        sic_rule = next(r for r in result.rule_results if "sic" in r.rule_id)
        self.assertEqual(sic_rule.outcome, RULE_OUTCOME_FAIL)

    def test_trusted_sic_pass(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            complete_msci_business_evidence(sic_code="7372"),
        )
        sic_rule = next(r for r in result.rule_results if "sic" in r.rule_id)
        self.assertEqual(sic_rule.outcome, RULE_OUTCOME_PASS)

    def test_unmapped_untrusted_sic_insufficient(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            BusinessActivityEvidence(symbol="TEST", sic_code="9999"),
        )
        sic_rule = next(r for r in result.rule_results if "sic" in r.rule_id)
        self.assertEqual(sic_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_trusted_sector_pass(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            complete_msci_business_evidence(),
        )
        sector_rule = next(r for r in result.rule_results if "sector" in r.rule_id)
        self.assertEqual(sector_rule.outcome, RULE_OUTCOME_PASS)

    def test_description_no_keyword_not_pass(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            complete_msci_business_evidence(business_description="enterprise software provider"),
        )
        desc_rule = next(r for r in result.rule_results if "description" in r.rule_id)
        self.assertEqual(desc_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)


class CompletenessAndUygunTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_cache_for_tests()
        from services.participation_business_rules_registry import load_business_rules_registry

        load_business_rules_registry.cache_clear()

    def test_complete_msci_can_emit_uygun(self) -> None:
        financial = evaluate_financial_rules(
            "msci_islamic_index_series",
            complete_msci_financial_inputs(),
        )
        business = evaluate_business_activity(
            "msci_islamic_index_series",
            complete_msci_business_evidence(),
        )
        self.assertTrue(
            can_emit_uygun(
                methodology_id="msci_islamic_index_series",
                financial_screen=financial,
                business_screen=business,
            )
        )
        assessment = build_combined_methodology_assessment(financial, business)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN)

    def test_missing_financial_field_blocks_uygun(self) -> None:
        financial = evaluate_financial_rules(
            "msci_islamic_index_series",
            complete_msci_financial_inputs(non_permissible_revenue=None),
        )
        business = evaluate_business_activity(
            "msci_islamic_index_series",
            complete_msci_business_evidence(),
        )
        self.assertFalse(
            can_emit_uygun(
                methodology_id="msci_islamic_index_series",
                financial_screen=financial,
                business_screen=business,
            )
        )

    def test_decisive_fail_despite_incomplete(self) -> None:
        financial = evaluate_financial_rules(
            "msci_islamic_index_series",
            complete_msci_financial_inputs(total_debt=80_000_000.0),
        )
        business = evaluate_business_activity(
            "msci_islamic_index_series",
            BusinessActivityEvidence(symbol="TEST"),
        )
        assessment = build_combined_methodology_assessment(financial, business)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_msci_does_not_require_historical_market_cap(self) -> None:
        graph = build_methodology_capability_graph("msci_islamic_index_series")
        self.assertNotIn("historical_market_cap_24m", graph.required_capabilities)
        self.assertNotIn("historical_market_value_equity_36m", graph.required_capabilities)

    def test_sp_requires_historical_mve(self) -> None:
        graph = build_methodology_capability_graph("sp_shariah")
        self.assertIn("historical_market_value_equity_36m", graph.required_capabilities)

    def test_methodology_self_audit_msci_ok(self) -> None:
        result = audit_methodology("msci_islamic_index_series")
        self.assertTrue(result.ok, msg=[issue.message for issue in result.issues])


class FirewallTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_cache_for_tests()

    def test_genuine_uygun_allows_research(self) -> None:
        financial = evaluate_financial_rules(
            "msci_islamic_index_series",
            complete_msci_financial_inputs(),
        )
        business = evaluate_business_activity(
            "msci_islamic_index_series",
            complete_msci_business_evidence(),
        )
        from services.participation_assessment_service import ParticipationAssessmentResult

        assessment = build_combined_methodology_assessment(financial, business)
        result = ParticipationAssessmentResult(
            symbol="TEST",
            methodology_id="msci_islamic_index_series",
            resolved_methodology_version="2024-10",
            participation_assessment=assessment,
            financial_screen_result=financial,
            business_screen_result=business,
            sec_available=True,
        )
        eligibility = evaluate_research_eligibility_from_assessment(result)
        self.assertTrue(eligibility.research_allowed)

    def test_kontrol_et_blocks_research(self) -> None:
        result = assess_equity_participation(
            "TEST",
            sec_client=MockSECClient(),
            cik=1,
        )
        eligibility = evaluate_research_eligibility_from_assessment(result)
        self.assertFalse(eligibility.research_allowed)


if __name__ == "__main__":
    unittest.main()
