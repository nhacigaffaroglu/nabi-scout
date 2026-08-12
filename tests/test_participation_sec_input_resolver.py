import inspect
import subprocess
import sys
import unittest
from datetime import date

from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_financial_engine import evaluate_financial_rules
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
)
from services.participation_intelligence_service import (
    build_methodology_assessment_from_financial_screen,
)
from services.participation_sec_input_resolver import (
    PARTICIPATION_INPUT_SOURCE_SEC,
    ParticipationInputResolutionResult,
    build_participation_inputs_from_sec,
)
from services.sec_financial_client import SECFinancialClient


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


class ResolverContractTests(unittest.TestCase):
    def test_resolution_result_is_immutable(self) -> None:
        result = build_participation_inputs_from_sec("AAPL", sample_sec_financials())
        with self.assertRaises(Exception):
            result.source = "X"  # type: ignore[misc]

    def test_inputs_are_immutable(self) -> None:
        result = build_participation_inputs_from_sec("AAPL", sample_sec_financials())
        with self.assertRaises(Exception):
            result.inputs.total_debt = 1.0  # type: ignore[misc]


class SecMappingTests(unittest.TestCase):
    def test_maps_total_debt_cash_assets_revenue(self) -> None:
        result = build_participation_inputs_from_sec("AAPL", sample_sec_financials())
        inputs = result.inputs
        self.assertEqual(inputs.symbol, "AAPL")
        self.assertEqual(inputs.total_debt, 30_000_000.0)
        self.assertEqual(inputs.cash, 10_000_000.0)
        self.assertEqual(inputs.total_assets, 100_000_000.0)
        self.assertEqual(inputs.total_revenue, 1_000_000_000.0)
        self.assertEqual(inputs.accounts_receivable, 15_000_000.0)
        self.assertEqual(inputs.as_of_date, date(2025, 12, 31))

    def test_market_cap_from_caller_only(self) -> None:
        result = build_participation_inputs_from_sec(
            "AAPL",
            sample_sec_financials(),
            market_capitalization=250_000_000_000.0,
        )
        self.assertEqual(result.inputs.market_capitalization, 250_000_000_000.0)
        self.assertIsNone(result.inputs.average_market_cap_24m)
        self.assertIsNone(result.inputs.average_market_value_of_equity_36m)

    def test_no_total_debt_to_interest_bearing_debt_substitution(self) -> None:
        result = build_participation_inputs_from_sec("AAPL", sample_sec_financials())
        self.assertIsNone(result.inputs.interest_bearing_debt)

    def test_no_cash_to_interest_bearing_securities_substitution(self) -> None:
        result = build_participation_inputs_from_sec("AAPL", sample_sec_financials())
        self.assertIsNone(result.inputs.cash_and_interest_bearing_securities)
        self.assertIsNone(result.inputs.cash_plus_interest_bearing_securities)
        self.assertIsNone(result.inputs.interest_taking_deposits)

    def test_missing_receivables_stays_none(self) -> None:
        result = build_participation_inputs_from_sec(
            "AAPL",
            sample_sec_financials(accounts_receivable=None),
        )
        self.assertIsNone(result.inputs.accounts_receivable)

    def test_missing_prohibited_revenue_stays_none(self) -> None:
        result = build_participation_inputs_from_sec("AAPL", sample_sec_financials())
        self.assertIsNone(result.inputs.non_permissible_revenue)

    def test_missing_data_never_zero(self) -> None:
        result = build_participation_inputs_from_sec(
            "AAPL",
            sample_sec_financials(
                total_debt=None,
                cash=None,
                total_assets=None,
                revenue=None,
            ),
        )
        inputs = result.inputs
        self.assertIsNone(inputs.total_debt)
        self.assertIsNone(inputs.cash)
        self.assertIsNone(inputs.total_assets)
        self.assertIsNone(inputs.total_revenue)

    def test_source_evidence_populated(self) -> None:
        result = build_participation_inputs_from_sec(
            "AAPL",
            sample_sec_financials(),
            cik="320193",
        )
        evidence = dict(result.inputs.source_evidence)
        self.assertEqual(evidence["provider"], "SEC")
        self.assertEqual(evidence["cik"], "320193")
        self.assertEqual(evidence["financial_period_end"], "2025-12-31")
        self.assertEqual(evidence["sec_field:total_debt"], "extract_financials")


class ForeignAndMissingDataTests(unittest.TestCase):
    def test_empty_sec_payload_is_safe(self) -> None:
        result = build_participation_inputs_from_sec("AAPL", {})
        self.assertEqual(result.inputs.symbol, "AAPL")
        self.assertIsNone(result.inputs.total_assets)
        self.assertTrue(result.warnings)

    def test_non_usd_currency_leaves_monetary_fields_unset(self) -> None:
        result = build_participation_inputs_from_sec(
            "TSM",
            sample_sec_financials(financial_currency="TWD"),
        )
        self.assertIsNone(result.inputs.total_debt)
        self.assertIsNone(result.inputs.total_assets)
        self.assertTrue(any("currency" in warning for warning in result.warnings))


