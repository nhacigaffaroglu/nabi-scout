import unittest
from datetime import date

from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_financial_diagnostics import (
    assert_diagnostic_payload_safe,
    format_financial_rule_diagnostic,
)
from services.participation_financial_engine import evaluate_financial_rules
from services.participation_financial_provenance import (
    FinancialFieldProvenance,
    SOURCE_FMP,
    SOURCE_SEC,
    combine_field_provenance,
    resolve_rule_metric_provenance,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    ParticipationRuleResult,
    RULE_OUTCOME_PASS,
)
from services.participation_market_cap_resolver import apply_market_cap_evidence_to_inputs, HistoricalMarketCapEvidence
from services.participation_sec_input_resolver import build_participation_inputs_from_sec


def _aapl_sec_financials(**overrides):
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


class ProvenanceSemanticsTests(unittest.TestCase):
    def test_sec_plus_sec_combines_to_sec(self) -> None:
        combined = combine_field_provenance(
            FinancialFieldProvenance(source=SOURCE_SEC, source_fields=("Cash",)),
            FinancialFieldProvenance(source=SOURCE_SEC, source_fields=("Assets",)),
        )
        self.assertEqual(combined.source, SOURCE_SEC)
        self.assertEqual(combined.source_fields, ("Cash", "Assets"))

    def test_sec_plus_fmp_combines_to_mixed(self) -> None:
        combined = combine_field_provenance(
            FinancialFieldProvenance(source=SOURCE_SEC, source_fields=("Assets",)),
            FinancialFieldProvenance(source=SOURCE_FMP, source_fields=("marketCap",)),
        )
        self.assertEqual(combined.source, "SEC + FMP")

    def test_multiple_sec_tags_remain_sec(self) -> None:
        resolution = build_participation_inputs_from_sec("AAPL", _aapl_sec_financials(), cik="320193")
        provenance = resolve_rule_metric_provenance(
            numerator_key="total_debt",
            denominator_key="total_assets",
            provenance_by_field=dict(resolution.inputs.field_provenance),
        )
        self.assertEqual(provenance.source, SOURCE_SEC)
        self.assertIn("LongTermDebtCurrent", provenance.source_fields)
        self.assertIn("Assets", provenance.source_fields)


class RuleProvenanceTests(unittest.TestCase):
    def test_sec_only_msci_rule_reports_sec(self) -> None:
        resolution = build_participation_inputs_from_sec("AAPL", _aapl_sec_financials(), cik="320193")
        screen = evaluate_financial_rules("msci_islamic_index_series", resolution.inputs)
        debt_rule = next(
            rule for rule in screen.rule_results
            if rule.rule_id == "msci.total_debt_to_total_assets"
        )
        self.assertEqual(debt_rule.metric_source, SOURCE_SEC)

    def test_fmp_only_rule_reports_fmp(self) -> None:
        inputs = ParticipationFinancialInputs(
            symbol="TEST",
            total_debt=10.0,
            average_market_cap_24m=100.0,
            field_provenance=(
                ("total_debt", FinancialFieldProvenance(source=SOURCE_SEC, source_fields=("Debt",))),
                (
                    "average_market_cap_24m",
                    FinancialFieldProvenance(
                        source=SOURCE_FMP,
                        source_fields=("historical_price_eod_light",),
                    ),
                ),
            ),
        )
        screen = evaluate_financial_rules("djim", inputs)
        rule = next(
            item for item in screen.rule_results if "total_debt_to_avg_mcap_24m" in item.rule_id
        )
        self.assertEqual(rule.metric_source, "SEC + FMP")

    def test_provider_call_presence_does_not_override_metric_provenance(self) -> None:
        resolution = build_participation_inputs_from_sec("AAPL", _aapl_sec_financials(), cik="320193")
        merged = apply_market_cap_evidence_to_inputs(
            resolution.inputs,
            HistoricalMarketCapEvidence(
                average_market_cap_24m=1_000_000.0,
                source_evidence=(("market_cap_provider", "fmp"),),
            ),
        )
        self.assertIn(("provider", "SEC"), merged.source_evidence)
        screen = evaluate_financial_rules("msci_islamic_index_series", merged)
        cash_rule = next(
            rule
            for rule in screen.rule_results
            if rule.rule_id == "msci.cash_and_interest_bearing_to_total_assets"
        )
        self.assertEqual(cash_rule.metric_source, SOURCE_SEC)
        diagnostic = format_financial_rule_diagnostic(cash_rule, as_of_date=date(2025, 9, 27))
        self.assertEqual(diagnostic["source"], SOURCE_SEC)

    def test_diagnostic_serializer_preserves_source_and_fields(self) -> None:
        rule = ParticipationRuleResult(
            rule_id="msci.total_debt_to_total_assets",
            outcome=RULE_OUTCOME_PASS,
            numerator_raw_value=90.68e9,
            denominator_raw_value=359.24e9,
            ratio_pct=25.24,
            threshold_pct=33.33,
            comparator="<=",
            metric_source=SOURCE_SEC,
            metric_source_fields=(
                "LongTermDebtCurrent",
                "LongTermDebtNoncurrent",
                "Assets",
            ),
            source_dates=(("provider", "FMP"), ("balance_sheet_period_end", "2025-09-27")),
        )
        payload = format_financial_rule_diagnostic(rule, as_of_date=date(2025, 9, 27))
        self.assertEqual(payload["source"], SOURCE_SEC)
        self.assertIn("Assets", payload["source_fields"])
        assert_diagnostic_payload_safe(payload)

    def test_source_fields_do_not_expose_secrets(self) -> None:
        rule = ParticipationRuleResult(
            rule_id="msci.total_debt_to_total_assets",
            outcome=RULE_OUTCOME_PASS,
            metric_source=SOURCE_SEC,
            metric_source_fields=("Assets", "api_key=hidden"),
        )
        with self.assertRaises(ValueError):
            assert_diagnostic_payload_safe(
                format_financial_rule_diagnostic(rule, as_of_date=date(2025, 9, 27))
            )


