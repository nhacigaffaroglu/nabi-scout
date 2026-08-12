import inspect
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from services.participation_assessment_service import (
    BUSINESS_ACTIVITY_UNAVAILABLE_WARNING,
    assess_equity_participation,
)
from services.participation_business_contract import BusinessActivityEvidence
from services.participation_financial_engine import evaluate_financial_rules
from services.participation_intelligence_contract import (
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    PARTICIPATION_SOURCE_CONFIGURED,
    PARTICIPATION_SOURCE_METHODOLOGY,
    PARTICIPATION_SOURCE_UNKNOWN,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
)
from services.participation_intelligence_service import (
    get_participation_assessment_for_fund,
)
from services.participation_methodology_registry import get_default_equity_methodology_id
from services.participation_sec_input_resolver import build_participation_inputs_from_sec
from services.sec_financial_client import SECFinancialError


def sample_sec_financials(**overrides) -> dict:
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


class MockSECClient:
    def __init__(
        self,
        *,
        financials: dict | None = None,
        company_facts_error: Exception | None = None,
        extract_error: Exception | None = None,
    ) -> None:
        self.financials = financials if financials is not None else sample_sec_financials()
        self.company_facts_error = company_facts_error
        self.extract_error = extract_error
        self.company_facts_calls: list[str] = []
        self.extract_calls: list[dict] = []

    def company_facts(self, cik):
        self.company_facts_calls.append(str(cik))
        if self.company_facts_error is not None:
            raise self.company_facts_error
        return {"facts": {"us-gaap": {}}}

    def extract_financials(self, payload):
        self.extract_calls.append(payload)
        if self.extract_error is not None:
            raise self.extract_error
        return dict(self.financials)


class MethodologySelectionTests(unittest.TestCase):
    def test_default_methodology_from_registry(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(),
            cik=320193,
        )
        self.assertEqual(result.methodology_id, get_default_equity_methodology_id())
        self.assertEqual(
            result.methodology_id,
            "msci_islamic_index_series",
        )

    def test_explicit_methodology_selection(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            methodology_id="sp_shariah",
            sec_client=MockSECClient(),
            cik=320193,
        )
        self.assertEqual(result.methodology_id, "sp_shariah")

    def test_unknown_methodology_fail_safe(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            methodology_id="not_real",
            sec_client=MockSECClient(),
            cik=320193,
        )
        self.assertEqual(result.participation_assessment.source, PARTICIPATION_SOURCE_UNKNOWN)
        self.assertTrue(result.errors)
        self.assertIsNone(result.financial_screen_result)


class SecFlowTests(unittest.TestCase):
    def test_sec_client_invoked_with_cik(self) -> None:
        client = MockSECClient()
        assess_equity_participation("AAPL", sec_client=client, cik=320193)
        self.assertEqual(client.company_facts_calls, ["320193"])
        self.assertEqual(len(client.extract_calls), 1)

    @patch("services.participation_assessment_service.build_participation_inputs_from_sec")
    @patch("services.participation_assessment_service.evaluate_financial_rules")
    @patch(
        "services.participation_assessment_service.build_methodology_assessment_from_financial_screen"
    )
    def test_orchestration_uses_resolver_and_engine(
        self,
        mock_build_assessment,
        mock_evaluate,
        mock_resolver,
    ) -> None:
        from services.participation_financial_contract import (
            ParticipationFinancialInputs,
            ParticipationFinancialScreenResult,
        )
        from services.participation_intelligence_contract import ParticipationAssessment

        mock_resolver.return_value = MagicMock(
            inputs=ParticipationFinancialInputs(symbol="AAPL"),
            warnings=(),
            missing_fields=(),
        )
        mock_evaluate.return_value = ParticipationFinancialScreenResult(
            symbol="AAPL",
            methodology_id="msci_islamic_index_series",
            methodology_version="2024-10",
            rule_results=(),
            overall_outcome="INSUFFICIENT_DATA",
        )
        mock_build_assessment.return_value = ParticipationAssessment(
            symbol="AAPL",
            asset_kind="equity",
            status=PARTICIPATION_STATUS_KONTROL_ET,
            source=PARTICIPATION_SOURCE_METHODOLOGY,
            confidence=CONFIDENCE_LOW,
        )

        assess_equity_participation("AAPL", sec_client=MockSECClient(), cik=1)
        mock_resolver.assert_called_once()
        mock_evaluate.assert_called_once()
        mock_build_assessment.assert_called_once()


