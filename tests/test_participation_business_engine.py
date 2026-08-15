import inspect
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError
from datetime import date

from services.participation_business_contract import (
    BUSINESS_SCREEN_OUTCOME_FAIL,
    BUSINESS_SCREEN_OUTCOME_INSUFFICIENT_DATA,
    BUSINESS_SCREEN_OUTCOME_PASS,
    BUSINESS_SCREEN_OUTCOME_REVIEW_REQUIRED,
    EVIDENCE_TYPE_SIC,
    BusinessActivityEvidence,
    BusinessRevenueEvidence,
)
from services.participation_business_engine import evaluate_business_activity
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
from services.participation_methodology_registry import clear_registry_cache_for_tests


def evidence(**kwargs) -> BusinessActivityEvidence:
    base = dict(symbol="TEST")
    base.update(kwargs)
    return BusinessActivityEvidence(**base)


class ContractImmutabilityTests(unittest.TestCase):
    def test_business_activity_evidence_is_frozen(self) -> None:
        item = evidence(company_name="Acme")
        with self.assertRaises(FrozenInstanceError):
            item.company_name = "Other"  # type: ignore[misc]


class MethodologyIsolationTests(unittest.TestCase):
    def test_weapons_category_only_blocks_sp_not_msci(self) -> None:
        weapons_sector = evidence(sector="Aerospace & Defense")
        msci = evaluate_business_activity("msci_islamic_index_series", weapons_sector)
        sp = evaluate_business_activity("sp_shariah", weapons_sector)
        msci_sector = next(r for r in msci.rule_results if "sector" in r.rule_id)
        sp_sector = next(r for r in sp.rule_results if "sector" in r.rule_id)
        self.assertEqual(msci_sector.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)
        self.assertEqual(sp_sector.outcome, RULE_OUTCOME_REVIEW_REQUIRED)


class StructuredProhibitedCategoryTests(unittest.TestCase):
    def test_exact_structured_gambling_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(industry="Gambling"),
        )
        sector_rule = next(r for r in result.rule_results if "sector" in r.rule_id)
        self.assertEqual(sector_rule.outcome, RULE_OUTCOME_FAIL)
        self.assertEqual(result.overall_outcome, BUSINESS_SCREEN_OUTCOME_FAIL)

    def test_sic_prohibited_mapping_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(sic_code="7990"),
        )
        sic_rule = next(r for r in result.rule_results if r.evidence_type == EVIDENCE_TYPE_SIC)
        self.assertEqual(sic_rule.outcome, RULE_OUTCOME_FAIL)
        self.assertEqual(sic_rule.category, "gambling")

    def test_unknown_sic_no_false_pass(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(sic_code="9999"),
        )
        sic_rule = next(r for r in result.rule_results if r.evidence_type == EVIDENCE_TYPE_SIC)
        self.assertEqual(sic_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)
        self.assertNotEqual(result.overall_outcome, BUSINESS_SCREEN_OUTCOME_PASS)


class DescriptionKeywordTests(unittest.TestCase):
    def test_ambiguous_casino_customer_review_required(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(business_description="serves casino industry customers"),
        )
        desc_rule = next(r for r in result.rule_results if "description" in r.rule_id)
        self.assertEqual(desc_rule.outcome, RULE_OUTCOME_REVIEW_REQUIRED)

    def test_no_keyword_not_automatic_pass(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(business_description="enterprise software provider"),
        )
        desc_rule = next(r for r in result.rule_results if "description" in r.rule_id)
        self.assertEqual(desc_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)
        self.assertNotEqual(result.overall_outcome, BUSINESS_SCREEN_OUTCOME_PASS)

    def test_explicit_casino_operator_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(business_description="Regional casino operator in Nevada"),
        )
        desc_rule = next(r for r in result.rule_results if "description" in r.rule_id)
        self.assertEqual(desc_rule.outcome, RULE_OUTCOME_FAIL)


