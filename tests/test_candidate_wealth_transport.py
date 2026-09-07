from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
import tempfile
import unittest
from pathlib import Path

from services.candidate_contract import (
    CandidateEligibility,
    CandidateRecord,
    CandidateSourceTrace,
    ELIGIBILITY_ELIGIBLE,
)
from services.candidate_ranking import rank_candidates
from services.candidate_wealth_export import build_wealth_candidate_feed
from services.candidate_wealth_facade import wealth_candidate_facade
from services.candidate_wealth_transport import (
    FRESHNESS_FRESH,
    FRESHNESS_FUTURE_DATED,
    FRESHNESS_STALE,
    WEALTH_TRANSPORT_VERSION,
    build_wealth_candidate_transport,
    evaluate_wealth_feed_freshness,
    require_wealth_feed_freshness,
    validate_wealth_candidate_transport,
    write_wealth_candidate_transport,
)


def feed(as_of="2026-08-31"):
    record = CandidateRecord(
        symbol="GKV",
        market="TR",
        instrument_type="FUND",
        total_score=81.96,
        confidence=0.9,
        intelligence_state="ATTRACTIVE",
        eligibility=CandidateEligibility(status=ELIGIBILITY_ELIGIBLE),
        source_trace=CandidateSourceTrace(
            analysis_snapshot_id="snap-gkv",
            analysis_as_of=as_of,
            score_version="fund_intelligence_1g.1",
            facts_version="fund_facts_1d.1",
        ),
        data_completeness=1.0,
        economic_exposure="equity",
        peer_group="EQUITY_PARTICIPATION_FUND",
    )
    ranking = rank_candidates([record], ranking_as_of=as_of)
    return build_wealth_candidate_feed(wealth_candidate_facade(ranking))


class CandidateWealthTransportTests(unittest.TestCase):
    def test_transport_hashes_exact_payload_json(self):
        envelope = build_wealth_candidate_transport(feed())
        self.assertEqual(envelope.envelope_version, WEALTH_TRANSPORT_VERSION)
        self.assertEqual(len(envelope.payload_sha256), 64)
        parsed = validate_wealth_candidate_transport(envelope)
        self.assertEqual(parsed.ranking_as_of, "2026-08-31")
        self.assertEqual(parsed.eligible[0]["peer_rank"], 1)
        self.assertEqual(
            parsed.eligible[0]["peer_group"],
            "EQUITY_PARTICIPATION_FUND",
        )

    def test_payload_tampering_is_rejected(self):
        envelope = build_wealth_candidate_transport(feed())
        bad = replace(
            envelope,
            payload_json=envelope.payload_json.replace("GKV", "BAD"),
        )
        with self.assertRaisesRegex(
            ValueError, "wealth_transport_payload_sha256_mismatch"
        ):
            validate_wealth_candidate_transport(bad)

    def test_hash_tampering_is_rejected(self):
        envelope = build_wealth_candidate_transport(feed())
        bad = replace(envelope, payload_sha256="0" * 64)
        with self.assertRaisesRegex(
            ValueError, "wealth_transport_payload_sha256_mismatch"
        ):
            validate_wealth_candidate_transport(bad)

    def test_freshness_requires_explicit_policy(self):
        result = evaluate_wealth_feed_freshness(
            feed(),
            reference_date=date(2026, 9, 2),
            max_age_days=2,
        )
        self.assertEqual(result.status, FRESHNESS_FRESH)
        self.assertTrue(result.acceptable)

    def test_stale_feed_is_identified_and_strict_gate_rejects(self):
        source = feed()
        result = evaluate_wealth_feed_freshness(
            source,
            reference_date=date(2026, 9, 3),
            max_age_days=2,
        )
        self.assertEqual(result.status, FRESHNESS_STALE)
        with self.assertRaisesRegex(ValueError, "wealth_feed_stale"):
            require_wealth_feed_freshness(
                source,
                reference_date=date(2026, 9, 3),
                max_age_days=2,
            )

    def test_future_dated_feed_is_rejected(self):
        source = feed(as_of="2026-09-10")
        result = evaluate_wealth_feed_freshness(
            source,
            reference_date=date(2026, 9, 6),
            max_age_days=30,
        )
        self.assertEqual(result.status, FRESHNESS_FUTURE_DATED)
        with self.assertRaisesRegex(ValueError, "wealth_feed_future_dated"):
            require_wealth_feed_freshness(
                source,
                reference_date=date(2026, 9, 6),
                max_age_days=30,
            )

    def test_negative_max_age_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError, "wealth_feed_max_age_days_must_be_nonnegative"
        ):
            evaluate_wealth_feed_freshness(
                feed(),
                reference_date=date(2026, 9, 1),
                max_age_days=-1,
            )

    def test_write_is_local_envelope_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_wealth_candidate_transport(
                feed(),
                output_path=Path(tmp) / "transport.json",
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["envelope_version"],
                WEALTH_TRANSPORT_VERSION,
            )
            self.assertEqual(len(payload["payload_sha256"]), 64)
            self.assertIsInstance(payload["payload_json"], str)


if __name__ == "__main__":
    unittest.main()
