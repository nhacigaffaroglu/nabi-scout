import inspect
import subprocess
import sys
import unittest
from datetime import date
from decimal import Decimal

from services.participation_financial_contract import (
    FINANCIAL_SCREEN_OUTCOME_FAIL,
    FINANCIAL_SCREEN_OUTCOME_INSUFFICIENT_DATA,
    FINANCIAL_SCREEN_OUTCOME_PASS,
    FINANCIAL_SCREEN_OUTCOME_REVIEW_REQUIRED,
    ParticipationFinancialInputs,
)
from services.participation_financial_engine import (
    aggregate_rule_outcomes,
    compare_ratio_to_threshold,
    evaluate_financial_rules,
    normalize_financial_value,
    resolve_denominator_value,
    _methodology_complete_from_evaluation,
)
from services.participation_intelligence_contract import (
    METHODOLOGY_COMPLETENESS_COMPLETE,
    METHODOLOGY_COMPLETENESS_PARTIAL,
    PARTICIPATION_SOURCE_CONFIGURED,
    PARTICIPATION_SOURCE_METHODOLOGY,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
    ParticipationRuleResult,
)
from services.participation_intelligence_service import (
    build_configured_assessment,
    build_methodology_assessment_from_financial_screen,
    get_participation_assessment_for_fund,
)
from services.participation_methodology_registry import (
    MethodologyDefinition,
    _parse_methodology,
    get_methodology,
)


def sample_inputs(**overrides) -> ParticipationFinancialInputs:
    base = dict(
        symbol="TEST",
        as_of_date=date(2026, 1, 1),
        total_debt=30.0,
        interest_bearing_debt=30.0,
        cash=10.0,
        cash_and_interest_bearing_securities=20.0,
        cash_plus_interest_bearing_securities=20.0,
        cash_and_interest_bearing_items=20.0,
        interest_taking_deposits=15.0,
        accounts_receivable=25.0,
        total_assets=100.0,
        market_capitalization=200.0,
        average_market_cap_24m=150.0,
        average_market_value_of_equity_36m=120.0,
        total_revenue=1000.0,
        total_income=900.0,
        non_permissible_revenue=10.0,
        non_permissible_income_excluding_interest=10.0,
        non_compliant_activities_income=10.0,
        prohibited_component_income=10.0,
    )
    base.update(overrides)
    return ParticipationFinancialInputs(**base)


def passing_msci_inputs(**overrides) -> ParticipationFinancialInputs:
    return sample_inputs(
        total_debt=30.0,
        cash_and_interest_bearing_securities=20.0,
        accounts_receivable=20.0,
        cash=10.0,
        non_permissible_revenue=10.0,
        **overrides,
    )


def full_passing_inputs(**overrides) -> ParticipationFinancialInputs:
    return sample_inputs(
        total_debt=10.0,
        interest_bearing_debt=10.0,
        cash=5.0,
        cash_and_interest_bearing_securities=10.0,
        cash_plus_interest_bearing_securities=10.0,
        cash_and_interest_bearing_items=10.0,
        interest_taking_deposits=10.0,
        accounts_receivable=10.0,
        total_assets=100.0,
        market_capitalization=200.0,
        average_market_cap_24m=150.0,
        average_market_value_of_equity_36m=120.0,
        total_revenue=1000.0,
        total_income=900.0,
        non_permissible_revenue=1.0,
        non_permissible_income_excluding_interest=1.0,
        non_compliant_activities_income=1.0,
        prohibited_component_income=1.0,
        **overrides,
    )


class ParticipationFinancialContractTests(unittest.TestCase):
    def test_inputs_are_frozen(self) -> None:
        inputs = sample_inputs()
        with self.assertRaises(Exception):
            inputs.total_assets = 50.0  # type: ignore[misc]

    def test_missing_values_remain_none(self) -> None:
        inputs = ParticipationFinancialInputs(symbol="X")
        self.assertIsNone(inputs.total_assets)
        self.assertIsNone(inputs.market_capitalization)

    def test_to_dict_serializes_as_of_date(self) -> None:
        payload = sample_inputs().to_dict()
        self.assertEqual(payload["as_of_date"], "2026-01-01")
        self.assertEqual(payload["total_assets"], 100.0)