class FalsePositiveDescriptionTests(unittest.TestCase):
    def test_does_not_manufacture_tobacco_not_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(business_description="Company does not manufacture tobacco products"),
        )
        desc_rule = next(r for r in result.rule_results if "description" in r.rule_id)
        self.assertNotEqual(desc_rule.outcome, RULE_OUTCOME_FAIL)

    def test_alcohol_free_not_review_or_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(business_description="Produces alcohol-free beverages"),
        )
        desc_rule = next(r for r in result.rule_results if "description" in r.rule_id)
        self.assertNotIn(desc_rule.outcome, {RULE_OUTCOME_FAIL, RULE_OUTCOME_REVIEW_REQUIRED})

    def test_former_banking_not_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(business_description="Former banking subsidiary now divested"),
        )
        desc_rule = next(r for r in result.rule_results if "description" in r.rule_id)
        self.assertNotEqual(desc_rule.outcome, RULE_OUTCOME_FAIL)
        self.assertIn(
            desc_rule.outcome,
            {RULE_OUTCOME_REVIEW_REQUIRED, RULE_OUTCOME_INSUFFICIENT_DATA},
        )

    def test_gaming_software_not_treated_as_gambling(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(business_description="Develops gaming software for mobile devices"),
        )
        desc_rule = next(r for r in result.rule_results if "description" in r.rule_id)
        self.assertNotEqual(desc_rule.outcome, RULE_OUTCOME_FAIL)
        self.assertEqual(desc_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_cyber_defense_not_weapons_fail(self) -> None:
        result = evaluate_business_activity(
            "sp_shariah",
            evidence(business_description="Provides defense against cyber attacks"),
        )
        desc_rule = next(r for r in result.rule_results if "description" in r.rule_id)
        self.assertNotEqual(desc_rule.outcome, RULE_OUTCOME_FAIL)


class RevenueEvidenceTests(unittest.TestCase):
    def test_revenue_threshold_below_pass(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(
                reported_total_revenue=1_000.0,
                revenue_segments=(
                    BusinessRevenueEvidence(
                        category="no_match",
                        segment_name="Subscription and support",
                        revenue_value=950.0,
                    ),
                    BusinessRevenueEvidence(
                        category="no_match",
                        segment_name="Professional services",
                        revenue_value=50.0,
                    ),
                ),
            ),
        )
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_PASS)
        self.assertEqual(revenue_rule.ratio_pct, 0.0)

    def test_revenue_threshold_below_pass_legacy(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(
                revenue_segments=(
                    BusinessRevenueEvidence(
                        category="non_permissible",
                        segment_name="Non-permissible income",
                        revenue_pct=4.0,
                        source="segment_disclosure",
                        confidence="HIGH",
                    ),
                ),
            ),
        )
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_PASS)

    def test_revenue_threshold_above_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(
                revenue_segments=(
                    BusinessRevenueEvidence(
                        category="non_permissible",
                        segment_name="Non-permissible income",
                        revenue_pct=6.0,
                        source="segment_disclosure",
                        confidence="HIGH",
                    ),
                ),
            ),
        )
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_FAIL)
        self.assertEqual(result.overall_outcome, BUSINESS_SCREEN_OUTCOME_FAIL)

    def test_missing_revenue_value_insufficient(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(
                revenue_segments=(
                    BusinessRevenueEvidence(
                        category="non_permissible",
                        segment_name="Non-permissible income",
                        source="segment_disclosure",
                    ),
                ),
            ),
        )
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_no_inferred_prohibited_revenue_from_description(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(business_description="Operates in alcohol distribution with 8% revenue"),
        )
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)


class NoEvidenceTests(unittest.TestCase):
    def test_empty_evidence_insufficient(self) -> None:
        result = evaluate_business_activity("msci_islamic_index_series", evidence())
        self.assertEqual(result.overall_outcome, BUSINESS_SCREEN_OUTCOME_INSUFFICIENT_DATA)
        self.assertFalse(result.methodology_complete)


class PassSemanticsTests(unittest.TestCase):
    def test_allowed_structured_label_does_not_pass_sector_rule(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(sector="Technology", industry="Software - Application"),
        )
        sector_rule = next(r for r in result.rule_results if "sector" in r.rule_id)
        self.assertEqual(sector_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)
        self.assertNotEqual(result.overall_outcome, BUSINESS_SCREEN_OUTCOME_PASS)


