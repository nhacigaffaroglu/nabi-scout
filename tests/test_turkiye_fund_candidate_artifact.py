from __future__ import annotations

import copy
import math
import unittest

from services.turkiye_fund_candidate_artifact import (
    CandidateArtifactContractError,
    DEFAULT_EXPECTED_SOURCE_HEAD,
    build_candidate_artifact,
)


def row(
    code: str,
    *,
    status: str = "READY",
    participation: str = "Uygun",
    research_allowed: bool = True,
    fi_score=80.0,
    completeness=1.0,
    confidence=0.9,
):
    return {
        "fund_code": code,
        "fund_name": f"{code} Test Fund",
        "category": "TEST",
        "rank": None,
        "fi_score": fi_score,
        "fi_state": "NEUTRAL",
        "confidence": confidence,
        "participation": participation,
        "research_allowed": research_allowed,
        "exposure": "MIXED",
        "return_1y": 0.1,
        "max_drawdown": -0.05,
        "data_completeness": completeness,
        "scanner_status": status,
        "universe_states": ["DISCOVERED", "ACTIVE", "SCANNABLE"],
        "reason": "test",
        "missing_evidence": [],
        "fi_profile": "TEST",
        "peer_view": "PEER_CATEGORY",
        "founder": "TEST",
    }


def snapshot(rows=None):
    return {
        "schema_version": "fund14a_research_snapshot_3",
        "source_head": DEFAULT_EXPECTED_SOURCE_HEAD,
        "as_of": "2026-09-08",
        "calculated_at": "2026-09-08T12:00:00Z",
        "research_only": True,
        "thresholds_proposed": False,
        "thresholds_locked": False,
        "activation_safe": True,
        "participation_baseline_delta": {
            "baseline_count": 14,
            "current_count": 14,
            "added": [],
            "removed": [],
            "manual_review_required": False,
        },
        "write_proof": {
            "persist": False,
            "production_writes": [],
            "eight_e_calls": 0,
            "new_money_calls": 0,
            "trades": 0,
            "portfolio_writes": 0,
        },
        "scanner": {"rows": list(rows or [])},
    }


