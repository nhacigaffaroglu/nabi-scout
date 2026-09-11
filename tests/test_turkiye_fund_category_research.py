from __future__ import annotations

import copy
import unittest

from services.turkiye_fund_category_research import (
    CategoryResearchContractError,
    build_category_research_artifact,
)


def candidate(code: str, category: str, score: float, rank: int):
    return {
        "fund_code": code,
        "fund_name": f"{code} Fund",
        "category": category,
        "candidate_rank": rank,
        "fi_score": score,
        "fi_state": "NEUTRAL",
        "return_1y": 10.0 + rank,
        "max_drawdown": -float(rank),
        "data_completeness": 1.0,
        "confidence": 1.0,
        "fi_profile": "TEST",
        "peer_view": "TEST",
        "founder": "TEST",
    }


def artifact():
    rows = [
        candidate("GKV", "equity", 82.33, 1),
        candidate("AIS", "cash_like", 70.39, 2),
        candidate("TLZ", "equity", 67.74, 3),
        candidate("ZPE", "equity", 66.32, 4),
        candidate("BCO", "multi_asset", 62.20, 5),
        candidate("IAT", "sukuk", 60.49, 6),
    ]
    return {
        "schema_version": "fund14b_candidate_artifact_4",
        "source": {"source_head": "abc"},
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "candidates": rows,
        "threshold_policy": {
            "locked": True,
            "fi_min": 60.0,
            "source": "human_decision",
            "decision_id": "FUND14B-FI60-2026-09-11",
        },
        "promotion_gate": {
            "open": True,
            "reasons": [],
            "meaning": "research_candidate_promotion_only",
            "execution_authority": False,
        },
        "promotion_eligible": [
            {"fund_code": x["fund_code"], "candidate_rank": x["candidate_rank"], "fi_score": x["fi_score"]}
            for x in rows
        ],
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
        },
    }


class CategoryResearchTests(unittest.TestCase):
    def build(self, payload):
        return build_category_research_artifact(
            payload,
            generated_at="2026-09-11T16:30:00Z",
        )

    def test_groups_promoted_candidates_by_category(self):
        out = self.build(artifact())
        groups = {x["category"]: [r["fund_code"] for r in x["candidates"]] for x in out["categories"]}
        self.assertEqual(groups["equity"], ["GKV", "TLZ", "ZPE"])
        self.assertEqual(groups["cash_like"], ["AIS"])
        self.assertEqual(groups["multi_asset"], ["BCO"])
        self.assertEqual(groups["sukuk"], ["IAT"])

    def test_category_rank_is_deterministic(self):
        out = self.build(artifact())
        equity = next(x for x in out["categories"] if x["category"] == "equity")
        self.assertEqual([x["category_rank"] for x in equity["candidates"]], [1, 2, 3])

    def test_no_cross_category_winner_or_composite_score(self):
        out = self.build(artifact())
        self.assertIsNone(out["cross_category_winner"])
        self.assertIsNone(out["cross_category_composite_score"])

    def test_upstream_gate_must_be_open(self):
        data = artifact()
        data["promotion_gate"]["open"] = False
        with self.assertRaises(CategoryResearchContractError):
            self.build(data)

    def test_threshold_must_be_locked(self):
        data = artifact()
        data["threshold_policy"]["locked"] = False
        with self.assertRaises(CategoryResearchContractError):
            self.build(data)

    def test_execution_authority_fails_closed(self):
        data = artifact()
        data["execution_authority"] = True
        with self.assertRaises(CategoryResearchContractError):
            self.build(data)

    def test_production_persist_fails_closed(self):
        data = artifact()
        data["production_persist"] = True
        with self.assertRaises(CategoryResearchContractError):
            self.build(data)

    def test_upstream_write_fails_closed(self):
        data = artifact()
        data["write_proof"]["orders"] = 1
        with self.assertRaises(CategoryResearchContractError):
            self.build(data)

    def test_promotion_must_exist_in_candidates(self):
        data = artifact()
        data["promotion_eligible"].append({"fund_code": "XXX", "candidate_rank": 7, "fi_score": 61.0})
        with self.assertRaises(CategoryResearchContractError):
            self.build(data)

    def test_promotion_score_must_match_candidate(self):
        data = artifact()
        data["promotion_eligible"][0]["fi_score"] = 99.0
        with self.assertRaises(CategoryResearchContractError):
            self.build(data)

    def test_duplicate_promotion_fails_closed(self):
        data = artifact()
        data["promotion_eligible"].append(copy.deepcopy(data["promotion_eligible"][0]))
        with self.assertRaises(CategoryResearchContractError):
            self.build(data)

    def test_noncanonical_code_fails_closed(self):
        data = artifact()
        data["candidates"][0]["fund_code"] = "gkv"
        with self.assertRaises(CategoryResearchContractError):
            self.build(data)

    def test_write_proof_is_zero(self):
        out = self.build(artifact())
        self.assertEqual(
            out["write_proof"],
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
