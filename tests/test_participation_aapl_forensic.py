import unittest
from datetime import date

from services.participation_financial_diagnostics import (
    assert_diagnostic_payload_safe,
    format_financial_rule_diagnostic,
    serialize_financial_diagnostics,
)
from services.participation_financial_contract import (
    FINANCIAL_SCREEN_OUTCOME_FAIL,
    FINANCIAL_SCREEN_OUTCOME_INSUFFICIENT_DATA,
    ParticipationFinancialInputs,
)
from services.participation_financial_engine import evaluate_financial_rules
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    ParticipationRuleResult,
)
from services.participation_intelligence_service import (
    _combined_assessment_status,
    build_combined_methodology_assessment,
)
from services.participation_sec_input_resolver import build_participation_inputs_from_sec


def _aapl_like_sec_financials(**overrides):
    payload = {
        "total_debt": 90_678_000_000.0,
        "cash": 35_934_000_000.0,
        "total_assets": 359_241_000_000.0,
        "revenue": 416_161_000_000.0,
        "accounts_receivable": 39_777_000_000.0,
        "interest_bearing_securities": 96_486_000_000.0,
        "interest_bearing_securities_tags": (
            "MarketableSecuritiesCurrent+MarketableSecuritiesNoncurrent"
        ),
        "balance_sheet_period_end": "2025-09-27",
        "financial_period_end": "2025-09-27",
        "financial_currency": "USD",
        "annual_periods_found": 5,
    }
    payload.update(overrides)
    return payload


class ParticipationAaplForensicTests(unittest.TestCase):
    def test_aapl_corrected_cash_interest_rule_still_fails_methodologically(self) -> None:
        resolution = build_participation_inputs_from_sec(
            "AAPL",
            _aapl_like_sec_financials(),
            cik="320193",
        )
        screen = evaluate_financial_rules(
            "msci_islamic_index_series",
            resolution.inputs,
        )
        by_id = {rule.rule_id: rule for rule in screen.rule_results}

        self.assertEqual(by_id["msci.total_debt_to_total_assets"].outcome, RULE_OUTCOME_PASS)
        self.assertEqual(
            by_id["msci.cash_and_interest_bearing_to_total_assets"].outcome,
            RULE_OUTCOME_FAIL,
        )
        self.assertAlmostEqual(
            by_id["msci.cash_and_interest_bearing_to_total_assets"].ratio_pct,
            36.86,
            places=1,
        )
        self.assertEqual(
            by_id["msci.receivables_and_cash_to_total_assets"].outcome,
            RULE_OUTCOME_PASS,
        )
        self.assertEqual(
            by_id["msci.non_permissible_revenue"].outcome,
            RULE_OUTCOME_INSUFFICIENT_DATA,
        )
        self.assertEqual(screen.overall_outcome, FINANCIAL_SCREEN_OUTCOME_FAIL)
        self.assertEqual(
            sum(
                1
                for rule in screen.rule_results
                if rule.outcome in {RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL}
            ),
            3,
        )

    def test_stale_interest_bearing_without_aligned_period_is_insufficient_not_fail(
        self,
    ) -> None:
        resolution = build_participation_inputs_from_sec(
            "AAPL",
            _aapl_like_sec_financials(interest_bearing_securities=None),
            cik="320193",
        )
        self.assertIsNone(resolution.inputs.cash_and_interest_bearing_securities)
        screen = evaluate_financial_rules(
            "msci_islamic_index_series",
            resolution.inputs,
        )
        cash_rule = next(
            rule
            for rule in screen.rule_results
            if rule.rule_id == "msci.cash_and_interest_bearing_to_total_assets"
        )
        self.assertEqual(cash_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_business_incomplete_alone_does_not_force_uygun_degil(self) -> None:
        from services.participation_business_contract import BusinessActivityScreenResult

        passing_inputs = ParticipationFinancialInputs(
            symbol="TEST",
            total_debt=10.0,
            cash=10.0,
            cash_and_interest_bearing_securities=20.0,
            total_assets=100.0,
            accounts_receivable=5.0,
            total_revenue=100.0,
        )
        financial = evaluate_financial_rules("msci_islamic_index_series", passing_inputs)
        self.assertEqual(financial.overall_outcome, FINANCIAL_SCREEN_OUTCOME_INSUFFICIENT_DATA)
        business = BusinessActivityScreenResult(
            symbol="TEST",
            methodology_id="msci_islamic_index_series",
            methodology_version="2024-10",
            rule_results=(),
            overall_outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            business_rules_evaluated=False,
            methodology_complete=False,
            warnings=(),
        )
        assessment = build_combined_methodology_assessment(financial, business)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertNotEqual(assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

        decisive_financial = evaluate_financial_rules(
            "msci_islamic_index_series",
            build_participation_inputs_from_sec("AAPL", _aapl_like_sec_financials()).inputs,
        )
        self.assertEqual(
            _combined_assessment_status(decisive_financial, business),
            PARTICIPATION_STATUS_UYGUN_DEGIL,
        )

    def test_financial_fail_exposes_exact_rule_evidence(self) -> None:
        screen = evaluate_financial_rules(
            "msci_islamic_index_series",
            build_participation_inputs_from_sec("AAPL", _aapl_like_sec_financials()).inputs,
        )
        diagnostics = serialize_financial_diagnostics(screen, as_of_date=date(2025, 9, 27))
        failing = next(row for row in diagnostics if row["status"] == "Başarısız")
        self.assertEqual(
            failing["rule_id"],
            "msci.cash_and_interest_bearing_to_total_assets",
        )
        self.assertEqual(failing["source"], "SEC")
        self.assertIn("36.86%", failing["calculated_ratio"])
        self.assertEqual(
            next(row for row in diagnostics if row["status"] == "Değerlendirilemedi")[
                "rule_id"
            ],
            "msci.non_permissible_revenue",
        )

    def test_diagnostic_serialization_contains_no_secrets(self) -> None:
        rule = ParticipationRuleResult(
            rule_id="msci.total_debt_to_total_assets",
            outcome=RULE_OUTCOME_PASS,
            numerator_raw_value=100.0,
            denominator_raw_value=400.0,
            ratio_pct=25.0,
            threshold_pct=33.33,
            comparator="<=",
            source_dates=(("provider", "SEC"), ("financial_period_end", "2025-09-27")),
        )
        payload = format_financial_rule_diagnostic(rule, as_of_date=date(2025, 9, 27))
        assert_diagnostic_payload_safe(payload)
        with self.assertRaises(ValueError):
            assert_diagnostic_payload_safe({"note": "api_key=super-secret"})


if __name__ == "__main__":
    unittest.main()
