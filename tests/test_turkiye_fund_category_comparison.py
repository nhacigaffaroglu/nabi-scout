from __future__ import annotations

import unittest

from services.turkiye_fund_category_comparison import (
    CategoryComparisonContractError,
    build_category_comparison_artifact,
)


def row(code, category, fi_rank, score, ret, dd):
    return {
        "fund_code": code,
        "fund_name": f"{code} Fund",
        "category": category,
        "category_rank": fi_rank,
        "candidate_rank": fi_rank,
        "fi_score": score,
        "fi_state": "WATCH",
        "return_1y": ret,
        "max_drawdown": dd,
        "data_completeness": 1.0,
        "confidence": 1.0,
        "fi_profile": "TEST",
        "peer_view": "TEST",
        "founder": "TEST",
    }


def artifact():
    groups = [
        {
            "category": "cash_like",
            "candidate_count": 1,
            "candidates": [row("AIS", "cash_like", 1, 70.39, 47.35, 0.0)],
        },
        {
            "category": "equity",
            "candidate_count": 3,
            "candidates": [
                row("GKV", "equity", 1, 82.33, 57.75, -8.66),
                row("TLZ", "equity", 2, 67.74, 52.12, -9.60),
                row("ZPE", "equity", 3, 66.32, 38.09, -10.92),
            ],
        },
        {
            "category": "multi_asset",
            "candidate_count": 1,
            "candidates": [row("BCO", "multi_asset", 1, 62.20, 74.16, -10.41)],
        },
        {
            "category": "sukuk",
            "candidate_count": 1,
            "candidates": [row("IAT", "sukuk", 1, 60.49, 40.76, -0.22)],
        },
    ]
    return {
        "schema_version": "fund15_category_research_artifact_1",
        "source": {
            "fund14b_schema_version": "fund14b_candidate_artifact_4",
            "threshold_policy": {
                "locked": True,
                "fi_min": 60.0,
                "source": "human_decision",
                "decision_id": "FUND14B-FI60-2026-09-11",
            },
        },
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "cross_category_winner": None,
        "cross_category_composite_score": None,
        "counts": {"promotion_eligible": 6, "categories": 4},
        "categories": groups,
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
        },
    }


class CategoryComparisonTests(unittest.TestCase):
    def build(self, data):
        return build_category_comparison_artifact(
            data,
            generated_at="2026-09-11T17:30:00Z",
        )

    def test_equity_metric_ranks_are_descriptive_and_deterministic(self):
        out = self.build(artifact())
        equity = next(g for g in out["categories"] if g["category"] == "equity")
        self.assertTrue(equity["peer_comparison_available"])
        self.assertEqual(
            [r["fund_code"] for r in equity["candidates"]],
            ["GKV", "TLZ", "ZPE"],
        )
        self.assertEqual(
            [r["return_1y_rank"] for r in equity["candidates"]],
            [1, 2, 3],
        )
        self.assertEqual(
            [r["drawdown_resilience_rank"] for r in equity["candidates"]],
            [1, 2, 3],
        )

    def test_singletons_do_not_fake_peer_rank(self):
        out = self.build(artifact())
        ais = next(g for g in out["categories"] if g["category"] == "cash_like")
        self.assertFalse(ais["peer_comparison_available"])
        self.assertIsNone(ais["candidates"][0]["return_1y_rank"])
        self.assertIsNone(ais["candidates"][0]["drawdown_resilience_rank"])

    def test_no_winner_composite_or_recommendation(self):
        out = self.build(artifact())
        self.assertIsNone(out["cross_category_winner"])
        self.assertIsNone(out["cross_category_composite_score"])
        self.assertIsNone(out["recommendation"])
        self.assertTrue(
            all(
                g["winner"] is None and g["composite_score"] is None
                for g in out["categories"]
            )
        )

    def test_counts(self):
        out = self.build(artifact())
        self.assertEqual(
            out["counts"],
            {
                "promotion_eligible": 6,
                "categories": 4,
                "peer_comparable_categories": 1,
            },
        )

    def test_threshold_must_be_locked(self):
        data = artifact()
        data["source"]["threshold_policy"]["locked"] = False
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_threshold_must_remain_fi60(self):
        data = artifact()
        data["source"]["threshold_policy"]["fi_min"] = 65.0
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_threshold_source_must_be_human_decision(self):
        data = artifact()
        data["source"]["threshold_policy"]["source"] = "automatic"
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_threshold_decision_id_must_match(self):
        data = artifact()
        data["source"]["threshold_policy"]["decision_id"] = "OTHER"
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_upstream_execution_fails_closed(self):
        data = artifact()
        data["execution_authority"] = True
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_upstream_write_fails_closed(self):
        data = artifact()
        data["write_proof"]["orders"] = 1
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_cross_category_winner_fails_closed(self):
        data = artifact()
        data["cross_category_winner"] = "GKV"
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_category_count_mismatch_fails_closed(self):
        data = artifact()
        data["counts"]["categories"] = 5
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_promotion_count_mismatch_fails_closed(self):
        data = artifact()
        data["counts"]["promotion_eligible"] = 7
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_category_rank_mismatch_fails_closed(self):
        data = artifact()
        data["categories"][1]["candidates"][1]["category_rank"] = 3
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_duplicate_candidate_fails_closed(self):
        data = artifact()
        data["categories"][1]["candidates"][1]["fund_code"] = "GKV"
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_category_mismatch_fails_closed(self):
        data = artifact()
        data["categories"][1]["candidates"][0]["category"] = "sukuk"
        with self.assertRaises(CategoryComparisonContractError):
            self.build(data)

    def test_missing_return_does_not_fail_and_has_no_metric_rank(self):
        data = artifact()
        data["categories"][1]["candidates"][1]["return_1y"] = None
        out = self.build(data)
        equity = next(g for g in out["categories"] if g["category"] == "equity")
        tlz = next(r for r in equity["candidates"] if r["fund_code"] == "TLZ")
        self.assertIsNone(tlz["return_1y_rank"])

    def test_write_proof_is_exact_zero(self):
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