class MissingSecTests(unittest.TestCase):
    def test_no_cik_safe_result(self) -> None:
        client = MockSECClient()
        result = assess_equity_participation("AAPL", sec_client=client, cik=None)
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(result.participation_assessment.source, PARTICIPATION_SOURCE_UNKNOWN)
        self.assertEqual(result.participation_assessment.confidence, CONFIDENCE_LOW)
        self.assertEqual(client.company_facts_calls, [])

    def test_no_sec_client_safe_result(self) -> None:
        result = assess_equity_participation("AAPL", sec_client=None, cik=320193)
        self.assertEqual(result.participation_assessment.source, PARTICIPATION_SOURCE_UNKNOWN)
        self.assertIsNone(result.financial_screen_result)

    def test_empty_sec_still_evaluates_methodology(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(financials={}),
            cik=320193,
        )
        self.assertEqual(result.participation_assessment.source, PARTICIPATION_SOURCE_METHODOLOGY)
        self.assertIsNotNone(result.financial_screen_result)

    def test_sec_failure_safe_result(self) -> None:
        client = MockSECClient(company_facts_error=SECFinancialError("network"))
        result = assess_equity_participation("AAPL", sec_client=client, cik=320193)
        self.assertFalse(result.sec_available)
        self.assertEqual(result.participation_assessment.source, PARTICIPATION_SOURCE_METHODOLOGY)
        self.assertEqual(result.participation_assessment.confidence, CONFIDENCE_LOW)
        self.assertTrue(result.errors)

    def test_non_usd_safe_result(self) -> None:
        result = assess_equity_participation(
            "TSM",
            sec_client=MockSECClient(
                financials=sample_sec_financials(financial_currency="TWD"),
            ),
            cik=1046179,
        )
        self.assertIsNone(result.financial_inputs.total_debt)
        self.assertEqual(result.participation_assessment.source, PARTICIPATION_SOURCE_METHODOLOGY)


