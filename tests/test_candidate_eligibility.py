from __future__ import annotations

import unittest

from services.candidate_contract import (
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_WATCH_ONLY,
)
from services.candidate_eligibility import (
    CandidateEligibilityInput,
    evaluate_candidate_eligibility,
)


class CandidateEligibilityTests(unittest.TestCase):
    def ready(self, **updates):
        payload = dict(
            scanner_status="READY",
            participation_status="Uygun",
            research_allowed=True,
            intelligence_publishable=True,
            economic_exposure_known=True,
            analysis_snapshot_id="snapshot-1",
            missing_evidence=(),
            required_evidence_fresh=True,
        )
        payload.update(updates)
        return CandidateEligibilityInput(**payload)

    def test_ready_row_is_eligible(self):
        result = evaluate_candidate_eligibility(self.ready())
        self.assertEqual(result.status, ELIGIBILITY_ELIGIBLE)
        self.assertTrue(result.rankable)

    def test_high_score_cannot_bypass_scanner_gate(self):
        result = evaluate_candidate_eligibility(
            self.ready(scanner_status="REVIEW_REQUIRED")
        )
        self.assertEqual(result.status, ELIGIBILITY_WATCH_ONLY)
        self.assertFalse(result.rankable)
        self.assertIn("SCANNER_NOT_READY", result.reasons)

    def test_participation_gate_fail_is_ineligible(self):
        result = evaluate_candidate_eligibility(
            self.ready(participation_status="Kontrol Et")
        )
        self.assertEqual(result.status, ELIGIBILITY_INELIGIBLE)
        self.assertIn("PARTICIPATION_NOT_UYGUN", result.reasons)

    def test_research_not_allowed_is_ineligible(self):
        result = evaluate_candidate_eligibility(
            self.ready(research_allowed=False)
        )
        self.assertEqual(result.status, ELIGIBILITY_INELIGIBLE)

    def test_unknown_exposure_is_watch_only(self):
        result = evaluate_candidate_eligibility(
            self.ready(economic_exposure_known=False)
        )
        self.assertEqual(result.status, ELIGIBILITY_WATCH_ONLY)

    def test_stale_required_evidence_is_watch_only(self):
        result = evaluate_candidate_eligibility(
            self.ready(required_evidence_fresh=False)
        )
        self.assertEqual(result.status, ELIGIBILITY_WATCH_ONLY)

    def test_protected_blocker_prevents_ranking(self):
        result = evaluate_candidate_eligibility(
            self.ready(missing_evidence=("PDR_RECONCILIATION_FAILED",))
        )
        self.assertEqual(result.status, ELIGIBILITY_WATCH_ONLY)
        self.assertIn("PDR_RECONCILIATION_FAILED", result.reasons)

    def test_missing_snapshot_is_ineligible(self):
        result = evaluate_candidate_eligibility(
            self.ready(analysis_snapshot_id="")
        )
        self.assertEqual(result.status, ELIGIBILITY_INELIGIBLE)


if __name__ == "__main__":
    unittest.main()
