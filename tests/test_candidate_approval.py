from __future__ import annotations

import unittest

from services.candidate_approval import (
    REVIEW_PENDING,
    REVIEW_REJECTED,
    REVIEW_RESEARCH_APPROVED,
    CandidateReviewDecision,
    build_candidate_approval_package,
    with_review_decision,
)
from services.candidate_contract import (
    CandidateEligibility,
    CandidateRecord,
    CandidateSourceTrace,
    ELIGIBILITY_ELIGIBLE,
    RankedCandidate,
)
from services.candidate_ranking import rank_candidates


def candidate(symbol="GKV", snapshot="snap-GKV"):
    return CandidateRecord(
        symbol=symbol,
        market="TR",
        instrument_type="FUND",
        total_score=81.96,
        confidence=.9,
        intelligence_state="ATTRACTIVE",
        eligibility=CandidateEligibility(status=ELIGIBILITY_ELIGIBLE),
        source_trace=CandidateSourceTrace(
            analysis_snapshot_id=snapshot,
            analysis_as_of="2026-08-31",
            score_version="fund_intelligence_1g.1",
            facts_version="fund_facts_1d.1",
        ),
        data_completeness=1.0,
        economic_exposure="equity",
        peer_group="EQUITY_PARTICIPATION_FUND",
    )


class CandidateApprovalTests(unittest.TestCase):
    def ranking(self):
        return rank_candidates(
            [candidate()],
            ranking_as_of="2026-08-31",
        )

    def test_default_state_is_pending_review(self):
        result = self.ranking()
        package = build_candidate_approval_package(result.ranked[0], result)
        self.assertEqual(package.review.state, REVIEW_PENDING)
        self.assertEqual(package.peer_group, "EQUITY_PARTICIPATION_FUND")
        self.assertEqual(package.peer_rank, 1)

    def test_research_approval_preserves_snapshot(self):
        result = self.ranking()
        package = build_candidate_approval_package(
            result.ranked[0],
            result,
            review=CandidateReviewDecision(
                state=REVIEW_RESEARCH_APPROVED,
                reason="manual research review complete",
            ),
        )
        self.assertEqual(package.analysis_snapshot_id, "snap-GKV")
        self.assertEqual(
            package.universe_fingerprint,
            result.universe_fingerprint,
        )

    def test_review_decision_is_immutable_copy(self):
        result = self.ranking()
        pending = build_candidate_approval_package(result.ranked[0], result)
        rejected = with_review_decision(
            pending,
            CandidateReviewDecision(
                state=REVIEW_REJECTED,
                reason="research thesis rejected",
            ),
        )
        self.assertEqual(pending.review.state, REVIEW_PENDING)
        self.assertEqual(rejected.review.state, REVIEW_REJECTED)
        self.assertEqual(
            pending.analysis_snapshot_id,
            rejected.analysis_snapshot_id,
        )

    def test_membership_mismatch_fails_closed(self):
        result = self.ranking()
        alien = RankedCandidate(rank=1, candidate=candidate("AAA", "alien"))
        with self.assertRaisesRegex(
            ValueError, "candidate_approval_ranking_membership_mismatch"
        ):
            build_candidate_approval_package(alien, result)

    def test_unknown_review_state_fails(self):
        result = self.ranking()
        with self.assertRaisesRegex(ValueError, "unknown_candidate_review_state"):
            build_candidate_approval_package(
                result.ranked[0],
                result,
                review=CandidateReviewDecision(state="BUY_APPROVED"),
            )

    def test_package_has_no_trade_or_allocation_fields(self):
        result = self.ranking()
        payload = build_candidate_approval_package(
            result.ranked[0], result
        ).to_dict()
        self.assertNotIn("quantity", payload)
        self.assertNotIn("allocation", payload)
        self.assertNotIn("position_size", payload)
        self.assertNotIn("trade", payload)
        self.assertNotIn("new_money", payload)

    def test_notice_explicitly_denies_execution_authority(self):
        result = self.ranking()
        package = build_candidate_approval_package(result.ranked[0], result)
        self.assertIn("Research approval only", package.notice)
        self.assertIn("does not authorize a trade", package.notice)


if __name__ == "__main__":
    unittest.main()
