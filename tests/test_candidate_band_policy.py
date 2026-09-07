from __future__ import annotations

import unittest

from services.candidate_band_policy import (
    CandidateBandPolicy,
    apply_candidate_band_policy,
    band_for_score,
)
from services.candidate_contract import (
    CANDIDATE_BAND_CANDIDATE,
    CANDIDATE_BAND_REJECT,
    CANDIDATE_BAND_STRONG,
    CANDIDATE_BAND_WATCH,
    CandidateEligibility,
    CandidateRecord,
    CandidateSourceTrace,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
)


def policy():
    # Synthetic mechanics-only test values.
    # These are NOT production calibration values.
    return CandidateBandPolicy(
        policy_version="test_policy_1",
        calibration_fingerprint="synthetic-fixture",
        strong_candidate_min=90,
        candidate_min=80,
        watch_min=70,
    )


def record(score, *, eligibility=ELIGIBILITY_ELIGIBLE):
    return CandidateRecord(
        symbol="TST",
        market="TR",
        instrument_type="FUND",
        total_score=score,
        confidence=.9,
        intelligence_state="ATTRACTIVE",
        eligibility=CandidateEligibility(status=eligibility),
        source_trace=CandidateSourceTrace(
            analysis_snapshot_id="snap",
            analysis_as_of="2026-08-31",
            score_version="test_score",
        ),
        data_completeness=1.0,
        economic_exposure="equity",
    )


class CandidateBandPolicyTests(unittest.TestCase):
    def test_policy_requires_calibration_fingerprint(self):
        bad = CandidateBandPolicy(
            policy_version="p",
            calibration_fingerprint="",
            strong_candidate_min=90,
            candidate_min=80,
            watch_min=70,
        )
        with self.assertRaisesRegex(
            ValueError, "candidate_band_calibration_fingerprint_required"
        ):
            bad.validate()

    def test_policy_requires_descending_thresholds(self):
        bad = CandidateBandPolicy(
            policy_version="p",
            calibration_fingerprint="f",
            strong_candidate_min=80,
            candidate_min=90,
            watch_min=70,
        )
        with self.assertRaisesRegex(
            ValueError, "candidate_band_threshold_order_invalid"
        ):
            bad.validate()

    def test_mechanics_map_scores_to_bands(self):
        p = policy()
        self.assertEqual(band_for_score(95, policy=p), CANDIDATE_BAND_STRONG)
        self.assertEqual(band_for_score(85, policy=p), CANDIDATE_BAND_CANDIDATE)
        self.assertEqual(band_for_score(75, policy=p), CANDIDATE_BAND_WATCH)
        self.assertEqual(band_for_score(65, policy=p), CANDIDATE_BAND_REJECT)

    def test_ineligible_never_receives_band(self):
        result = apply_candidate_band_policy(
            record(99, eligibility=ELIGIBILITY_INELIGIBLE),
            policy=policy(),
        )
        self.assertIsNone(result.recommendation_band)

    def test_policy_application_is_immutable(self):
        original = record(95)
        changed = apply_candidate_band_policy(original, policy=policy())
        self.assertIsNone(original.recommendation_band)
        self.assertEqual(changed.recommendation_band, CANDIDATE_BAND_STRONG)


if __name__ == "__main__":
    unittest.main()
