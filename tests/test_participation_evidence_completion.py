import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock

from services.participation_assessment_service import assess_equity_participation
from services.participation_business_contract import BusinessRevenueEvidence
from services.participation_business_evidence_enrichment import (
    derive_non_permissible_revenue_amount,
    enrich_business_activity_evidence,
)
from services.participation_completeness import (
    build_assessment_completeness,
    translate_missing_capability,
)
from services.participation_evidence_service import load_participation_evidence_bundle
from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
)
from services.participation_market_cap_resolver import resolve_historical_market_cap_evidence
from services.participation_sec_input_resolver import build_participation_inputs_from_sec
from services.research_eligibility_service import evaluate_research_eligibility_from_assessment
from tests.test_participation_assessment_service import MockSECClient, sample_sec_financials


def _monthly_prices(count: int, *, start_price: float = 100.0) -> list[dict]:
    end = date.today()
    rows = []
    for index in range(count):
        day = end - timedelta(days=index * 30)
        rows.append({"date": day.isoformat(), "price": start_price + index * 0.5})
    return rows


class MockFMPClient:
    def __init__(
        self,
        *,
        profile: dict | None = None,
        prices: list[dict] | None = None,
    ) -> None:
        self.profile_data = profile or {
            "sharesOutstanding": 1_000_000,
            "marketCap": 150_000_000,
        }
        self.prices = prices if prices is not None else _monthly_prices(40)
        self.profile_calls = 0
        self.price_calls = 0

    def profile(self, symbol: str) -> dict:
        self.profile_calls += 1
        return dict(self.profile_data)

    def historical_price_eod_light(self, symbol: str, *, from_date: str, to_date: str) -> list:
        self.price_calls += 1
        return list(self.prices)


class HistoricalMarketCapTests(unittest.TestCase):
    def test_24m_and_36m_averages_from_price_times_shares(self) -> None:
        fmp = MockFMPClient(prices=_monthly_prices(36, start_price=10.0))
        evidence = resolve_historical_market_cap_evidence(
            symbol="TEST",
            fmp_client=fmp,
            shares_outstanding=1_000_000,
        )
        self.assertIsNotNone(evidence.average_market_cap_24m)
        self.assertIsNotNone(evidence.average_market_value_equity_36m)
        self.assertGreaterEqual(evidence.observation_count_24m, 18)
        self.assertGreaterEqual(evidence.observation_count_36m, 24)

    def test_insufficient_history_does_not_backfill_spot_market_cap(self) -> None:
        fmp = MockFMPClient(prices=_monthly_prices(6))
        evidence = resolve_historical_market_cap_evidence(
            symbol="TEST",
            fmp_client=fmp,
            shares_outstanding=1_000_000,
            profile_market_cap=999_999_999,
        )
        self.assertIsNone(evidence.average_market_cap_24m)
        self.assertIsNone(evidence.average_market_value_equity_36m)
        self.assertTrue(
            any("Güncel piyasa değeri" in item for item in evidence.limitations)
        )

    def test_duplicate_monthly_dates_use_last_observation(self) -> None:
        today = date.today().isoformat()
        fmp = MockFMPClient(
            prices=[
                {"date": today, "price": 10.0},
                {"date": today, "price": 20.0},
                *_monthly_prices(35, start_price=30.0),
            ]
        )
        evidence = resolve_historical_market_cap_evidence(
            symbol="TEST",
            fmp_client=fmp,
            shares_outstanding=1_000,
        )
        self.assertIsNotNone(evidence.average_market_cap_24m)


class SecInputResolverTests(unittest.TestCase):
    def test_cash_alone_does_not_populate_combined_field(self) -> None:
        result = build_participation_inputs_from_sec(
            "AAPL",
            sample_sec_financials(interest_bearing_securities=None),
        )
        self.assertIsNone(result.inputs.cash_and_interest_bearing_securities)

    def test_both_cash_and_interest_bearing_populates_combined_field(self) -> None:
        result = build_participation_inputs_from_sec(
            "AAPL",
            sample_sec_financials(interest_bearing_securities=5_000_000.0),
        )
        self.assertEqual(result.inputs.cash_and_interest_bearing_securities, 15_000_000.0)

    def test_missing_values_remain_none_not_zero(self) -> None:
        result = build_participation_inputs_from_sec(
            "AAPL",
            sample_sec_financials(total_debt=None),
        )
        self.assertIsNone(result.inputs.total_debt)


