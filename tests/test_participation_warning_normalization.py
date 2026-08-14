import os
import unittest
from unittest.mock import MagicMock

from components.company_report_ui import render_company_report_participation_section
from services.company_report_participation_service import build_company_report_participation
from services.participation_business_evidence_enrichment import (
    derive_non_permissible_revenue_amount,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
)
from services.participation_message_normalization import (
    merge_warning_messages,
    normalize_warning_messages,
)
from services.research_eligibility_service import (
    evaluate_research_eligibility_from_assessment,
    evaluate_research_eligibility_from_participation_view,
)
from services.sec_financial_client import SECFinancialClient
from tests.test_company_report_participation import sample_sec_financials


CRM_CIK = "1108524"
CRM_SEC_LOOKUP = {
    "CRM": {"symbol": "CRM", "cik": CRM_CIK, "company_name": "Salesforce, Inc."},
}


class ParticipationWarningNormalizationTests(unittest.TestCase):
    def test_none_renders_no_item(self) -> None:
        self.assertEqual(normalize_warning_messages(None), ())

    def test_single_warning_string_renders_one_item(self) -> None:
        message = "Yasaklı gelir segment kanıtı sağlanmadı."
        self.assertEqual(normalize_warning_messages(message), (message,))

    def test_tuple_renders_one_item_per_message(self) -> None:
        messages = ("warning one", "warning two")
        self.assertEqual(normalize_warning_messages(messages), messages)

    def test_duplicate_warnings_deduped_preserving_order(self) -> None:
        merged = merge_warning_messages(
            ("first", "second"),
            ("second", "third"),
        )
        self.assertEqual(merged, ("first", "second", "third"))

    def test_turkish_unicode_preserved(self) -> None:
        message = "Yasaklı gelir segment kanıtı sağlanmadı; MSCI metodolojisi açık gelir atfı gerektirir."
        self.assertEqual(normalize_warning_messages(message), (message,))

    def test_technical_code_string_not_split_into_characters(self) -> None:
        technical = "FMPError"
        normalized = normalize_warning_messages(technical)
        self.assertEqual(normalized, (technical,))
        self.assertNotIn("F", normalized[1:])

    def test_nested_lists_normalized_conservatively(self) -> None:
        nested = ["outer", ("inner one", "inner two")]
        self.assertEqual(
            normalize_warning_messages(nested),
            ("outer", "inner one", "inner two"),
        )

    def test_non_string_values_are_not_stringified(self) -> None:
        self.assertEqual(normalize_warning_messages([123, object()]), ())

    def test_research_status_blocked_reasons_not_split(self) -> None:
        from services.participation_assessment_service import ParticipationAssessmentResult
        from services.participation_intelligence_contract import (
            METHODOLOGY_COMPLETENESS_COMPLETE,
            ParticipationAssessment,
            PARTICIPATION_SOURCE_METHODOLOGY,
        )

        warning = (
            "Yasaklı gelir segment kanıtı sağlanmadı; "
            "MSCI metodolojisi açık gelir atfı gerektirir."
        )
        assessment = ParticipationAssessment(
            symbol="CRM",
            asset_kind="equity",
            status=PARTICIPATION_STATUS_KONTROL_ET,
            source=PARTICIPATION_SOURCE_METHODOLOGY,
            confidence="low",
            methodology_id="msci_islamic_index_series",
            methodology_version="2025-05",
            methodology_label="MSCI Islamic Index Series",
            methodology_completeness=METHODOLOGY_COMPLETENESS_COMPLETE,
        )
        result = ParticipationAssessmentResult(
            symbol="CRM",
            methodology_id="msci_islamic_index_series",
            resolved_methodology_version="2025-05",
            participation_assessment=assessment,
            warnings=warning,
            sec_available=True,
            missing_capabilities=(),
        )
        eligibility = evaluate_research_eligibility_from_assessment(result, symbol="CRM")
        self.assertEqual(eligibility.limitations, (warning,))

    def test_exception_objects_are_not_stringified(self) -> None:
        class SecretError(Exception):
            def __str__(self) -> str:
                return "Bearer sk-live-abc123"

        self.assertEqual(normalize_warning_messages([SecretError()]), ())


class DeriveNonPermissibleRevenueWarningTests(unittest.TestCase):
    def test_missing_segment_evidence_returns_tuple_not_string(self) -> None:
        _, warnings = derive_non_permissible_revenue_amount(
            1_000_000.0,
            (),
        )
        self.assertIsInstance(warnings, tuple)
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("Yasaklı gelir segment kanıtı"))