class CandidateArtifactTests(unittest.TestCase):
    def build(self, snap, **kwargs):
        return build_candidate_artifact(
            snap,
            generated_at="2026-09-08T12:01:00Z",
            **kwargs,
        )

    def test_default_threshold_is_unlocked_and_promotes_nothing(self):
        art = self.build(snapshot([row("AAA")]))
        self.assertEqual(art["counts"]["eligible_candidates"], 1)
        self.assertEqual(art["promotion_eligible"], [])
        self.assertFalse(art["promotion_gate"]["open"])
        self.assertIn("THRESHOLD_UNLOCKED", art["promotion_gate"]["reasons"])

    def test_ready_uygun_research_allowed_numeric_fi_is_candidate(self):
        art = self.build(snapshot([row("AAA")]))
        self.assertEqual([x["fund_code"] for x in art["candidates"]], ["AAA"])

    def test_not_ready_is_excluded(self):
        art = self.build(snapshot([row("AAA", status="REVIEW_REQUIRED")]))
        self.assertEqual(art["candidates"], [])
        self.assertIn(
            "SCANNER_NOT_READY",
            art["excluded"][0]["exclusion_reasons"],
        )

    def test_not_uygun_is_excluded(self):
        art = self.build(snapshot([row("AAA", participation="Kontrol Et")]))
        self.assertEqual(art["candidates"], [])
        self.assertIn(
            "PARTICIPATION_NOT_UYGUN",
            art["excluded"][0]["exclusion_reasons"],
        )

    def test_research_not_allowed_is_excluded(self):
        art = self.build(snapshot([row("AAA", research_allowed=False)]))
        self.assertEqual(art["candidates"], [])
        self.assertIn(
            "RESEARCH_NOT_ALLOWED",
            art["excluded"][0]["exclusion_reasons"],
        )

    def test_missing_fi_is_excluded(self):
        art = self.build(snapshot([row("AAA", fi_score=None)]))
        self.assertEqual(art["candidates"], [])
        self.assertIn(
            "FI_SCORE_NOT_PUBLISHABLE",
            art["excluded"][0]["exclusion_reasons"],
        )

    def test_nan_fi_is_excluded(self):
        art = self.build(snapshot([row("AAA", fi_score=float("nan"))]))
        self.assertEqual(art["candidates"], [])

    def test_rank_matches_scanner_contract(self):
        rows = [
            row("CCC", fi_score=90, completeness=.8, confidence=.9),
            row("BBB", fi_score=90, completeness=.9, confidence=.8),
            row("AAA", fi_score=90, completeness=.9, confidence=.9),
            row("DDD", fi_score=80, completeness=1.0, confidence=1.0),
        ]
        art = self.build(snapshot(rows))
        self.assertEqual(
            [x["fund_code"] for x in art["candidates"]],
            ["AAA", "BBB", "CCC", "DDD"],
        )

    def test_unsafe_upstream_closes_locked_gate(self):
        snap = snapshot([row("AAA", fi_score=90)])
        snap["activation_safe"] = False
        art = self.build(
            snap,
            threshold_policy={
                "locked": True,
                "fi_min": 80,
                "source": "human_decision",
                "decision_id": "TEST-1",
            },
        )
        self.assertFalse(art["promotion_gate"]["open"])
        self.assertIn(
            "UPSTREAM_ACTIVATION_UNSAFE",
            art["promotion_gate"]["reasons"],
        )
        self.assertEqual(art["promotion_eligible"], [])

    def test_baseline_delta_closes_locked_gate(self):
        snap = snapshot([row("AAA", fi_score=90)])
        snap["participation_baseline_delta"]["added"] = ["NEW"]
        snap["participation_baseline_delta"]["current_count"] = 15
        snap["participation_baseline_delta"]["manual_review_required"] = True
        art = self.build(
            snap,
            threshold_policy={
                "locked": True,
                "fi_min": 80,
                "source": "human_decision",
                "decision_id": "TEST-2",
            },
        )
        self.assertFalse(art["promotion_gate"]["open"])
        self.assertIn(
            "PARTICIPATION_BASELINE_REVIEW_REQUIRED",
            art["promotion_gate"]["reasons"],
        )

    def test_locked_threshold_requires_source_and_decision(self):
        with self.assertRaises(CandidateArtifactContractError):
            self.build(
                snapshot([row("AAA")]),
                threshold_policy={"locked": True, "fi_min": 80},
            )

    def test_unlocked_threshold_cannot_smuggle_value(self):
        with self.assertRaises(CandidateArtifactContractError):
            self.build(
                snapshot([row("AAA")]),
                threshold_policy={"locked": False, "fi_min": 80},
            )

    def test_locked_clean_gate_filters_research_promotions(self):
        art = self.build(
            snapshot([row("AAA", fi_score=90), row("BBB", fi_score=70)]),
            threshold_policy={
                "locked": True,
                "fi_min": 80,
                "source": "human_decision",
                "decision_id": "TEST-3",
            },
        )
        self.assertTrue(art["promotion_gate"]["open"])
        self.assertEqual(
            [x["fund_code"] for x in art["promotion_eligible"]],
            ["AAA"],
        )
        self.assertFalse(art["execution_authority"])

    def test_upstream_production_write_fails_closed(self):
        snap = snapshot([row("AAA")])
        snap["write_proof"]["production_writes"] = ["x"]
        with self.assertRaises(CandidateArtifactContractError):
            self.build(snap)

    def test_upstream_trade_fails_closed(self):
        snap = snapshot([row("AAA")])
        snap["write_proof"]["trades"] = 1
        with self.assertRaises(CandidateArtifactContractError):
            self.build(snap)

    def test_source_head_is_pinned(self):
        snap = snapshot([row("AAA")])
        snap["source_head"] = "deadbeef"
        with self.assertRaises(CandidateArtifactContractError):
            self.build(snap)

    def test_explicit_source_pin_disable_still_keeps_schema_firewall(self):
        snap = snapshot([row("AAA")])
        snap["source_head"] = "future-add-only-head"
        art = self.build(snap, expected_source_head=None)
        self.assertEqual(art["source"]["source_head"], "future-add-only-head")

    def test_duplicate_code_fails_closed(self):
        with self.assertRaises(CandidateArtifactContractError):
            self.build(snapshot([row("AAA"), row("AAA")]))

    def test_noncanonical_symbol_is_not_autocorrected(self):
        with self.assertRaises(CandidateArtifactContractError):
            self.build(snapshot([row("aaa")]))

    def test_output_write_proof_is_zero(self):
        art = self.build(snapshot([row("AAA")]))
        self.assertEqual(
            art["write_proof"],
            {
                "production_writes": 0,
                "trade_actions": 0,
                "orders": 0,
                "portfolio_writes": 0,
                "eight_e_calls": 0,
                "new_money_calls": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