class FinancialOutcomeTests(unittest.TestCase):
    def _assess(self, **sec_overrides):
        return assess_equity_participation(
            "TEST",
            sec_client=MockSECClient(financials=sample_sec_financials(**sec_overrides)),
            cik=1,
        )

    def test_msci_partial_evaluation_kontrol_et(self) -> None:
        result = self._assess()
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertFalse(result.financial_screen_result.methodology_complete)
        self.assertIn(BUSINESS_ACTIVITY_UNAVAILABLE_WARNING, result.warnings)

    def test_high_debt_fail_uygun_degil(self) -> None:
        result = self._assess(total_debt=50_000_000.0, total_assets=100_000_000.0)
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_no_uygun_path(self) -> None:
        for methodology_id in (
            "msci_islamic_index_series",
            "sp_shariah",
            "djim",
            "ftse_yasaar",
            "aaoifi_std21",
        ):
            with self.subTest(methodology_id=methodology_id):
                result = assess_equity_participation(
                    "TEST",
                    methodology_id=methodology_id,
                    sec_client=MockSECClient(),
                    cik=1,
                )
                self.assertNotEqual(
                    result.participation_assessment.status,
                    PARTICIPATION_STATUS_UYGUN,
                )

    def test_sp_missing_36m_denominator(self) -> None:
        result = assess_equity_participation(
            "TEST",
            methodology_id="sp_shariah",
            sec_client=MockSECClient(),
            cik=1,
            market_capitalization=200_000_000_000.0,
        )
        debt_rule = next(
            rule
            for rule in result.financial_screen_result.rule_results
            if "debt_to_avg_equity" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_djim_missing_24m_denominator(self) -> None:
        result = assess_equity_participation(
            "TEST",
            methodology_id="djim",
            sec_client=MockSECClient(),
            cik=1,
            market_capitalization=200_000_000_000.0,
        )
        debt_rule = next(
            rule
            for rule in result.financial_screen_result.rule_results
            if "avg_mcap_24m" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_aaoifi_missing_interest_bearing_debt(self) -> None:
        result = assess_equity_participation(
            "TEST",
            methodology_id="aaoifi_std21",
            sec_client=MockSECClient(),
            cik=1,
            market_capitalization=200_000_000_000.0,
        )
        debt_rule = next(
            rule
            for rule in result.financial_screen_result.rule_results
            if "interest_bearing_debt_to_market_cap" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)


class ProviderBudgetTests(unittest.TestCase):
    def test_single_sec_call_no_retries(self) -> None:
        client = MockSECClient()
        assess_equity_participation("AAPL", sec_client=client, cik=320193)
        self.assertEqual(len(client.company_facts_calls), 1)
        self.assertEqual(len(client.extract_calls), 1)

    def test_provider_status_sec_only(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(),
            cik=320193,
        )
        providers = dict(result.provider_status)
        self.assertEqual(set(providers), {"sec"})
        self.assertEqual(providers["sec"], "ok")
        self.assertNotIn("fmp", providers)
        self.assertNotIn("alpha", providers)

    def test_no_fmp_or_alpha_calls(self) -> None:
        with patch("services.fmp_client.FMPClient") as mock_fmp, patch(
            "services.alpha_vantage_client.AlphaVantageClient"
        ) as mock_alpha:
            assess_equity_participation(
                "AAPL",
                sec_client=MockSECClient(),
                cik=320193,
            )
        mock_fmp.assert_not_called()
        mock_alpha.assert_not_called()

    def test_no_db_reads_or_writes(self) -> None:
        import sqlite3

        connect = MagicMock(wraps=sqlite3.connect)
        with patch("sqlite3.connect", connect):
            assess_equity_participation(
                "AAPL",
                sec_client=MockSECClient(),
                cik=320193,
            )
        connect.assert_not_called()


class SmokeMatrixTests(unittest.TestCase):
    def test_fixture_a_strong_sec_partial_msci_kontrol_et(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(financials=sample_sec_financials()),
            cik=320193,
        )
        self.assertTrue(result.financial_screen_result.financial_rules_evaluated)
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)

    def test_fixture_b_high_debt_uygun_degil(self) -> None:
        result = assess_equity_participation(
            "LEVER",
            sec_client=MockSECClient(
                financials=sample_sec_financials(
                    total_debt=50_000_000.0,
                    total_assets=100_000_000.0,
                ),
            ),
            cik=1,
        )
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_fixture_c_sp_no_36m_denominator(self) -> None:
        result = assess_equity_participation(
            "TEST",
            methodology_id="sp_shariah",
            sec_client=MockSECClient(),
            cik=1,
            market_capitalization=200_000_000_000.0,
        )
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        debt_rule = next(
            rule
            for rule in result.financial_screen_result.rule_results
            if "debt_to_avg_equity" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_fixture_d_no_cik(self) -> None:
        client = MockSECClient()
        result = assess_equity_participation("AAPL", sec_client=client, cik=None)
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(result.participation_assessment.confidence, CONFIDENCE_LOW)
        self.assertEqual(client.company_facts_calls, [])

    def test_fixture_e_sec_failure_no_fallback(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(company_facts_error=SECFinancialError("timeout")),
            cik=320193,
        )
        self.assertFalse(result.sec_available)
        self.assertEqual(dict(result.provider_status)["sec"], "error")
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)


class ConfidenceAndEvidenceTests(unittest.TestCase):
    def test_confidence_low_without_sec(self) -> None:
        result = assess_equity_participation("AAPL", sec_client=None, cik=1)
        self.assertEqual(result.participation_assessment.confidence, CONFIDENCE_LOW)

    def test_confidence_medium_with_meaningful_financial_evaluation(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(),
            cik=1,
        )
        self.assertEqual(result.participation_assessment.confidence, CONFIDENCE_MEDIUM)

    def test_market_cap_preserved_without_historical_substitution(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(),
            cik=1,
            market_capitalization=123_456.0,
        )
        self.assertEqual(result.used_market_capitalization, 123_456.0)
        self.assertEqual(result.financial_inputs.market_capitalization, 123_456.0)
        self.assertIsNone(result.financial_inputs.average_market_cap_24m)
        self.assertIsNone(result.financial_inputs.average_market_value_of_equity_36m)

    def test_source_evidence_preserved(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(),
            cik=320193,
        )
        evidence = dict(result.source_evidence)
        self.assertEqual(evidence["provider"], "SEC")
        self.assertEqual(evidence["cik"], "320193")

    def test_confidence_not_from_participation_score(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(),
            cik=1,
        )
        assessment_dict = result.participation_assessment.to_dict()
        self.assertNotIn("participation_score", assessment_dict)
        self.assertEqual(result.participation_assessment.confidence, CONFIDENCE_MEDIUM)


class IsolationTests(unittest.TestCase):
    def test_configured_fund_factory_unchanged(self) -> None:
        result = get_participation_assessment_for_fund("SPUS")
        self.assertEqual(result.source, PARTICIPATION_SOURCE_CONFIGURED)

    def test_assess_equity_does_not_use_configured_catalog_for_spus(self) -> None:
        result = assess_equity_participation(
            "SPUS",
            sec_client=MockSECClient(),
            cik=1,
        )
        self.assertEqual(result.participation_assessment.source, PARTICIPATION_SOURCE_METHODOLOGY)

    def test_no_scanner_or_scoring_imports(self) -> None:
        import services.participation_assessment_service as module

        source = inspect.getsource(module)
        for token in (
            "scanner_v",
            "nabi_score_v4",
            "decision_engine",
            "alpha_vantage",
            "fmp",
            "repository",
            "streamlit",
        ):
            self.assertNotIn(token, source)

    def test_score_firewall_still_holds(self) -> None:
        from services.nabi_score_v4 import calculate_nabi_score_v4

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
        scores = {
            calculate_nabi_score_v4(
                **kwargs,
                participation_score=score,
                participation_status=status,
            )["nabi_score"]
            for score in (0, 60, 100)
            for status in ("Uygun", "Kontrol Et", "Uygun Değil")
        }
        self.assertEqual(len(scores), 1)


class FreshProcessImportTests(unittest.TestCase):
    def test_fresh_imports(self) -> None:
        script = """
import importlib
for name in (
    "services.participation_assessment_service",
    "services.participation_sec_input_resolver",
    "services.participation_financial_engine",
    "services.participation_intelligence_service",
    "services.sec_financial_client",
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


class BusinessCompositionTests(unittest.TestCase):
    def test_business_evidence_composed_without_new_providers(self) -> None:
        client = MockSECClient()
        result = assess_equity_participation(
            "AAPL",
            sec_client=client,
            cik=1,
            business_evidence=BusinessActivityEvidence(
                symbol="AAPL",
                industry="Gambling",
                source="fixture",
            ),
        )
        self.assertIsNotNone(result.business_screen_result)
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)
        self.assertEqual(len(client.company_facts_calls), 1)

    def test_no_business_evidence_keeps_unavailable_warning(self) -> None:
        result = assess_equity_participation(
            "AAPL",
            sec_client=MockSECClient(),
            cik=1,
        )
        self.assertIsNone(result.business_screen_result)
        self.assertIn(BUSINESS_ACTIVITY_UNAVAILABLE_WARNING, result.warnings)


if __name__ == "__main__":
    unittest.main()
