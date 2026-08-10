import unittest

from services.decision_engine import build_decision


def _candidate(**overrides):
    base = {
        "nabi_score": 79.0,
        "research_confidence": 97.0,
        "risk_score": 70.0,
        "valuation_score": 50.0,
        "quality_score": 90.0,
        "growth_score": 95.0,
        "data_completeness": 96.0,
        "score_positive_factors": [],
        "score_negative_factors": [],
        "hard_flags": [],
        "company_name": "Test Co",
        "symbol": "TEST",
    }
    base.update(overrides)
    return base


class OpportunityScoreTests(unittest.TestCase):
    def test_zero_valuation_score_is_not_treated_as_missing(self):
        low = build_decision(_candidate(valuation_score=0.0))[
            "opportunity_score"
        ]
        missing = build_decision(_candidate(valuation_score=None))[
            "opportunity_score"
        ]
        high = build_decision(_candidate(valuation_score=50.0))[
            "opportunity_score"
        ]

        self.assertLess(low, missing)
        self.assertAlmostEqual(high, missing)

    def test_valuation_improvement_increases_opportunity_with_fixed_inputs(self):
        before = build_decision(_candidate(valuation_score=0.0))[
            "opportunity_score"
        ]
        after = build_decision(_candidate(valuation_score=12.0))[
            "opportunity_score"
        ]

        self.assertGreater(after, before)
        self.assertAlmostEqual(after - before, 12.0 * 0.45, places=1)

    def test_opportunity_formula_is_deterministic(self):
        candidate = _candidate(valuation_score=32.4)
        first = build_decision(candidate)["opportunity_score"]
        second = build_decision(candidate)["opportunity_score"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
