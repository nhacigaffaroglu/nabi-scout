from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.candidate_contract import (
    CandidateEligibility,
    CandidateRecord,
    CandidateSourceTrace,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_WATCH_ONLY,
)
from services.candidate_ranking import rank_candidates
from services.candidate_wealth_export import (
    FORBIDDEN_EXECUTION_KEYS,
    WEALTH_FEED_AUTHORITY,
    WEALTH_FEED_SCHEMA_VERSION,
    build_wealth_candidate_feed,
    validate_wealth_candidate_feed,
    write_wealth_candidate_feed,
)
from services.candidate_wealth_facade import wealth_candidate_facade


def record(symbol, score, eligibility, snapshot):
    return CandidateRecord(
        symbol=symbol,
        market="TR",
        instrument_type="FUND",
        total_score=score,
        confidence=0.9,
        intelligence_state=(
            "ATTRACTIVE" if score is not None else "INSUFFICIENT_DATA"
        ),
        eligibility=CandidateEligibility(status=eligibility),
        source_trace=CandidateSourceTrace(
            analysis_snapshot_id=snapshot,
            analysis_as_of="2026-08-31",
            score_version="fund_intelligence_1g.1",
            facts_version="fund_facts_1d.1",
        ),
        data_completeness=1.0 if score is not None else None,
        economic_exposure=(
            "equity" if eligibility == ELIGIBILITY_ELIGIBLE else None
        ),
        peer_group=(
            "EQUITY_PARTICIPATION_FUND"
            if eligibility == ELIGIBILITY_ELIGIBLE
            else None
        ),
    )


def facade():
    ranking = rank_candidates(
        [
            record("GKV", 81.96, ELIGIBILITY_ELIGIBLE, "g"),
            record("WWW", 70.0, ELIGIBILITY_WATCH_ONLY, "w"),
            record("CPU", None, ELIGIBILITY_INELIGIBLE, "c"),
        ],
        ranking_as_of="2026-08-31",
    )
    return wealth_candidate_facade(ranking)


class CandidateWealthExportTests(unittest.TestCase):
    def test_feed_is_research_only(self):
        feed = build_wealth_candidate_feed(facade())
        self.assertTrue(feed.research_only)
        self.assertEqual(feed.authority, WEALTH_FEED_AUTHORITY)
        self.assertEqual(feed.schema_version, WEALTH_FEED_SCHEMA_VERSION)

    def test_feed_preserves_ranking_identity(self):
        source = facade()
        feed = build_wealth_candidate_feed(source)
        self.assertEqual(feed.ranking_version, source.ranking_version)
        self.assertEqual(feed.ranking_as_of, source.ranking_as_of)
        self.assertEqual(
            feed.universe_fingerprint,
            source.universe_fingerprint,
        )

    def test_export_fingerprint_is_deterministic(self):
        one = build_wealth_candidate_feed(facade())
        two = build_wealth_candidate_feed(facade())
        self.assertEqual(one.export_fingerprint, two.export_fingerprint)
        self.assertEqual(len(one.export_fingerprint), 64)

    def test_no_execution_fields_exist(self):
        payload = build_wealth_candidate_feed(facade()).to_dict()

        def keys(value):
            result = set()
            if isinstance(value, dict):
                result.update(value)
                for item in value.values():
                    result.update(keys(item))
            elif isinstance(value, (list, tuple)):
                for item in value:
                    result.update(keys(item))
            return result

        self.assertTrue(FORBIDDEN_EXECUTION_KEYS.isdisjoint(keys(payload)))

    def test_write_is_local_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_wealth_candidate_feed(
                facade(),
                output_path=Path(tmp) / "feed.json",
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(payload["research_only"])
            self.assertEqual(
                payload["eligible"][0]["analysis_snapshot_id"],
                "g",
            )
            self.assertEqual(payload["eligible"][0]["peer_rank"], 1)
            self.assertEqual(
                payload["eligible"][0]["peer_group"],
                "EQUITY_PARTICIPATION_FUND",
            )


    def test_feed_preserves_peer_context_without_execution_authority(self):
        feed = build_wealth_candidate_feed(facade())
        row = feed.eligible[0]
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["peer_rank"], 1)
        self.assertEqual(row["peer_group"], "EQUITY_PARTICIPATION_FUND")

    def test_validation_rejects_tampered_fingerprint(self):
        feed = build_wealth_candidate_feed(facade())
        payload = feed.to_dict()
        payload["export_fingerprint"] = "0" * 64

        from services.candidate_wealth_export import WealthCandidateFeed

        bad = WealthCandidateFeed(**payload)
        with self.assertRaisesRegex(
            ValueError, "wealth_feed_export_fingerprint_mismatch"
        ):
            validate_wealth_candidate_feed(bad)


if __name__ == "__main__":
    unittest.main()
