import inspect
import subprocess
import sys
import unittest
from datetime import date

from config.participation_catalog import (
    CONFIGURED_PARTICIPATION_CATALOG,
    CATALOG_NAME,
)
from config.scan_universe import PARTICIPATION_DEFAULTS
from services.fund_analysis_contract import FundAnalysisResult
from services.fund_analysis_service import analyze_fund
from services.nabi_score_v4 import calculate_nabi_score_v4
from services.participation_intelligence_contract import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    PARTICIPATION_DISCLAIMER_FULL,
    PARTICIPATION_SOURCE_CONFIGURED,
    PARTICIPATION_SOURCE_METHODOLOGY,
    PARTICIPATION_SOURCE_UNKNOWN,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    RULE_OUTCOME_PASS,
    ParticipationAssessment,
    ParticipationRuleResult,
)
from services.participation_intelligence_service import (
    build_configured_assessment,
    build_unknown_assessment,
    get_participation_assessment_for_fund,
)
from services.participation_methodology_registry import (
    get_default_equity_methodology,
    get_default_equity_methodology_id,
    get_methodology,
    list_methodologies,
)


class ParticipationContractTests(unittest.TestCase):
    def test_assessment_is_frozen(self) -> None:
        assessment = build_configured_assessment("SPUS")
        with self.assertRaises(Exception):
            assessment.status = "X"  # type: ignore[misc]

    def test_rule_result_is_frozen(self) -> None:
        rule = ParticipationRuleResult(rule_id="test.rule", outcome="PASS")
        with self.assertRaises(Exception):
            rule.outcome = "FAIL"  # type: ignore[misc]

    def test_assessment_to_dict_excludes_numeric_participation_score(self) -> None:
        payload = build_configured_assessment("SPUS").to_dict()
        self.assertNotIn("participation_score", payload)
        self.assertNotIn("score", payload)

    def test_status_confidence_completeness_are_separate_fields(self) -> None:
        assessment = build_unknown_assessment("QQQ")
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(assessment.confidence, CONFIDENCE_LOW)
        self.assertIsNone(assessment.data_completeness_pct)

    def test_configured_helpers(self) -> None:
        assessment = build_configured_assessment("HLAL")
        self.assertTrue(assessment.is_configured_only())
        self.assertFalse(assessment.has_methodology_result())
        self.assertFalse(assessment.requires_review())