class FinancialEngineIntegrationTests(unittest.TestCase):
    def _resolve(self, **sec_overrides) -> ParticipationFinancialInputs:
        return build_participation_inputs_from_sec(
            "TEST",
            sample_sec_financials(**sec_overrides),
            market_capitalization=sec_overrides.pop("market_capitalization", None),
        ).inputs

    def test_msci_debt_rule_evaluates_with_sec_inputs(self) -> None:
        inputs = self._resolve()
        screen = evaluate_financial_rules("msci_islamic_index_series", inputs)
        debt_rule = next(
            rule for rule in screen.rule_results if "total_debt" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_PASS)

    def test_msci_missing_total_assets_stays_insufficient(self) -> None:
        inputs = self._resolve(
            total_assets=None,
            market_capitalization=500_000_000_000.0,
        )
        screen = evaluate_financial_rules("msci_islamic_index_series", inputs)
        debt_rule = next(
            rule for rule in screen.rule_results if "total_debt" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_sp_requires_36m_denominator_insufficient_with_spot_cap_only(self) -> None:
        inputs = self._resolve(market_capitalization=500_000_000_000.0)
        screen = evaluate_financial_rules("sp_shariah", inputs)
        debt_rule = next(
            rule for rule in screen.rule_results if "debt_to_avg_equity" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_djim_requires_24m_denominator_insufficient_with_spot_cap_only(self) -> None:
        inputs = self._resolve(market_capitalization=500_000_000_000.0)
        screen = evaluate_financial_rules("djim", inputs)
        debt_rule = next(
            rule for rule in screen.rule_results if "avg_mcap_24m" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_aaoifi_does_not_use_total_debt_as_interest_bearing_debt(self) -> None:
        inputs = self._resolve(market_capitalization=200_000_000_000.0)
        screen = evaluate_financial_rules("aaoifi_std21", inputs)
        debt_rule = next(
            rule
            for rule in screen.rule_results
            if "interest_bearing_debt_to_market_cap" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_missing_receivables_rule_is_insufficient(self) -> None:
        inputs = self._resolve(accounts_receivable=None)
        screen = evaluate_financial_rules("msci_islamic_index_series", inputs)
        recv_rule = next(
            rule
            for rule in screen.rule_results
            if "receivables_and_cash" in rule.rule_id
        )
        self.assertEqual(recv_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_missing_prohibited_revenue_rule_is_insufficient(self) -> None:
        inputs = self._resolve()
        screen = evaluate_financial_rules("msci_islamic_index_series", inputs)
        revenue_rule = next(
            rule for rule in screen.rule_results if "non_permissible_revenue" in rule.rule_id
        )
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_financial_pass_still_kontrol_et(self) -> None:
        inputs = self._resolve()
        screen = evaluate_financial_rules("msci_islamic_index_series", inputs)
        assessment = build_methodology_assessment_from_financial_screen(screen)
        self.assertFalse(screen.methodology_complete)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_KONTROL_ET)

    def test_financial_fail_still_uygun_degil(self) -> None:
        inputs = self._resolve(total_debt=50_000_000.0, total_assets=100_000_000.0)
        screen = evaluate_financial_rules("msci_islamic_index_series", inputs)
        assessment = build_methodology_assessment_from_financial_screen(screen)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)


class SecAccountsReceivableExtractionTests(unittest.TestCase):
    def test_extract_financials_includes_accounts_receivable(self) -> None:
        client = SECFinancialClient(contact_email="test@example.com")
        payload = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "form": "10-K",
                                    "start": "2024-01-01",
                                    "end": "2024-12-31",
                                    "val": 1000,
                                    "filed": "2025-02-01",
                                },
                            ],
                        },
                    },
                    "AccountsReceivableNetCurrent": {
                        "units": {
                            "USD": [
                                {
                                    "form": "10-K",
                                    "end": "2024-12-31",
                                    "val": 25,
                                    "filed": "2025-02-01",
                                },
                            ],
                        },
                    },
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "form": "10-K",
                                    "end": "2024-12-31",
                                    "val": 100,
                                    "filed": "2025-02-01",
                                },
                            ],
                        },
                    },
                },
            },
        }
        result = client.extract_financials(payload)
        self.assertEqual(result["accounts_receivable"], 25.0)


class DependencyFirewallTests(unittest.TestCase):
    def test_resolver_has_no_forbidden_imports(self) -> None:
        import services.participation_sec_input_resolver as module

        source = inspect.getsource(module)
        forbidden = (
            "alpha_vantage",
            "fmp",
            "requests",
            "httpx",
            "supabase",
            "streamlit",
            "repository",
            "nabi_score_v4",
            "decision_engine",
            "scanner_v",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_resolver_does_not_import_sec_financial_client(self) -> None:
        import services.participation_sec_input_resolver as module

        source = inspect.getsource(module)
        self.assertNotIn("sec_financial_client", source)


class FreshProcessImportTests(unittest.TestCase):
    def test_fresh_imports(self) -> None:
        script = """
import importlib
for name in (
    "services.participation_sec_input_resolver",
    "services.participation_financial_contract",
    "services.participation_financial_engine",
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


if __name__ == "__main__":
    unittest.main()
