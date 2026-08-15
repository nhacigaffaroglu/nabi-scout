import inspect
import unittest
from unittest.mock import MagicMock, patch

from components.company_report_ui import render_company_report_participation_section
from services.company_report_participation_service import (
    CompanyReportParticipationView,
    build_company_report_participation,
    participation_status_is_final_uygun,
)
from services.participation_business_evidence_resolver import (
    build_business_activity_evidence_from_candidate,
)
from services.participation_assessment_service import ParticipationAssessmentResult
from services.participation_completeness import ParticipationAssessmentCompleteness
from services.participation_intelligence_contract import (
    METHODOLOGY_COMPLETENESS_COMPLETE,
    PARTICIPATION_SOURCE_METHODOLOGY,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    ParticipationAssessment,
)
from services.participation_screening_context import (
    SCREENING_CONTEXT_NEW_ENTRY,
    screening_context_label_tr,
)
from services.sec_financial_client import SECFinancialError


def sample_candidate(**overrides):
    base = {
        "symbol": "AAPL",
        "company_name": "Apple Inc.",
        "sector_theme": "Technology",
        "notes": "Designs consumer electronics.",
        "cik": 320193,
        "market_cap": 3_000_000_000_000,
        "data_source": "SEC Company Facts + FMP",
        "source_updated_at": "2026-08-01",
    }
    base.update(overrides)
    return base


def sample_sec_financials(**overrides):
    base = {
        "total_debt": 30_000_000.0,
        "cash": 10_000_000.0,
        "total_assets": 100_000_000.0,
        "revenue": 1_000_000_000.0,
        "accounts_receivable": 15_000_000.0,
        "financial_period_end": "2025-12-31",
        "annual_periods_found": 3,
        "financial_currency": "USD",
        "financial_taxonomy": "us-gaap",
    }
    base.update(overrides)
    return base


class BusinessEvidenceResolverTests(unittest.TestCase):
    def test_maps_existing_candidate_fields(self) -> None:
        evidence = build_business_activity_evidence_from_candidate(sample_candidate())
        self.assertEqual(evidence.symbol, "AAPL")
        self.assertEqual(evidence.company_name, "Apple Inc.")
        self.assertEqual(evidence.sector, "Technology")
        self.assertEqual(evidence.business_description, "Designs consumer electronics.")
        self.assertEqual(evidence.source, "candidate_record:SEC Company Facts + FMP")
        self.assertIn(("sector_theme", "Technology"), evidence.evidence_refs)

    def test_missing_fields_remain_missing(self) -> None:
        evidence = build_business_activity_evidence_from_candidate({"symbol": "X"})
        self.assertIsNone(evidence.sic_code)
        self.assertIsNone(evidence.business_description)
        self.assertEqual(evidence.revenue_segments, ())

    def test_no_fabricated_sic_or_revenue(self) -> None:
        evidence = build_business_activity_evidence_from_candidate(
            sample_candidate(sector_theme="Gambling")
        )
        self.assertIsNone(evidence.sic_code)
        self.assertEqual(evidence.revenue_segments, ())

    def test_industry_used_when_sector_missing(self) -> None:
        evidence = build_business_activity_evidence_from_candidate(
            {"symbol": "X", "industry": "Software - Application"}
        )
        self.assertEqual(evidence.sector, "Software - Application")


class CompanyReportParticipationServiceTests(unittest.TestCase):
    def test_graceful_without_cik(self) -> None:
        view = build_company_report_participation(
            sample_candidate(cik=None),
            sec_client=MagicMock(),
        )
        self.assertTrue(view.available)
        self.assertIsNotNone(view.result)
        self.assertEqual(
            view.result.participation_assessment.status,
            PARTICIPATION_STATUS_KONTROL_ET,
        )

    def test_sec_failure_does_not_break_view(self) -> None:
        client = MagicMock()
        client.company_facts.side_effect = SECFinancialError("network")
        view = build_company_report_participation(
            sample_candidate(),
            sec_client=client,
        )
        self.assertTrue(view.available)
        self.assertEqual(
            view.result.participation_assessment.status,
            PARTICIPATION_STATUS_KONTROL_ET,
        )

    def test_definitive_fail_display(self) -> None:
        view = build_company_report_participation(
            sample_candidate(sector_theme="Gambling"),
            sec_client=MagicMock(),
            sec_financials=sample_sec_financials(),
        )
        self.assertEqual(
            view.result.participation_assessment.status,
            PARTICIPATION_STATUS_UYGUN_DEGIL,
        )

    def test_incomplete_kontrol_et(self) -> None:
        view = build_company_report_participation(
            sample_candidate(),
            sec_client=MagicMock(),
            sec_financials=sample_sec_financials(),
        )
        self.assertEqual(
            view.result.participation_assessment.status,
            PARTICIPATION_STATUS_KONTROL_ET,
        )

    def test_no_final_uygun(self) -> None:
        view = build_company_report_participation(
            sample_candidate(),
            sec_client=MagicMock(),
            sec_financials=sample_sec_financials(),
        )
        self.assertFalse(participation_status_is_final_uygun(view))
        self.assertNotEqual(
            view.result.participation_assessment.status,
            PARTICIPATION_STATUS_UYGUN,
        )

    def test_provided_sec_financials_skip_fetch(self) -> None:
        client = MagicMock()
        build_company_report_participation(
            sample_candidate(),
            sec_client=client,
            sec_financials=sample_sec_financials(),
        )
        client.company_facts.assert_not_called()

    def test_no_legacy_participation_score_in_view(self) -> None:
        view = build_company_report_participation(
            sample_candidate(participation_score=99, participation_status="Uygun"),
            sec_client=MagicMock(),
            sec_financials=sample_sec_financials(),
        )
        payload = view.to_dict()
        self.assertNotIn("participation_score", payload)