class MethodologyRegistryTests(unittest.TestCase):
    def test_methodology_ids_unique(self) -> None:
        ids = [item.methodology_id for item in list_methodologies()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_versions_present(self) -> None:
        for item in list_methodologies():
            self.assertTrue(item.version)

    def test_unknown_methodology_returns_none(self) -> None:
        self.assertIsNone(get_methodology("not_a_real_methodology"))

    def test_default_equity_methodology_is_msci(self) -> None:
        self.assertEqual(get_default_equity_methodology_id(), "msci_islamic_index_series")
        default = get_default_equity_methodology()
        self.assertEqual(default.methodology_id, "msci_islamic_index_series")

    def test_denominator_policies_are_not_normalized(self) -> None:
        msci = get_methodology("msci_islamic_index_series")
        sp = get_methodology("sp_shariah")
        djim = get_methodology("djim")
        ftse = get_methodology("ftse_yasaar")
        aaoifi = get_methodology("aaoifi_std21")
        assert msci and sp and djim and ftse and aaoifi
        self.assertNotEqual(msci.denominator_policy, sp.denominator_policy)
        self.assertNotEqual(sp.denominator_policy, djim.denominator_policy)
        self.assertNotEqual(aaoifi.denominator_policy, msci.denominator_policy)
        self.assertEqual(msci.denominator_policy, ftse.denominator_policy)
        policies = {
            msci.denominator_policy,
            sp.denominator_policy,
            djim.denominator_policy,
            ftse.denominator_policy,
            aaoifi.denominator_policy,
        }
        self.assertGreaterEqual(len(policies), 4)

    def test_no_global_thirty_three_constant_in_registry_module(self) -> None:
        import services.participation_methodology_registry as registry_module

        source = inspect.getsource(registry_module)
        self.assertNotIn("GLOBAL_THRESHOLD", source)
        self.assertNotIn("UNIVERSAL_THRESHOLD", source)

    def test_msci_and_sp_receivable_thresholds_differ(self) -> None:
        msci = get_methodology("msci_islamic_index_series")
        sp = get_methodology("sp_shariah")
        assert msci and sp
        msci_recv = next(
            rule for rule in msci.rules if "receivables" in rule.rule_id
        )
        sp_recv = next(rule for rule in sp.rules if "receivables" in rule.rule_id)
        self.assertNotEqual(msci_recv.threshold_pct, sp_recv.threshold_pct)


class ConfiguredFactoryTests(unittest.TestCase):
    def test_spus_configured_assessment(self) -> None:
        assessment = build_configured_assessment("SPUS")
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(assessment.source, PARTICIPATION_SOURCE_CONFIGURED)
        self.assertEqual(assessment.confidence, CONFIDENCE_HIGH)
        self.assertIsNone(assessment.methodology_id)
        self.assertIn(PARTICIPATION_DISCLAIMER_FULL, assessment.disclaimer)
        self.assertEqual(assessment.evidence["catalog"], CATALOG_NAME)

    def test_configured_is_not_methodology(self) -> None:
        assessment = build_configured_assessment("SPSK")
        self.assertNotEqual(assessment.source, PARTICIPATION_SOURCE_METHODOLOGY)
        self.assertFalse(assessment.has_methodology_result())

    def test_configured_has_no_pass_rule_results(self) -> None:
        assessment = build_configured_assessment("HLAL")
        self.assertEqual(assessment.financial_screens, ())
        self.assertIsNone(assessment.business_activity)

    def test_unknown_assessment(self) -> None:
        assessment = build_unknown_assessment("QQQ")
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(assessment.source, PARTICIPATION_SOURCE_UNKNOWN)
        self.assertEqual(assessment.confidence, CONFIDENCE_LOW)
        self.assertIn("Bağımsız katılım taraması", assessment.warnings[0])


class ParticipationCatalogTransitionTests(unittest.TestCase):
    def test_scan_universe_reexports_catalog(self) -> None:
        self.assertIs(PARTICIPATION_DEFAULTS, CONFIGURED_PARTICIPATION_CATALOG)


class FundAnalysisIntegrationTests(unittest.TestCase):
    def _analyze(self, symbol: str) -> FundAnalysisResult:
        from tests.test_fund_analysis import (
            make_alpha_client,
            resolved_etf,
            sample_alpha_etf_profile,
        )

        client = make_alpha_client(profile=sample_alpha_etf_profile(symbol))
        return analyze_fund(resolved_etf(symbol), alpha_vantage_client=client)

    def test_spus_legacy_and_assessment(self) -> None:
        result = self._analyze("SPUS")
        self.assertEqual(result.participation_status, "Uygun")
        self.assertEqual(result.participation_score, 100)
        self.assertEqual(result.participation_source, PARTICIPATION_SOURCE_CONFIGURED)
        self.assertIsNotNone(result.participation_assessment)
        assert result.participation_assessment is not None
        self.assertEqual(result.participation_assessment.source, "configured")

    def test_hlal_configured(self) -> None:
        result = self._analyze("HLAL")
        self.assertEqual(result.participation_status, "Uygun")
        assert result.participation_assessment is not None
        self.assertTrue(result.participation_assessment.is_configured_only())

    def test_spsk_configured_without_equity_methodology(self) -> None:
        result = self._analyze("SPSK")
        assert result.participation_assessment is not None
        self.assertEqual(result.participation_assessment.source, "configured")
        self.assertFalse(result.participation_assessment.has_methodology_result())

    def test_qqq_unknown_assessment(self) -> None:
        result = self._analyze("QQQ")
        self.assertEqual(result.participation_status, "Kontrol Et")
        self.assertIsNone(result.participation_source)
        assert result.participation_assessment is not None
        self.assertEqual(result.participation_assessment.source, "unknown")


class FundReportDisplayTests(unittest.TestCase):
    def test_fund_report_ui_prefers_assessment_rendering(self) -> None:
        with open("components/fund_report_ui.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("render_participation_assessment", source)
        self.assertIn("Bağımsız metodoloji taraması", source)
        self.assertIn("Katılım bilgisi: Yapılandırılmış", source)

    def test_fund_report_ui_does_not_show_score_in_primary_assessment(self) -> None:
        with open("components/fund_report_ui.py", encoding="utf-8") as handle:
            source = handle.read()
        assessment_block = source.split("def render_participation_assessment")[1].split(
            "def format_tracked_participation_label"
        )[0]
        self.assertNotIn("participation_score", assessment_block)


class DependencyFirewallTests(unittest.TestCase):
    def test_nabi_score_v4_does_not_import_participation_intelligence(self) -> None:
        import services.nabi_score_v4 as module

        source = inspect.getsource(module)
        self.assertNotIn("participation_intelligence", source)

    def test_decision_engine_does_not_import_participation_intelligence(self) -> None:
        import services.decision_engine as module

        source = inspect.getsource(module)
        self.assertNotIn("participation_intelligence", source)

    def test_participation_service_does_not_import_scoring(self) -> None:
        import services.participation_intelligence_service as module

        source = inspect.getsource(module)
        self.assertNotIn("nabi_score_v4", source)
        self.assertNotIn("decision_engine", source)
        self.assertNotIn("scanner_v8", source)

    def test_score_firewall_still_holds(self) -> None:
        kwargs = dict(
            revenue_growth_1y=18.0,
            revenue_cagr_3y=16.0,
            eps_growth_1y=20.0,
            eps_cagr_3y=18.0,
            fcf_cagr_3y=15.0,
            gross_margin=55.0,
            operating_margin=28.0,
            net_margin=22.0,
            fcf_margin=20.0,
            roic=22.0,
            roe=24.0,
            roa=12.0,
            current_ratio=1.8,
            debt_to_equity=0.4,
            net_debt_to_fcf=1.5,
            interest_coverage=12.0,
            pe_ratio=18.0,
            price_to_sales=4.0,
            price_to_book=3.0,
            share_change_3y=-2.0,
            payout_ratio=25.0,
            market_cap=50_000_000_000,
            average_volume=5_000_000,
            portfolio_fit=70.0,
            completeness=90.0,
        )
        scores = [
            calculate_nabi_score_v4(
                **kwargs,
                participation_score=score,
                participation_status=status,
            )["nabi_score"]
            for score in (0, 60, 100)
            for status in ("Uygun", "Kontrol Et", "Uygun Değil")
        ]
        self.assertEqual(len(set(scores)), 1)


class FreshProcessImportTests(unittest.TestCase):
    def test_fresh_imports(self) -> None:
        script = """
import importlib
import py_compile

for name in (
    "services.participation_intelligence_contract",
    "services.participation_methodology_registry",
    "services.participation_intelligence_service",
    "services.fund_analysis_service",
    "services.fund_report_service",
    "components.fund_report_ui",
):
    importlib.import_module(name)

py_compile.compile("pages/9_Fund_Report.py", doraise=True)
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


class GetParticipationAssessmentForFundTests(unittest.TestCase):
    def test_factory_dispatch(self) -> None:
        configured = get_participation_assessment_for_fund("SPUS", as_of_date=date(2026, 1, 1))
        unknown = get_participation_assessment_for_fund("QQQ", as_of_date=date(2026, 1, 1))
        self.assertEqual(configured.source, PARTICIPATION_SOURCE_CONFIGURED)
        self.assertEqual(unknown.source, PARTICIPATION_SOURCE_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