class BusinessEvidenceEnrichmentTests(unittest.TestCase):
    def test_sec_sic_precedence_over_candidate(self) -> None:
        evidence = enrich_business_activity_evidence(
            {"symbol": "TEST", "sic_code": "7370"},
            sec_metadata={"sic_code": "7990", "sic_description": "Gambling"},
        )
        self.assertEqual(evidence.sic_code, "7990")

    def test_description_alone_cannot_derive_prohibited_revenue(self) -> None:
        amount, warnings = derive_non_permissible_revenue_amount(
            1_000_000.0,
            (),
        )
        self.assertIsNone(amount)
        self.assertTrue(warnings)

    def test_segment_pct_derives_non_permissible_revenue(self) -> None:
        segments = (
            BusinessRevenueEvidence(
                segment_name="non_permissible gaming",
                category="non_permissible",
                revenue_pct=4.0,
            ),
        )
        amount, _ = derive_non_permissible_revenue_amount(1_000_000.0, segments)
        self.assertEqual(amount, 40_000.0)


class AssessmentIntegrationTests(unittest.TestCase):
    def _assess(
        self,
        *,
        sec_overrides=None,
        fmp: MockFMPClient | None = None,
        business_evidence=None,
        persistence_available: bool = True,
        methodology_id: str | None = None,
    ):
        from services.participation_business_contract import BusinessActivityEvidence

        sec = sample_sec_financials(**(sec_overrides or {}))
        kwargs = {}
        if business_evidence is not None:
            kwargs["business_evidence"] = business_evidence
        if methodology_id is not None:
            kwargs["methodology_id"] = methodology_id
        return assess_equity_participation(
            "TEST",
            sec_client=MockSECClient(financials=sec),
            cik=1,
            fmp_client=fmp,
            persistence_available=persistence_available,
            **kwargs,
        )

    def test_fixture_a_compliant_inputs_still_kontrol_et_without_full_methodology(self) -> None:
        result = self._assess(
            sec_overrides={"interest_bearing_securities": 5_000_000.0},
            fmp=MockFMPClient(),
        )
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        evaluated = sum(
            1
            for rule in result.financial_screen_result.rule_results
            if rule.outcome in {RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL}
        )
        self.assertGreater(evaluated, 2)

    def test_fixture_b_prohibited_business_fail(self) -> None:
        from services.participation_business_contract import BusinessActivityEvidence

        result = self._assess(
            business_evidence=BusinessActivityEvidence(
                symbol="TEST",
                industry="Gambling",
            ),
        )
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_fixture_c_financial_ratio_fail(self) -> None:
        result = self._assess(
            sec_overrides={
                "total_debt": 50_000_000.0,
                "total_assets": 100_000_000.0,
            }
        )
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_fixture_d_missing_financial_denominator_blocks_pass(self) -> None:
        result = self._assess(sec_overrides={"total_assets": None})
        eligibility = evaluate_research_eligibility_from_assessment(result)
        self.assertFalse(eligibility.research_allowed)

    def test_fixture_f_missing_prohibited_revenue_capability(self) -> None:
        result = self._assess(fmp=MockFMPClient())
        self.assertIn("prohibited_revenue_inference", result.missing_capabilities)

    def test_fixture_g_insufficient_market_cap_history(self) -> None:
        result = self._assess(
            fmp=MockFMPClient(prices=_monthly_prices(6)),
            methodology_id="djim",
        )
        self.assertIn("historical_market_cap_24m", result.missing_capabilities)
        self.assertIsNone(result.financial_inputs.average_market_cap_24m)

    def test_fixture_h_decisive_fail_despite_incomplete_other_rules(self) -> None:
        result = self._assess(
            sec_overrides={"total_debt": 80_000_000.0, "total_assets": 100_000_000.0},
        )
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_fixture_j_provider_partial_failure_still_deterministic(self) -> None:
        fmp = MockFMPClient()
        fmp.profile = MagicMock(side_effect=RuntimeError("network"))
        result = self._assess(fmp=fmp)
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertFalse(result.errors)

    def test_persistence_capability_removed_when_available(self) -> None:
        result = self._assess(persistence_available=True)
        self.assertNotIn("assessment_persistence", result.missing_capabilities)


class CompletenessAndUiLabelTests(unittest.TestCase):
    def test_translate_missing_capability_turkish(self) -> None:
        label = translate_missing_capability("historical_market_cap_24m")
        self.assertIn("24 aylık", label)

    def test_completeness_counts_evaluated_rules(self) -> None:
        from services.participation_assessment_service import ParticipationAssessmentResult
        from services.participation_intelligence_contract import ParticipationAssessment

        result = assess_equity_participation(
            "TEST",
            sec_client=MockSECClient(),
            cik=1,
        )
        completeness = build_assessment_completeness(result)
        self.assertEqual(completeness.financial_rules_total, 4)
        self.assertFalse(completeness.assessment_complete)


class EvidenceBundleBudgetTests(unittest.TestCase):
    def test_participation_evidence_budget_separate_from_sec(self) -> None:
        fmp = MockFMPClient()
        bundle = load_participation_evidence_bundle("TEST", fmp_client=fmp)
        self.assertEqual(bundle.provider_calls.get("profile"), 1)
        self.assertEqual(bundle.provider_calls.get("historical_price_eod_light"), 1)


if __name__ == "__main__":
    unittest.main()
