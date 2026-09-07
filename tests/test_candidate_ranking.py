from __future__ import annotations

import unittest

from services.candidate_contract import (
    CANDIDATE_RANKING_VERSION,
    CandidateEligibility,
    CandidateRecord,
    CandidateSourceTrace,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_WATCH_ONLY,
)
from services.candidate_ranking import rank_candidates


class CandidateRankingTests(unittest.TestCase):
    def record(
        self,
        symbol,
        *,
        score=80.0,
        completeness=1.0,
        confidence=0.8,
        eligibility=ELIGIBILITY_ELIGIBLE,
        snapshot=None,
        band=None,
        peer_group="EQUITY_PARTICIPATION_FUND",
    ):
        return CandidateRecord(
            symbol=symbol,
            market="TR",
            instrument_type="FUND",
            total_score=score,
            confidence=confidence,
            intelligence_state="ATTRACTIVE",
            eligibility=CandidateEligibility(status=eligibility),
            source_trace=CandidateSourceTrace(
                analysis_snapshot_id=snapshot or f"snap-{symbol}",
                analysis_as_of="2026-08-31",
                score_version="fund_intelligence_1g.1",
                facts_version="fund_facts_1d.1",
            ),
            recommendation_band=band,
            data_completeness=completeness,
            economic_exposure="equity",
            peer_group=peer_group,
        )

    def test_score_desc_then_completeness_confidence_symbol(self):
        rows = [
            self.record("DDD", score=81, completeness=.8, confidence=.9),
            self.record("CCC", score=81, completeness=.9, confidence=.7),
            self.record("BBB", score=81, completeness=.9, confidence=.8),
            self.record("AAA", score=81, completeness=.9, confidence=.8),
            self.record("ZZZ", score=90, completeness=.1, confidence=.1),
        ]
        result = rank_candidates(rows, ranking_as_of="2026-08-31")
        self.assertEqual(
            [r.candidate.symbol for r in result.ranked],
            ["ZZZ", "AAA", "BBB", "CCC", "DDD"],
        )

    def test_input_order_does_not_change_order_or_fingerprint(self):
        a = self.record("AAA", score=80)
        b = self.record("BBB", score=90)
        one = rank_candidates([a, b], ranking_as_of="2026-08-31")
        two = rank_candidates([b, a], ranking_as_of="2026-08-31")
        self.assertEqual(one.universe_fingerprint, two.universe_fingerprint)
        self.assertEqual(
            [r.candidate.symbol for r in one.ranked],
            [r.candidate.symbol for r in two.ranked],
        )

    def test_watch_and_ineligible_are_not_ranked(self):
        rows = [
            self.record("AAA", eligibility=ELIGIBILITY_ELIGIBLE),
            self.record("WWW", eligibility=ELIGIBILITY_WATCH_ONLY),
            self.record("XXX", eligibility=ELIGIBILITY_INELIGIBLE),
        ]
        result = rank_candidates(rows, ranking_as_of="2026-08-31")
        self.assertEqual([r.candidate.symbol for r in result.ranked], ["AAA"])
        self.assertEqual([r.symbol for r in result.watch_only], ["WWW"])
        self.assertEqual([r.symbol for r in result.ineligible], ["XXX"])

    def test_eligible_missing_score_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "eligible_candidate_missing_score"):
            rank_candidates(
                [self.record("AAA", score=None)],
                ranking_as_of="2026-08-31",
            )

    def test_duplicate_symbol_snapshot_is_rejected(self):
        rows = [
            self.record("AAA", snapshot="same"),
            self.record("aaa", snapshot="same"),
        ]
        with self.assertRaisesRegex(ValueError, "duplicate_candidate_snapshot"):
            rank_candidates(rows, ranking_as_of="2026-08-31")

    def test_snapshot_change_changes_fingerprint(self):
        one = rank_candidates(
            [self.record("AAA", snapshot="snap-1")],
            ranking_as_of="2026-08-31",
        )
        two = rank_candidates(
            [self.record("AAA", snapshot="snap-2")],
            ranking_as_of="2026-08-31",
        )
        self.assertNotEqual(one.universe_fingerprint, two.universe_fingerprint)

    def test_ranking_does_not_assign_or_mutate_band(self):
        row = self.record("AAA", band=None)
        result = rank_candidates([row], ranking_as_of="2026-08-31")
        self.assertIsNone(result.ranked[0].candidate.recommendation_band)

    def test_ranking_version_is_explicit(self):
        result = rank_candidates(
            [self.record("AAA")],
            ranking_as_of="2026-08-31",
        )
        self.assertEqual(result.ranking_version, CANDIDATE_RANKING_VERSION)


    def test_peer_group_ranking_is_deterministic_and_separate_from_overall(self):
        rows = [
            self.record("EQ2", score=70, peer_group="EQUITY"),
            self.record("SK1", score=60, peer_group="SUKUK"),
            self.record("EQ1", score=80, peer_group="EQUITY"),
            self.record("SK2", score=50, peer_group="SUKUK"),
        ]
        result = rank_candidates(rows, ranking_as_of="2026-08-31")
        self.assertEqual(
            [row.candidate.symbol for row in result.ranked],
            ["EQ1", "EQ2", "SK1", "SK2"],
        )
        self.assertEqual(
            [row.candidate.symbol for row in result.ranked_by_peer_group["EQUITY"]],
            ["EQ1", "EQ2"],
        )
        self.assertEqual(
            [row.candidate.symbol for row in result.ranked_by_peer_group["SUKUK"]],
            ["SK1", "SK2"],
        )

    def test_peer_group_changes_universe_fingerprint(self):
        one = rank_candidates(
            [self.record("AAA", peer_group="EQUITY")],
            ranking_as_of="2026-08-31",
        )
        two = rank_candidates(
            [self.record("AAA", peer_group="SUKUK")],
            ranking_as_of="2026-08-31",
        )
        self.assertNotEqual(one.universe_fingerprint, two.universe_fingerprint)

    def test_missing_peer_group_does_not_block_overall_ranking(self):
        result = rank_candidates(
            [self.record("AAA", peer_group=None)],
            ranking_as_of="2026-08-31",
        )
        self.assertEqual(result.ranked[0].candidate.symbol, "AAA")
        self.assertEqual(result.ranked_by_peer_group, {})


if __name__ == "__main__":
    unittest.main()
