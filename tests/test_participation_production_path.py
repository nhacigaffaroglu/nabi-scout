import os
import unittest
from unittest.mock import MagicMock

from services.company_report_participation_service import build_company_report_participation
from services.participation_cik_resolver import (
    is_usable_cik,
    normalize_resolved_cik,
    resolve_participation_cik,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
)
from services.research_eligibility_service import evaluate_research_eligibility_from_participation_view
from services.sec_financial_client import SECFinancialClient, SECFinancialError
from tests.test_company_report_participation import sample_sec_financials


CRM_CIK = "1108524"
CRM_SEC_LOOKUP = {
    "CRM": {"symbol": "CRM", "cik": CRM_CIK, "company_name": "Salesforce, Inc."},
}


def crm_candidate(**overrides):
    base = {
        "symbol": "CRM",
        "company_name": "Salesforce Inc",
        "sector_theme": "Technology",
        "industry": "Software - Application",
        "market_cap": 250_000_000_000,
        "notes": (
            "Salesforce, Inc. provides customer relationship management "
            "technology that brings companies and customers together."
        ),
    }
    base.update(overrides)
    return base


class ParticipationCikResolverTests(unittest.TestCase):
    def test_rejects_empty_and_zero_cik(self) -> None:
        self.assertFalse(is_usable_cik(None))
        self.assertFalse(is_usable_cik(""))
        self.assertFalse(is_usable_cik("0"))
        self.assertFalse(is_usable_cik("0000000000"))
        self.assertTrue(is_usable_cik("1108524"))
        self.assertEqual(normalize_resolved_cik("0001108524"), "1108524")

    def test_fmp_fallback_when_candidate_cik_missing(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {"cik": "0001108524"}
        resolution = resolve_participation_cik(
            "CRM",
            fmp_client=fmp,
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        self.assertEqual(resolution.cik, CRM_CIK)
        self.assertEqual(resolution.source, "fmp_profile")

    def test_sec_lookup_fallback_when_fmp_unavailable(self) -> None:
        resolution = resolve_participation_cik(
            "CRM",
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        self.assertEqual(resolution.cik, CRM_CIK)
        self.assertEqual(resolution.source, "sec_ticker_lookup")


class CompanyReportProductionPathTests(unittest.TestCase):
    def test_missing_candidate_cik_resolves_via_sec_lookup(self) -> None:
        client = MagicMock()
        client.company_facts.return_value = {"facts": {"us-gaap": {}}}
        client.extract_financials.return_value = sample_sec_financials(
            interest_bearing_securities=5_000_000.0,
        )
        client.resolve_entity_metadata.return_value = (
            {"sic_code": "7372", "sic_description": "Services-Prepackaged Software"},
            (("sic_source", "sec_submissions"),),
        )

        view = build_company_report_participation(
            crm_candidate(),
            sec_client=client,
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        result = view.result
        self.assertIsNotNone(result)
        assert result is not None
        client.company_facts.assert_called_once_with(CRM_CIK)
        self.assertTrue(result.sec_available)
        self.assertGreater(result.assessment_completeness.financial_rules_evaluated, 0)

    def test_invalid_candidate_cik_does_not_block_sec_lookup(self) -> None:
        client = MagicMock()
        client.company_facts.return_value = {"facts": {"us-gaap": {}}}
        client.extract_financials.return_value = sample_sec_financials(
            interest_bearing_securities=5_000_000.0,
        )
        client.resolve_entity_metadata.return_value = (
            {"sic_code": "7372"},
            (("sic_source", "sec_submissions"),),
        )

        view = build_company_report_participation(
            crm_candidate(cik="0"),
            sec_client=client,
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        result = view.result
        self.assertIsNotNone(result)
        assert result is not None
        client.company_facts.assert_called_once_with(CRM_CIK)
        self.assertNotEqual(result.assessment_completeness.financial_rules_evaluated, 0)

    def test_sec_error_yields_zero_financial_rules_evaluated(self) -> None:
        client = MagicMock()
        client.company_facts.side_effect = SECFinancialError("network")

        view = build_company_report_participation(
            crm_candidate(cik=CRM_CIK),
            sec_client=client,
        )
        result = view.result
        self.assertIsNotNone(result)
        assert result is not None
        completeness = result.assessment_completeness
        self.assertEqual(completeness.financial_rules_evaluated, 0)
        self.assertEqual(completeness.financial_rules_total, 4)
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_PARTICIPATION_TESTS") == "1",
    "Set RUN_LIVE_PARTICIPATION_TESTS=1 for live SEC/FMP integration",
)
class LiveCompanyReportProductionPathTests(unittest.TestCase):
    def setUp(self) -> None:
        email = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
        if not email:
            self.skipTest("SEC_CONTACT_EMAIL required for live participation tests")
        self.sec_client = SECFinancialClient(contact_email=email)

    def test_crm_resolves_cik_without_candidate_field(self) -> None:
        view = build_company_report_participation(
            crm_candidate(),
            sec_client=self.sec_client,
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        result = view.result
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.sec_available)
        self.assertGreaterEqual(
            result.assessment_completeness.financial_rules_evaluated,
            3,
        )
        for rule in result.financial_screen_result.rule_results[:3]:
            self.assertIn(rule.outcome, {RULE_OUTCOME_PASS, RULE_OUTCOME_INSUFFICIENT_DATA})

    def test_crm_positive_path_when_evidence_supports(self) -> None:
        view = build_company_report_participation(
            crm_candidate(cik=CRM_CIK),
            sec_client=self.sec_client,
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        result = view.result
        self.assertIsNotNone(result)
        assert result is not None
        eligibility = evaluate_research_eligibility_from_participation_view(view)
        if result.participation_assessment.status == PARTICIPATION_STATUS_UYGUN:
            self.assertTrue(eligibility.research_allowed)
            self.assertEqual(result.assessment_completeness.financial_rules_evaluated, 4)
        else:
            self.assertFalse(eligibility.research_allowed)


if __name__ == "__main__":
    unittest.main()
