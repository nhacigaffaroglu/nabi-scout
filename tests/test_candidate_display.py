from __future__ import annotations

import unittest

from services.candidate_contract import (
    CandidateEligibility,
    CandidateRecord,
    CandidateSourceTrace,
    RankedCandidate,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
)
from services.candidate_display import (
    RESEARCH_ONLY_NOTICE,
    candidate_card,
    compare_candidates,
    ranked_candidate_card,
)


def record(
    symbol="GKV",
    *,
    score=81.96,
    eligibility=ELIGIBILITY_ELIGIBLE,
    band=None,
    snapshot="snap-GKV",
):
    return CandidateRecord(
        symbol=symbol,
        market="TR",
        instrument_type="FUND",
        total_score=score,
        confidence=.9,
        intelligence_state="ATTRACTIVE",
        eligibility=CandidateEligibility(
            status=eligibility,
            reasons=() if eligibility == ELIGIBILITY_ELIGIBLE else ("BLOCKED",),
        ),
        source_trace=CandidateSourceTrace(
            analysis_snapshot_id=snapshot,
            analysis_as_of="2026-08-31",
            score_version="fund_intelligence_1g.1",
            facts_version="fund_facts_1d.1",
            source_provenance=("TEFAS", "KAP"),
        ),
        recommendation_band=band,
        data_completeness=1.0,
        economic_exposure="equity",
        peer_group="EQUITY_PARTICIPATION_FUND",
        sub_scores=(("PERFORMANCE", 88.0), ("RISK", 72.0)),
        top_drivers=("PERFORMANCE",),
        top_risks=("RISK",),
        limitations=("RESEARCH_ONLY",),
    )


class CandidateDisplayTests(unittest.TestCase):
    def test_card_preserves_snapshot_and_versions(self):
        card = candidate_card(record())
        self.assertEqual(card.analysis_snapshot_id, "snap-GKV")
        self.assertEqual(card.score_version, "fund_intelligence_1g.1")
        self.assertEqual(card.facts_version, "fund_facts_1d.1")
        self.assertEqual(card.peer_group, "EQUITY_PARTICIPATION_FUND")

    def test_card_does_not_invent_band(self):
        card = candidate_card(record(band=None))
        self.assertIsNone(card.recommendation_band)

    def test_ranked_card_preserves_rank(self):
        card = ranked_candidate_card(RankedCandidate(rank=3, candidate=record()))
        self.assertEqual(card.rank, 3)

    def test_ineligible_card_preserves_reasons(self):
        card = candidate_card(record(eligibility=ELIGIBILITY_INELIGIBLE))
        self.assertEqual(card.eligibility_status, ELIGIBILITY_INELIGIBLE)
        self.assertEqual(card.eligibility_reasons, ("BLOCKED",))

    def test_research_only_notice_is_explicit(self):
        card = candidate_card(record())
        self.assertEqual(card.notice, RESEARCH_ONLY_NOTICE)
        self.assertIn("Not a buy", card.notice)
        self.assertIn("portfolio instruction", card.notice)

    def test_comparison_preserves_input_order(self):
        comparison = compare_candidates([
            RankedCandidate(rank=1, candidate=record("AAA", score=90, snapshot="a")),
            RankedCandidate(rank=2, candidate=record("BBB", score=80, snapshot="b")),
        ])
        self.assertEqual([r.symbol for r in comparison.rows], ["AAA", "BBB"])
        self.assertEqual([r.rank for r in comparison.rows], [1, 2])
        self.assertTrue(all(r.peer_group == "EQUITY_PARTICIPATION_FUND" for r in comparison.rows))

    def test_comparison_has_no_action_fields(self):
        payload = compare_candidates([record()]).to_dict()
        serialized_keys = set(payload["rows"][0])
        self.assertNotIn("buy", serialized_keys)
        self.assertNotIn("sell", serialized_keys)
        self.assertNotIn("allocation", serialized_keys)
        self.assertNotIn("position_size", serialized_keys)


if __name__ == "__main__":
    unittest.main()
