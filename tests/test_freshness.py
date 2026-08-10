import unittest
from datetime import date

from services.confidence_engine import calculate_confidence
from services.freshness_engine import (
    derive_score_confidence,
    evaluate_freshness,
    period_age_days,
)
from services.nabi_score_v4 import calculate_nabi_score_v4


class FreshnessEngineTests(unittest.TestCase):
    def test_period_age_days_from_iso_date(self) -> None:
        age = period_age_days(
            "2025-12-31",
            as_of=date(2026, 8, 10),
        )
        self.assertEqual(age, 222)

    def test_fresh_period(self) -> None:
        result = evaluate_freshness(200)
        self.assertEqual(result["freshness_status"], "FRESH")
        self.assertEqual(result["confidence_adjustment"], 0.0)

    def test_aging_period(self) -> None:
        result = evaluate_freshness(587)
        self.assertEqual(result["freshness_status"], "AGING")
        self.assertLess(result["confidence_adjustment"], 0)

    def test_stale_period(self) -> None:
        result = evaluate_freshness(1958)
        self.assertEqual(result["freshness_status"], "STALE")
        self.assertLessEqual(result["confidence_adjustment"], -22)

    def test_missing_period(self) -> None:
        result = evaluate_freshness(None)
        self.assertEqual(result["freshness_status"], "UNKNOWN")
        self.assertLess(result["confidence_adjustment"], 0)


class ScoreConfidenceAlignmentTests(unittest.TestCase):
    def test_fresh_high_completeness_is_high(self) -> None:
        label = derive_score_confidence(
            data_completeness=92.0,
            freshness_status="FRESH",
        )
        self.assertEqual(label, "YÜKSEK")

    def test_stale_high_completeness_is_not_high(self) -> None:
        label = derive_score_confidence(
            data_completeness=88.0,
            freshness_status="STALE",
        )
        self.assertEqual(label, "DÜŞÜK")

    def test_missing_period_is_not_high(self) -> None:
        label = derive_score_confidence(
            data_completeness=88.0,
            freshness_status="UNKNOWN",
        )
        self.assertEqual(label, "DÜŞÜK")

    def test_aging_high_completeness_is_moderate(self) -> None:
        label = derive_score_confidence(
            data_completeness=92.0,
            freshness_status="AGING",
        )
        self.assertEqual(label, "ORTA")


class ConfidenceFreshnessTests(unittest.TestCase):
    def _base_confidence(self, **overrides):
        payload = {
            "data_completeness": 88.0,
            "annual_periods_found": 10,
            "endpoint_errors": [],
            "score_penalty": 0,
            "financial_period_end": "2021-03-31",
        }
        payload.update(overrides)
        return calculate_confidence(**payload)

    def test_stale_data_lowers_research_confidence(self) -> None:
        stale = self._base_confidence(period_age_days_value=1958)
        fresh = self._base_confidence(
            financial_period_end="2026-01-25",
            period_age_days_value=197,
        )

        self.assertLess(
            stale["research_confidence"],
            fresh["research_confidence"],
        )
        self.assertEqual(stale["freshness_status"], "STALE")
        self.assertLess(stale["research_confidence"], 70)

    def test_stale_data_does_not_change_nabi_score(self) -> None:
        kwargs = dict(
            revenue_growth_1y=12.0,
            revenue_cagr_3y=15.0,
            eps_growth_1y=None,
            eps_cagr_3y=None,
            fcf_cagr_3y=None,
            gross_margin=40.0,
            operating_margin=25.0,
            net_margin=20.0,
            fcf_margin=18.0,
            roic=20.0,
            roe=18.0,
            roa=None,
            current_ratio=None,
            debt_to_equity=None,
            net_debt_to_fcf=None,
            interest_coverage=None,
            pe_ratio=22.0,
            price_to_sales=5.0,
            price_to_book=None,
            share_change_3y=None,
            payout_ratio=None,
            market_cap=1_000_000_000,
            average_volume=1_000_000,
            portfolio_fit=55.0,
            participation_score=60.0,
            participation_status="Kontrol Et",
            completeness=88.0,
        )
        first = calculate_nabi_score_v4(**kwargs)["nabi_score"]
        second = calculate_nabi_score_v4(**kwargs)["nabi_score"]
        self.assertEqual(first, second)

        stale_conf = self._base_confidence(period_age_days_value=1958)
        self.assertNotIn("nabi_score", stale_conf)

    def test_enrich_research_aligns_score_confidence_for_stale(self) -> None:
        from services.research_intelligence_engine import enrich_research

        candidate = {
            "symbol": "SONY",
            "data_completeness": 88.0,
            "annual_periods_found": 14,
            "score_penalty": 0,
            "financial_period_end": "2021-03-31",
            "score_confidence": "YÜKSEK",
            "nabi_score": 68.0,
        }
        enrich_research(candidate, errors=[])
        self.assertEqual(candidate["freshness_status"], "STALE")
        self.assertLess(candidate["research_confidence"], 70)
        self.assertEqual(candidate["score_confidence"], "DÜŞÜK")
        self.assertEqual(candidate["nabi_score"], 68.0)

    def test_fresh_us_regression_confidence_stays_high(self) -> None:
        result = calculate_confidence(
            data_completeness=100.0,
            annual_periods_found=19,
            endpoint_errors=[],
            score_penalty=0,
            financial_period_end="2026-01-25",
            period_age_days_value=197,
        )

        self.assertEqual(result["freshness_status"], "FRESH")
        self.assertGreaterEqual(result["research_confidence"], 95)

    def test_missing_period_reduces_confidence(self) -> None:
        result = calculate_confidence(
            data_completeness=88.0,
            annual_periods_found=10,
            endpoint_errors=[],
            score_penalty=0,
            financial_period_end=None,
        )

        self.assertEqual(result["freshness_status"], "UNKNOWN")
        self.assertIn(
            "Finansal dönem tarihi doğrulanamadı.",
            result["research_confidence_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
