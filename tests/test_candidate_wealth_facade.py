from __future__ import annotations

import unittest

from services.candidate_contract import (
    CandidateEligibility,
    CandidateRecord,
    CandidateSourceTrace,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_WATCH_ONLY,
)
from services.candidate_ranking import rank_candidates
from services.candidate_wealth_facade import (
    WEALTH_READ_ONLY_NOTICE,
    wealth_candidate_facade,
    wealth_candidate_lookup,
)


def record(symbol, *, score, eligibility, snapshot, peer_group="EQUITY"):
    return CandidateRecord(
        symbol=symbol,
        market="TR",
        instrument_type="FUND",
        total_score=score,
        confidence=.8,
        intelligence_state="ATTRACTIVE" if score is not None else "INSUFFICIENT_DATA",
        eligibility=CandidateEligibility(status=eligibility),
        source_trace=CandidateSourceTrace(
            analysis_snapshot_id=snapshot,
            analysis_as_of="2026-08-31",
            score_version="fund_intelligence_1g.1",
            facts_version="fund_facts_1d.1",
        ),
        data_completeness=1.0 if score is not None else None,
        economic_exposure="equity" if eligibility == ELIGIBILITY_ELIGIBLE else None,
        peer_group=peer_group,
    )


class CandidateWealthFacadeTests(unittest.TestCase):
    def ranking(self):
        return rank_candidates(
            [
                record("GKV", score=81.96, eligibility=ELIGIBILITY_ELIGIBLE, snapshot="g"),
                record("WWW", score=70.0, eligibility=ELIGIBILITY_WATCH_ONLY, snapshot="w"),
                record("CPU", score=None, eligibility=ELIGIBILITY_INELIGIBLE, snapshot="c"),
            ],
            ranking_as_of="2026-08-31",
        )

    def test_facade_preserves_ranking_identity(self):
        ranking = self.ranking()
        facade = wealth_candidate_facade(ranking)
        self.assertEqual(facade.ranking_version, ranking.ranking_version)
        self.assertEqual(facade.ranking_as_of, ranking.ranking_as_of)
        self.assertEqual(facade.universe_fingerprint, ranking.universe_fingerprint)

    def test_eligible_rank_is_preserved(self):
        facade = wealth_candidate_facade(self.ranking())
        self.assertEqual(facade.eligible[0].symbol, "GKV")
        self.assertEqual(facade.eligible[0].rank, 1)
        self.assertEqual(facade.eligible[0].peer_rank, 1)
        self.assertEqual(facade.eligible[0].peer_group, "EQUITY")

    def test_watch_and_ineligible_are_not_given_rank(self):
        facade = wealth_candidate_facade(self.ranking())
        self.assertIsNone(facade.watch_only[0].rank)
        self.assertIsNone(facade.watch_only[0].peer_rank)
        self.assertIsNone(facade.ineligible[0].rank)
        self.assertIsNone(facade.ineligible[0].peer_rank)

    def test_lookup_is_read_only_projection(self):
        facade = wealth_candidate_facade(self.ranking())
        row = wealth_candidate_lookup(facade, "gkv")
        self.assertIsNotNone(row)
        self.assertEqual(row.analysis_snapshot_id, "g")

    def test_facade_rows_have_no_execution_fields(self):
        payload = wealth_candidate_facade(self.ranking()).to_dict()
        forbidden = {
            "target_weight",
            "position_size",
            "quantity",
            "trade",
            "new_money_amount",
            "allocation",
        }
        for bucket in ("eligible", "watch_only", "ineligible"):
            for row in payload[bucket]:
                self.assertTrue(forbidden.isdisjoint(row.keys()))

    def test_facade_top_level_has_no_execution_fields(self):
        payload = wealth_candidate_facade(self.ranking()).to_dict()
        forbidden = {
            "target_weight",
            "position_size",
            "quantity",
            "trade",
            "new_money_amount",
            "allocation",
        }
        self.assertTrue(forbidden.isdisjoint(payload.keys()))

    def test_notice_denies_execution_authority(self):
        facade = wealth_candidate_facade(self.ranking())
        self.assertEqual(facade.notice, WEALTH_READ_ONLY_NOTICE)
        self.assertIn("Read-only", facade.notice)
        self.assertIn("No allocation", facade.notice)


    def test_peer_rank_can_differ_from_overall_rank(self):
        ranking = rank_candidates(
            [
                record("EQ", score=80, eligibility=ELIGIBILITY_ELIGIBLE, snapshot="eq", peer_group="EQUITY"),
                record("SK1", score=70, eligibility=ELIGIBILITY_ELIGIBLE, snapshot="s1", peer_group="SUKUK"),
                record("SK2", score=60, eligibility=ELIGIBILITY_ELIGIBLE, snapshot="s2", peer_group="SUKUK"),
            ],
            ranking_as_of="2026-08-31",
        )
        facade = wealth_candidate_facade(ranking)
        sk1 = wealth_candidate_lookup(facade, "SK1")
        self.assertEqual(sk1.rank, 2)
        self.assertEqual(sk1.peer_rank, 1)


if __name__ == "__main__":
    unittest.main()