class AaplProvenanceRegressionTests(unittest.TestCase):
    def test_aapl_forensic_ratios_unchanged(self) -> None:
        resolution = build_participation_inputs_from_sec("AAPL", _aapl_sec_financials(), cik="320193")
        screen = evaluate_financial_rules("msci_islamic_index_series", resolution.inputs)
        by_id = {rule.rule_id: rule for rule in screen.rule_results}
        self.assertAlmostEqual(by_id["msci.total_debt_to_total_assets"].ratio_pct, 25.24, places=1)
        self.assertAlmostEqual(
            by_id["msci.cash_and_interest_bearing_to_total_assets"].ratio_pct,
            36.86,
            places=1,
        )
        self.assertAlmostEqual(
            by_id["msci.receivables_and_cash_to_total_assets"].ratio_pct,
            21.08,
            places=1,
        )

    def test_aapl_forensic_sources_are_sec(self) -> None:
        resolution = build_participation_inputs_from_sec("AAPL", _aapl_sec_financials(), cik="320193")
        merged = apply_market_cap_evidence_to_inputs(
            resolution.inputs,
            HistoricalMarketCapEvidence(
                average_market_cap_24m=1_000_000.0,
                source_evidence=(("market_cap_provider", "fmp"),),
            ),
        )
        screen = evaluate_financial_rules("msci_islamic_index_series", merged)
        for rule_id in (
            "msci.total_debt_to_total_assets",
            "msci.cash_and_interest_bearing_to_total_assets",
            "msci.receivables_and_cash_to_total_assets",
        ):
            rule = next(item for item in screen.rule_results if item.rule_id == rule_id)
            self.assertEqual(rule.metric_source, SOURCE_SEC)

    def test_aapl_verdict_unchanged_after_provenance_fix(self) -> None:
        from services.participation_intelligence_service import build_combined_methodology_assessment
        from services.participation_business_contract import BusinessActivityScreenResult
        from services.participation_financial_contract import FINANCIAL_SCREEN_OUTCOME_FAIL

        resolution = build_participation_inputs_from_sec("AAPL", _aapl_sec_financials(), cik="320193")
        financial = evaluate_financial_rules("msci_islamic_index_series", resolution.inputs)
        business = BusinessActivityScreenResult(
            symbol="AAPL",
            methodology_id="msci_islamic_index_series",
            methodology_version="2024-10",
            rule_results=(),
            overall_outcome="INSUFFICIENT_DATA",
            business_rules_evaluated=False,
            methodology_complete=False,
            warnings=(),
        )
        assessment = build_combined_methodology_assessment(financial, business)
        self.assertEqual(financial.overall_outcome, FINANCIAL_SCREEN_OUTCOME_FAIL)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)


if __name__ == "__main__":
    unittest.main()