class BroadMappingTests(unittest.TestCase):
    def test_broad_sic_7999_review_not_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(sic_code="7999"),
        )
        sic_rule = next(r for r in result.rule_results if r.evidence_type == EVIDENCE_TYPE_SIC)
        self.assertEqual(sic_rule.outcome, RULE_OUTCOME_REVIEW_REQUIRED)
        self.assertNotEqual(result.overall_outcome, BUSINESS_SCREEN_OUTCOME_FAIL)

    def test_broad_sector_financial_diversified_review_not_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(sector="Financial - Diversified"),
        )
        sector_rule = next(r for r in result.rule_results if "sector" in r.rule_id)
        self.assertEqual(sector_rule.outcome, RULE_OUTCOME_REVIEW_REQUIRED)

    def test_definitive_sic_7990_fail(self) -> None:
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(sic_code="7990"),
        )
        sic_rule = next(r for r in result.rule_results if r.evidence_type == EVIDENCE_TYPE_SIC)
        self.assertEqual(sic_rule.outcome, RULE_OUTCOME_FAIL)


class CombinedAssessmentTests(unittest.TestCase):
    def _financial_inputs(self, **kwargs):
        base = dict(
            symbol="TEST",
            total_debt=30_000_000.0,
            cash=10_000_000.0,
            total_assets=100_000_000.0,
            total_revenue=1_000_000_000.0,
            accounts_receivable=15_000_000.0,
        )
        base.update(kwargs)
        return ParticipationFinancialInputs(**base)

    def test_financial_fail_business_pass_uygun_degil(self) -> None:
        financial = evaluate_financial_rules(
            "msci_islamic_index_series",
            self._financial_inputs(total_debt=50_000_000.0),
        )
        business = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(sector="Technology", industry="Software - Application"),
        )
        assessment = build_combined_methodology_assessment(financial, business)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_financial_pass_business_fail_uygun_degil(self) -> None:
        financial = evaluate_financial_rules(
            "msci_islamic_index_series",
            self._financial_inputs(),
        )
        business = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(industry="Gambling"),
        )
        assessment = build_combined_methodology_assessment(financial, business)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_financial_pass_business_incomplete_kontrol_et(self) -> None:
        financial = evaluate_financial_rules(
            "msci_islamic_index_series",
            self._financial_inputs(),
        )
        business = evaluate_business_activity("msci_islamic_index_series", evidence())
        assessment = build_combined_methodology_assessment(financial, business)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_KONTROL_ET)

    def test_no_final_uygun_for_incomplete_other_methodologies(self) -> None:
        clear_registry_cache_for_tests()
        for methodology_id in (
            "sp_shariah",
            "djim",
            "ftse_yasaar",
            "aaoifi_std21",
        ):
            with self.subTest(methodology_id=methodology_id):
                financial = evaluate_financial_rules(
                    methodology_id,
                    self._financial_inputs(),
                )
                business = evaluate_business_activity(
                    methodology_id,
                    evidence(
                        sector="Technology",
                        industry="Software - Application",
                        revenue_segments=(
                            BusinessRevenueEvidence(
                                category="non_permissible",
                                segment_name="Non-permissible",
                                revenue_pct=1.0,
                                source="segment",
                            ),
                        ),
                    ),
                )
                assessment = build_combined_methodology_assessment(financial, business)
                self.assertNotEqual(assessment.status, PARTICIPATION_STATUS_UYGUN)


class IsolationTests(unittest.TestCase):
    def test_no_provider_imports(self) -> None:
        import services.participation_business_engine as module

        source = inspect.getsource(module)
        for token in (
            "requests",
            "fmp_client",
            "alpha_vantage",
            "scanner_v",
            "nabi_score",
            "decision_engine",
            "streamlit",
            "repository",
        ):
            self.assertNotIn(token, source)


class FreshProcessImportTests(unittest.TestCase):
    def test_fresh_imports(self) -> None:
        script = """
import importlib
for name in (
    "services.participation_business_contract",
    "services.participation_business_engine",
    "services.participation_assessment_service",
):
    importlib.import_module(name)
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