class NumericSafetyTests(unittest.TestCase):
    def test_none_and_invalid_values(self) -> None:
        self.assertIsNone(normalize_financial_value(None))
        self.assertIsNone(normalize_financial_value(float("nan")))
        self.assertIsNone(normalize_financial_value(float("inf")))
        self.assertIsNone(normalize_financial_value(-1))
        self.assertIsNone(normalize_financial_value("not-a-number"))
        self.assertIsNone(normalize_financial_value(True))

    def test_valid_numeric_types(self) -> None:
        self.assertEqual(normalize_financial_value(10), Decimal("10"))
        self.assertEqual(normalize_financial_value(10.5), Decimal("10.5"))
        self.assertEqual(normalize_financial_value("12.25"), Decimal("12.25"))

    def test_zero_denominator_is_insufficient(self) -> None:
        inputs = sample_inputs(total_assets=0.0)
        result = evaluate_financial_rules("msci_islamic_index_series", inputs)
        debt_rule = next(
            rule for rule in result.rule_results if "total_debt" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)


class ThresholdBoundaryTests(unittest.TestCase):
    def test_less_than_exact_threshold_fails(self) -> None:
        outcome = compare_ratio_to_threshold(
            Decimal("33.0"),
            Decimal("33.0"),
            "<",
        )
        self.assertEqual(outcome, RULE_OUTCOME_FAIL)

    def test_less_than_below_threshold_passes(self) -> None:
        outcome = compare_ratio_to_threshold(
            Decimal("32.999"),
            Decimal("33.0"),
            "<",
        )
        self.assertEqual(outcome, RULE_OUTCOME_PASS)

    def test_less_or_equal_exact_threshold_passes(self) -> None:
        outcome = compare_ratio_to_threshold(
            Decimal("33.33"),
            Decimal("33.33"),
            "<=",
        )
        self.assertEqual(outcome, RULE_OUTCOME_PASS)

    def test_msci_debt_rule_exact_boundary(self) -> None:
        inputs = sample_inputs(total_debt=33.33, total_assets=100.0)
        result = evaluate_financial_rules("msci_islamic_index_series", inputs)
        debt_rule = next(
            rule for rule in result.rule_results if "total_debt" in rule.rule_id
        )
        self.assertAlmostEqual(debt_rule.ratio_pct or 0.0, 33.33, places=6)
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_PASS)