class CompanyReportWarningRenderRegressionTests(unittest.TestCase):
    def test_crm_production_warnings_are_full_sentences_not_characters(self) -> None:
        email = os.environ.get("SEC_CONTACT_EMAIL", "test@example.com")
        sec = SECFinancialClient(contact_email=email)
        view = build_company_report_participation(
            {
                "symbol": "CRM",
                "company_name": "Salesforce Inc",
                "sector_theme": "Technology",
                "industry": "Software - Application",
                "market_cap": 250_000_000_000,
                "notes": "Salesforce CRM software.",
            },
            sec_client=sec,
            sec_ticker_lookup=CRM_SEC_LOOKUP,
            fmp_client=None,
        )
        self.assertTrue(view.available)
        assert view.result is not None
        for warning in view.warnings:
            self.assertGreater(len(warning), 1, msg=f"character split detected: {warning!r}")

        eligibility = evaluate_research_eligibility_from_participation_view(view)
        for limitation in eligibility.limitations:
            self.assertGreater(len(limitation), 1, msg=f"character split detected: {limitation!r}")

    def test_crm_participation_semantics_unchanged(self) -> None:
        email = os.environ.get("SEC_CONTACT_EMAIL", "test@example.com")
        sec = SECFinancialClient(contact_email=email)
        view = build_company_report_participation(
            {
                "symbol": "CRM",
                "company_name": "Salesforce Inc",
                "sector_theme": "Technology",
                "industry": "Software - Application",
                "market_cap": 250_000_000_000,
                "notes": "Salesforce CRM software.",
            },
            sec_client=sec,
            sec_ticker_lookup=CRM_SEC_LOOKUP,
            fmp_client=None,
        )
        assert view.result is not None
        result = view.result
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(result.methodology_id, "msci_islamic_index_series")
        self.assertEqual(result.resolved_methodology_version, "2025-05")
        self.assertEqual(result.screening_context, "NEW_ENTRY")
        eligibility = evaluate_research_eligibility_from_participation_view(view)
        self.assertFalse(eligibility.research_allowed)

        revenue_rule = next(
            (
                rule
                for rule in result.financial_screen_result.rule_results
                if "revenue" in rule.rule_id or "non_permissible" in rule.rule_id
            ),
            None,
        )
        if revenue_rule is not None:
            self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_aapl_production_path_regression(self) -> None:
        email = os.environ.get("SEC_CONTACT_EMAIL", "test@example.com")
        sec = SECFinancialClient(contact_email=email)
        view = build_company_report_participation(
            {
                "symbol": "AAPL",
                "company_name": "Apple Inc",
                "sector_theme": "Technology",
                "industry": "Consumer Electronics",
                "market_cap": 3_000_000_000_000,
            },
            sec_client=sec,
            sec_ticker_lookup={"AAPL": {"symbol": "AAPL", "cik": "320193"}},
            fmp_client=None,
        )
        assert view.result is not None
        result = view.result
        self.assertEqual(result.resolved_methodology_version, "2025-05")
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)
        eligibility = evaluate_research_eligibility_from_participation_view(view)
        self.assertFalse(eligibility.research_allowed)
        self.assertEqual(result.participation_provider_calls.get("company_intelligence", 0), 0)


class CompanyReportUiWarningRegressionTests(unittest.TestCase):
    def test_ui_module_uses_merge_helper(self) -> None:
        import inspect

        source = inspect.getsource(render_company_report_participation_section)
        self.assertIn("merge_warning_messages", source)
        self.assertNotIn("(*view.warnings, *assessment.warnings)", source)


class MockedCrmFinancialCompletionTests(unittest.TestCase):
    def test_crm_mocked_sec_path_not_zero_of_four(self) -> None:
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
            {
                "symbol": "CRM",
                "company_name": "Salesforce Inc",
                "sector_theme": "Technology",
                "industry": "Software - Application",
            },
            sec_client=client,
            sec_ticker_lookup=CRM_SEC_LOOKUP,
        )
        assert view.result is not None
        completeness = view.result.assessment_completeness
        self.assertIsNotNone(completeness)
        self.assertGreaterEqual(completeness.financial_rules_evaluated, 3)
        self.assertEqual(completeness.financial_rules_total, 4)


if __name__ == "__main__":
    unittest.main()
