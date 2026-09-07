from __future__ import annotations

import unittest

from services.candidate_contract import (
    CandidateEligibility,
    CandidateRecord,
    CandidateSourceTrace,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
)
from services.candidate_score_calibration import (
    candidate_score_calibration_diagnostic,
    score_distribution,
)


def record(
    symbol,
    score,
    *,
    state="ATTRACTIVE",
    eligibility=ELIGIBILITY_ELIGIBLE,
    peer_group="EQUITY_PARTICIPATION_FUND",
    exposure="equity",
):
    return CandidateRecord(
        symbol=symbol,
        market="TR",
        instrument_type="FUND",
        total_score=score,
        confidence=.8,
        intelligence_state=state,
        eligibility=CandidateEligibility(status=eligibility),
        source_trace=CandidateSourceTrace(
            analysis_snapshot_id=f"snap-{symbol}",
            analysis_as_of="2026-08-31",
            score_version="fund_intelligence_1g.1",
            facts_version="fund_facts_1d.1",
        ),
        data_completeness=.9,
        economic_exposure=exposure,
        peer_group=peer_group,
    )


class CandidateScoreCalibrationTests(unittest.TestCase):
    def test_distribution_is_deterministic(self):
        self.assertEqual(
            score_distribution([90, 60, 80, 70]),
            score_distribution([70, 80, 60, 90]),
        )

    def test_distribution_reports_quantiles_without_thresholds(self):
        diag = candidate_score_calibration_diagnostic(
            [record("A", 60), record("B", 70), record("C", 80), record("D", 90)]
        )
        self.assertEqual(diag.eligible_scores.count, 4)
        self.assertEqual(diag.eligible_scores.minimum, 60.0)
        self.assertEqual(diag.eligible_scores.maximum, 90.0)
        self.assertFalse(diag.thresholds_proposed)

    def test_ineligible_scores_are_excluded(self):
        diag = candidate_score_calibration_diagnostic(
            [record("A", 80), record("X", 99, eligibility=ELIGIBILITY_INELIGIBLE)]
        )
        self.assertEqual(diag.eligible_scores.count, 1)
        self.assertEqual(diag.eligible_scores.maximum, 80.0)

    def test_grouping_by_state(self):
        diag = candidate_score_calibration_diagnostic(
            [
                record("A", 90, state="ATTRACTIVE"),
                record("B", 80, state="ATTRACTIVE"),
                record("C", 70, state="WATCH"),
            ]
        )
        groups = dict(diag.by_intelligence_state)
        self.assertEqual(groups["ATTRACTIVE"].count, 2)
        self.assertEqual(groups["WATCH"].count, 1)

    def test_empty_distribution_is_explicit(self):
        diag = candidate_score_calibration_diagnostic([])
        self.assertEqual(diag.eligible_scores.count, 0)
        self.assertIsNone(diag.eligible_scores.median)
        self.assertFalse(diag.thresholds_proposed)

    def test_single_value_quantiles_are_stable(self):
        dist = score_distribution([81.96])
        self.assertEqual(dist.q10, 81.96)
        self.assertEqual(dist.q25, 81.96)
        self.assertEqual(dist.median, 81.96)
        self.assertEqual(dist.q75, 81.96)
        self.assertEqual(dist.q90, 81.96)


    def test_grouping_by_peer_group_and_exposure(self):
        diag = candidate_score_calibration_diagnostic(
            [
                record("E1", 80, peer_group="EQUITY", exposure="equity"),
                record("E2", 70, peer_group="EQUITY", exposure="equity"),
                record("S1", 60, peer_group="SUKUK", exposure="sukuk"),
            ]
        )
        peers = dict(diag.by_peer_group)
        exposures = dict(diag.by_economic_exposure)
        self.assertEqual(peers["EQUITY"].count, 2)
        self.assertEqual(peers["SUKUK"].count, 1)
        self.assertEqual(exposures["equity"].count, 2)
        self.assertEqual(exposures["sukuk"].count, 1)

    def test_instrument_type_group_remains_backward_visible(self):
        diag = candidate_score_calibration_diagnostic(
            [record("A", 80), record("B", 70)]
        )
        self.assertEqual(dict(diag.by_instrument_type)["FUND"].count, 2)


if __name__ == "__main__":
    unittest.main()