class DependencyFirewallTests(unittest.TestCase):
    def test_resolver_has_no_provider_imports(self) -> None:
        import services.participation_business_evidence_resolver as module

        source = inspect.getsource(module)
        for token in ("scanner_v", "nabi_score", "decision_engine", "streamlit"):
            self.assertNotIn(token, source)

    def test_company_report_service_uses_orchestration(self) -> None:
        import services.company_report_participation_service as module

        source = inspect.getsource(module)
        self.assertIn("assess_equity_participation", source)
        self.assertNotIn("evaluate_financial_rules", source)


class CompanyReportParticipationUiRenderTests(unittest.TestCase):
    def test_imports_screening_context_label_helper(self) -> None:
        with open("components/company_report_ui.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn(
            "from services.participation_screening_context import screening_context_label_tr",
            source,
        )

    def test_technical_details_expander_renders_screening_context_label(self) -> None:
        assessment = ParticipationAssessment(
            symbol="CRM",
            asset_kind="equity",
            status=PARTICIPATION_STATUS_UYGUN,
            source=PARTICIPATION_SOURCE_METHODOLOGY,
            confidence="medium",
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
            assessment_completeness=ParticipationAssessmentCompleteness(
                financial_rules_total=4,
                financial_rules_evaluated=4,
                business_rules_total=4,
                business_rules_evaluated=4,
                methodology_complete=True,
                assessment_complete=True,
                financial_methodology_complete=True,
                business_methodology_complete=True,
            ),
            participation_provider_calls={"sec_inline_xbrl": 1},
            screening_context=SCREENING_CONTEXT_NEW_ENTRY,
            missing_capabilities=(),
        )
        view = CompanyReportParticipationView(
            symbol="CRM",
            available=True,
            result=result,
            financial_screen_summary="Genel sonuç: Geçti · 4/4 kural",
            business_screen_summary="Genel sonuç: Geçti · 4/4 kural",
        )

        mock_st = MagicMock()
        mock_st.columns.return_value = (MagicMock(), MagicMock())
        expander = MagicMock()
        expander.__enter__ = MagicMock(return_value=MagicMock())
        expander.__exit__ = MagicMock(return_value=False)
        mock_st.expander.return_value = expander
        mock_st.button.return_value = False

        with patch("components.company_report_ui.st", mock_st):
            render_company_report_participation_section(view)

        expected_label = screening_context_label_tr(SCREENING_CONTEXT_NEW_ENTRY)
        caption_calls = [str(call.args[0]) for call in mock_st.caption.call_args_list]
        self.assertTrue(
            any("Tarama bağlamı:" in text and expected_label in text for text in caption_calls),
            msg=f"expected screening context caption with {expected_label!r}, got {caption_calls}",
        )


class CompanyReportPageTests(unittest.TestCase):
    def test_participation_section_present(self) -> None:
        with open("pages/4_Company_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        with open("components/company_report_ui.py", encoding="utf-8") as handle:
            ui_source = handle.read()
        self.assertIn("render_company_report_participation_section", source)
        self.assertIn("build_company_report_participation", source)
        self.assertIn("Katılım İncelemesi", ui_source)
        self.assertIn("Katılım incelemesini kaydet", ui_source)
        self.assertNotIn("participation_score", source)

    def test_company_report_sec_client_uses_configured_contact_email(self) -> None:
        with open("pages/4_Company_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("SECFinancialClient()", source)
        self.assertIn("get_sec_contact_email()", source)
        self.assertIn("SECFinancialClient(contact_email=", source)
        self.assertIn("sec_ticker_lookup=", source)

    def test_participation_after_decision_not_in_nabi_metrics(self) -> None:
        with open("pages/4_Company_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        nabi_index = source.index('c1.metric("NABI Skoru"')
        participation_index = source.index("participation_view = build_company_report_participation")
        decision_index = source.index('st.subheader("Karar özeti")')
        self.assertLess(nabi_index, decision_index)
        self.assertLess(decision_index, participation_index)


if __name__ == "__main__":
    unittest.main()