class DenominatorIsolationTests(unittest.TestCase):
    def test_msci_uses_total_assets_only(self) -> None:
        inputs = sample_inputs(
            total_debt=30.0,
            total_assets=100.0,
            market_capitalization=500.0,
            average_market_cap_24m=400.0,
            average_market_value_of_equity_36m=300.0,
        )
        result = evaluate_financial_rules("msci_islamic_index_series", inputs)
        debt_rule = next(
            rule for rule in result.rule_results if "total_debt" in rule.rule_id
        )
        self.assertEqual(debt_rule.denominator_raw_value, 100.0)
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_PASS)

    def test_msci_missing_total_assets_is_insufficient(self) -> None:
        inputs = sample_inputs(
            total_assets=None,
            market_capitalization=500.0,
        )
        result = evaluate_financial_rules("msci_islamic_index_series", inputs)
        debt_rule = next(
            rule for rule in result.rule_results if "total_debt" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_sp_uses_36m_mve_only(self) -> None:
        inputs = sample_inputs(
            total_debt=36.0,
            total_assets=100.0,
            market_capitalization=500.0,
            average_market_cap_24m=400.0,
            average_market_value_of_equity_36m=120.0,
        )
        result = evaluate_financial_rules("sp_shariah", inputs)
        debt_rule = next(
            rule for rule in result.rule_results if "debt_to_avg_equity" in rule.rule_id
        )
        self.assertEqual(debt_rule.denominator_raw_value, 120.0)
        self.assertAlmostEqual(debt_rule.ratio_pct or 0.0, 30.0, places=6)

    def test_sp_missing_36m_mve_is_insufficient(self) -> None:
        inputs = sample_inputs(
            average_market_value_of_equity_36m=None,
            total_assets=100.0,
            market_capitalization=500.0,
        )
        result = evaluate_financial_rules("sp_shariah", inputs)
        debt_rule = next(
            rule for rule in result.rule_results if "debt_to_avg_equity" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_djim_uses_24m_market_cap_only(self) -> None:
        inputs = sample_inputs(
            total_debt=45.0,
            average_market_cap_24m=150.0,
            average_market_value_of_equity_36m=120.0,
        )
        result = evaluate_financial_rules("djim", inputs)
        debt_rule = next(
            rule for rule in result.rule_results if "avg_mcap_24m" in rule.rule_id
        )
        self.assertEqual(debt_rule.denominator_raw_value, 150.0)
        self.assertAlmostEqual(debt_rule.ratio_pct or 0.0, 30.0, places=6)

    def test_aaoifi_uses_market_cap_only(self) -> None:
        inputs = sample_inputs(
            interest_bearing_debt=60.0,
            market_capitalization=200.0,
            total_assets=100.0,
        )
        result = evaluate_financial_rules("aaoifi_std21", inputs)
        debt_rule = next(
            rule
            for rule in result.rule_results
            if "interest_bearing_debt_to_market_cap" in rule.rule_id
        )
        self.assertEqual(debt_rule.denominator_raw_value, 200.0)
        self.assertAlmostEqual(debt_rule.ratio_pct or 0.0, 30.0, places=6)


class MethodologyThresholdIsolationTests(unittest.TestCase):
    def test_sp_receivables_uses_49_percent(self) -> None:
        inputs = sample_inputs(
            accounts_receivable=58.8,
            average_market_value_of_equity_36m=120.0,
        )
        result = evaluate_financial_rules("sp_shariah", inputs)
        recv_rule = next(
            rule for rule in result.rule_results if "receivables" in rule.rule_id
        )
        self.assertEqual(recv_rule.threshold_pct, 49.0)
        self.assertEqual(recv_rule.outcome, RULE_OUTCOME_FAIL)

    def test_ftse_receivables_plus_cash_uses_50_percent(self) -> None:
        inputs = sample_inputs(
            accounts_receivable=20.0,
            cash=24.0,
            total_assets=100.0,
        )
        result = evaluate_financial_rules("ftse_yasaar", inputs)
        recv_rule = next(
            rule
            for rule in result.rule_results
            if "receivables_and_cash" in rule.rule_id
        )
        self.assertEqual(recv_rule.threshold_pct, 50.0)
        self.assertEqual(recv_rule.outcome, RULE_OUTCOME_PASS)

    def test_aaoifi_uses_30_percent_threshold(self) -> None:
        inputs = sample_inputs(
            interest_bearing_debt=61.0,
            market_capitalization=200.0,
        )
        result = evaluate_financial_rules("aaoifi_std21", inputs)
        debt_rule = next(
            rule
            for rule in result.rule_results
            if "interest_bearing_debt_to_market_cap" in rule.rule_id
        )
        self.assertEqual(debt_rule.threshold_pct, 30.0)
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_FAIL)


class MissingDataTests(unittest.TestCase):
    def test_missing_numerator_is_insufficient(self) -> None:
        inputs = sample_inputs(total_debt=None)
        result = evaluate_financial_rules("msci_islamic_index_series", inputs)
        debt_rule = next(
            rule for rule in result.rule_results if "total_debt" in rule.rule_id
        )
        self.assertEqual(debt_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_composite_receivables_plus_cash_requires_both_inputs(self) -> None:
        inputs = sample_inputs(accounts_receivable=20.0, cash=None)
        result = evaluate_financial_rules("msci_islamic_index_series", inputs)
        recv_rule = next(
            rule
            for rule in result.rule_results
            if "receivables_and_cash" in rule.rule_id
        )
        self.assertEqual(recv_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)


class CompositeAggregationTests(unittest.TestCase):
    def test_all_pass(self) -> None:
        outcomes = (
            ParticipationRuleResult(rule_id="a", outcome=RULE_OUTCOME_PASS),
            ParticipationRuleResult(rule_id="b", outcome=RULE_OUTCOME_PASS),
        )
        self.assertEqual(aggregate_rule_outcomes(outcomes), FINANCIAL_SCREEN_OUTCOME_PASS)

    def test_one_fail(self) -> None:
        outcomes = (
            ParticipationRuleResult(rule_id="a", outcome=RULE_OUTCOME_PASS),
            ParticipationRuleResult(rule_id="b", outcome=RULE_OUTCOME_FAIL),
        )
        self.assertEqual(aggregate_rule_outcomes(outcomes), FINANCIAL_SCREEN_OUTCOME_FAIL)

    def test_one_review_required(self) -> None:
        outcomes = (
            ParticipationRuleResult(rule_id="a", outcome=RULE_OUTCOME_PASS),
            ParticipationRuleResult(rule_id="b", outcome=RULE_OUTCOME_REVIEW_REQUIRED),
        )
        self.assertEqual(
            aggregate_rule_outcomes(outcomes),
            FINANCIAL_SCREEN_OUTCOME_REVIEW_REQUIRED,
        )

    def test_one_insufficient_data(self) -> None:
        outcomes = (
            ParticipationRuleResult(rule_id="a", outcome=RULE_OUTCOME_PASS),
            ParticipationRuleResult(rule_id="b", outcome=RULE_OUTCOME_INSUFFICIENT_DATA),
        )
        self.assertEqual(
            aggregate_rule_outcomes(outcomes),
            FINANCIAL_SCREEN_OUTCOME_INSUFFICIENT_DATA,
        )

    def test_zero_rules_is_review_required(self) -> None:
        self.assertEqual(
            aggregate_rule_outcomes(()),
            FINANCIAL_SCREEN_OUTCOME_REVIEW_REQUIRED,
        )


class MethodologyCompletenessTests(unittest.TestCase):
    METHODOLOGY_IDS = (
        "msci_islamic_index_series",
        "sp_shariah",
        "djim",
        "ftse_yasaar",
        "aaoifi_std21",
    )

    def test_passing_financial_subset_claims_complete_for_msci(self) -> None:
        inputs = passing_msci_inputs()
        result = evaluate_financial_rules("msci_islamic_index_series", inputs)
        self.assertTrue(result.financial_rules_evaluated)
        self.assertTrue(result.methodology_complete)
        self.assertEqual(result.overall_outcome, FINANCIAL_SCREEN_OUTCOME_PASS)

    def test_all_five_methodologies_fail_closed_on_financial_pass(self) -> None:
        inputs = full_passing_inputs()
        for methodology_id in self.METHODOLOGY_IDS:
            with self.subTest(methodology_id=methodology_id):
                result = evaluate_financial_rules(methodology_id, inputs)
                assessment = build_methodology_assessment_from_financial_screen(result)
                self.assertEqual(result.overall_outcome, FINANCIAL_SCREEN_OUTCOME_PASS)
                if methodology_id == "msci_islamic_index_series":
                    self.assertTrue(result.methodology_complete)
                    self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN)
                else:
                    self.assertFalse(result.methodology_complete)
                    self.assertEqual(assessment.status, PARTICIPATION_STATUS_KONTROL_ET)

    def test_registry_defaults_completeness_field_to_false(self) -> None:
        parsed = _parse_methodology(
            {
                "methodology_id": "synthetic.test",
                "label": "Synthetic",
                "version": "test",
                "asset_scope": ["equity"],
                "source_reference": "test",
                "denominator_policy": "total_assets",
                "notes": "",
                "rules": [],
            }
        )
        self.assertFalse(parsed.financial_screen_complete_methodology)

    def test_registry_explicit_complete_opt_in(self) -> None:
        methodology = MethodologyDefinition(
            methodology_id="synthetic.complete",
            label="Synthetic Complete",
            version="test",
            asset_scope=("equity",),
            source_reference="test",
            denominator_policy="total_assets",
            notes="",
            financial_screen_complete_methodology=True,
            rules=(),
        )
        rule_results = (
            ParticipationRuleResult(rule_id="a", outcome=RULE_OUTCOME_PASS),
        )
        self.assertTrue(
            _methodology_complete_from_evaluation(
                methodology,
                financial_rules_evaluated=True,
                overall_outcome=FINANCIAL_SCREEN_OUTCOME_PASS,
                rule_results=rule_results,
            )
        )

    def test_registry_msci_declares_complete_financial_screen(self) -> None:
        for methodology_id in self.METHODOLOGY_IDS:
            methodology = get_methodology(methodology_id)
            assert methodology is not None
            if methodology_id == "msci_islamic_index_series":
                self.assertTrue(methodology.financial_screen_complete_methodology)
            else:
                self.assertFalse(methodology.financial_screen_complete_methodology)


class AssessmentIntegrationTests(unittest.TestCase):
    def test_methodology_assessment_uses_methodology_source(self) -> None:
        inputs = passing_msci_inputs()
        screen = evaluate_financial_rules("msci_islamic_index_series", inputs)
        assessment = build_methodology_assessment_from_financial_screen(screen)
        self.assertEqual(assessment.source, PARTICIPATION_SOURCE_METHODOLOGY)
        self.assertEqual(assessment.methodology_id, "msci_islamic_index_series")
        self.assertTrue(assessment.financial_screens)

    def test_passing_complete_msci_financial_can_emit_uygun(self) -> None:
        inputs = passing_msci_inputs()
        screen = evaluate_financial_rules("msci_islamic_index_series", inputs)
        assessment = build_methodology_assessment_from_financial_screen(screen)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(assessment.methodology_completeness, METHODOLOGY_COMPLETENESS_COMPLETE)

    def test_financial_fail_maps_to_uygun_degil(self) -> None:
        inputs = sample_inputs(total_debt=50.0, total_assets=100.0)
        screen = evaluate_financial_rules("msci_islamic_index_series", inputs)
        assessment = build_methodology_assessment_from_financial_screen(screen)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_configured_spus_unchanged(self) -> None:
        configured = build_configured_assessment("SPUS")
        fund_path = get_participation_assessment_for_fund("SPUS")
        self.assertEqual(configured.source, PARTICIPATION_SOURCE_CONFIGURED)
        self.assertEqual(fund_path.source, PARTICIPATION_SOURCE_CONFIGURED)
        self.assertFalse(configured.has_methodology_result())


class DependencyFirewallTests(unittest.TestCase):
    def test_financial_engine_has_no_provider_imports(self) -> None:
        import services.participation_financial_engine as module

        source = inspect.getsource(module)
        forbidden = (
            "alpha_vantage",
            "fmp",
            "sec_client",
            "sec_service",
            "requests",
            "httpx",
            "supabase",
            "streamlit",
            "repository",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_financial_engine_has_no_scoring_imports(self) -> None:
        import services.participation_financial_engine as module

        source = inspect.getsource(module)
        for token in ("nabi_score_v4", "decision_engine", "scanner_v8"):
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
    "services.participation_financial_contract",
    "services.participation_financial_engine",
    "services.participation_intelligence_contract",
    "services.participation_methodology_registry",
    "services.participation_intelligence_service",
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


class RegistryExecutableRuleTests(unittest.TestCase):
    def test_each_methodology_has_distinct_denominator_policy(self) -> None:
        msci = get_methodology("msci_islamic_index_series")
        sp = get_methodology("sp_shariah")
        assert msci and sp
        self.assertNotEqual(msci.denominator_policy, sp.denominator_policy)


if __name__ == "__main__":
    unittest.main()
