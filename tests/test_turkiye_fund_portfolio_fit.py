from __future__ import annotations

import unittest

from services.turkiye_fund_portfolio_fit import (
    PortfolioFitContractError,
    build_portfolio_fit_artifact,
)


def candidate(code, category, score, ret, ret_rank, dd, dd_rank):
    return {
        "fund_code": code,
        "fund_name": f"{code} Fund",
        "category": category,
        "fi_score": score,
        "fi_state": "WATCH",
        "fi_category_rank": 1,
        "return_1y": ret,
        "return_1y_rank": ret_rank,
        "max_drawdown": dd,
        "drawdown_resilience_rank": dd_rank,
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
            "peer_comparison_available": False,
            "winner": None,
            "composite_score": None,
            "candidates": [candidate("AIS", "cash_like", 70.39, 47.35, None, 0.0, None)],
        },
        {
            "category": "equity",
            "candidate_count": 3,
            "peer_comparison_available": True,
            "winner": None,
            "composite_score": None,
            "candidates": [
                candidate("GKV", "equity", 82.33, 57.75, 1, -8.66, 1),
                candidate("TLZ", "equity", 67.74, 52.12, 2, -9.60, 2),
                candidate("ZPE", "equity", 66.32, 38.09, 3, -10.92, 3),
            ],
        },
        {
            "category": "multi_asset",
            "candidate_count": 1,
            "peer_comparison_available": False,
            "winner": None,
            "composite_score": None,
            "candidates": [candidate("BCO", "multi_asset", 62.20, 74.16, None, -10.41, None)],
        },
        {
            "category": "sukuk",
            "candidate_count": 1,
            "peer_comparison_available": False,
            "winner": None,
            "composite_score": None,
            "candidates": [candidate("IAT", "sukuk", 60.49, 40.76, None, -0.22, None)],
        },
    ]
    return {
        "schema_version": "fund16_category_comparison_artifact_1",
        "source": {
            "fund15_schema_version": "fund15_category_research_artifact_1",
            "source": {
                "fund14b_schema_version": "fund14b_candidate_artifact_4",
                "threshold_policy": {
                    "locked": True,
                    "fi_min": 60.0,
                    "source": "human_decision",
                    "decision_id": "FUND14B-FI60-2026-09-11",
                },
            },
        },
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "cross_category_winner": None,
        "cross_category_composite_score": None,
        "recommendation": None,
        "counts": {
            "promotion_eligible": 6,
            "categories": 4,
            "peer_comparable_categories": 1,
        },
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


def context():
    return {
        "schema_version": "fund17_portfolio_context_1",
        "human_supplied": True,
        "research_only": True,
        "execution_authority": False,
        "desired_roles": ["safety", "core_growth"],
        "existing_exposures": ["equity", "sukuk"],
        "constraints": ["research_only"],
        "notes": "fixture only",
    }


class PortfolioFitTests(unittest.TestCase):
    def build(self, data, ctx=None):
        return build_portfolio_fit_artifact(
            data,
            portfolio_context=ctx,
            generated_at="2026-09-11T18:00:00Z",
        )

    def test_missing_context_fails_closed_as_research_status_not_exception(self):
        out = self.build(artifact())
        self.assertFalse(out["portfolio_context_available"])
        self.assertEqual(out["portfolio_fit_status"], "PORTFOLIO_CONTEXT_REQUIRED")
        self.assertEqual(out["counts"]["context_required"], 6)
        self.assertEqual(out["counts"]["context_ready"], 0)
        self.assertTrue(
            all(c["portfolio_fit_status"] == "PORTFOLIO_CONTEXT_REQUIRED" for c in out["candidates"])
        )

    def test_context_enables_only_research_readiness(self):
        out = self.build(artifact(), context())
        self.assertTrue(out["portfolio_context_available"])
        self.assertEqual(out["portfolio_fit_status"], "READY_FOR_PORTFOLIO_FIT_RESEARCH")
        self.assertEqual(out["counts"]["context_ready"], 6)
        self.assertTrue(
            all(c["portfolio_fit_status"] == "READY_FOR_PORTFOLIO_FIT_RESEARCH" for c in out["candidates"])
        )

    def test_no_fit_values_are_invented(self):
        out = self.build(artifact(), context())
        for c in out["candidates"]:
            self.assertIsNone(c["role_fit"])
            self.assertIsNone(c["economic_overlap"])
            self.assertIsNone(c["diversification_contribution"])
            self.assertIsNone(c["concentration_risk"])

    def test_no_composite_rank_winner_or_recommendation(self):
        out = self.build(artifact(), context())
        self.assertIsNone(out["portfolio_fit_winner"])
        self.assertIsNone(out["portfolio_fit_composite_score"])
        self.assertIsNone(out["recommendation"])
        for c in out["candidates"]:
            self.assertIsNone(c["portfolio_fit_composite_score"])
            self.assertIsNone(c["portfolio_fit_rank"])
            self.assertIsNone(c["recommendation"])

    def test_preserves_fund16_descriptive_metrics(self):
        out = self.build(artifact())
        equity = [c for c in out["candidates"] if c["category"] == "equity"]
        self.assertEqual([c["fund_code"] for c in equity], ["GKV", "TLZ", "ZPE"])
        self.assertEqual([c["return_1y_rank"] for c in equity], [1, 2, 3])
        self.assertEqual([c["drawdown_resilience_rank"] for c in equity], [1, 2, 3])

    def test_bad_upstream_schema_fails_closed(self):
        data = artifact()
        data["schema_version"] = "other"
        with self.assertRaises(PortfolioFitContractError):
            self.build(data)

    def test_upstream_execution_fails_closed(self):
        data = artifact()
        data["execution_authority"] = True
        with self.assertRaises(PortfolioFitContractError):
            self.build(data)

    def test_upstream_recommendation_fails_closed(self):
        data = artifact()
        data["recommendation"] = "BUY"
        with self.assertRaises(PortfolioFitContractError):
            self.build(data)

    def test_upstream_write_fails_closed(self):
        data = artifact()
        data["write_proof"]["orders"] = 1
        with self.assertRaises(PortfolioFitContractError):
            self.build(data)

    def test_threshold_must_remain_fi60_human_locked(self):
        data = artifact()
        data["source"]["source"]["threshold_policy"]["fi_min"] = 65.0
        with self.assertRaises(PortfolioFitContractError):
            self.build(data)

    def test_context_schema_must_match(self):
        ctx = context()
        ctx["schema_version"] = "other"
        with self.assertRaises(PortfolioFitContractError):
            self.build(artifact(), ctx)

    def test_context_must_be_human_supplied(self):
        ctx = context()
        ctx["human_supplied"] = False
        with self.assertRaises(PortfolioFitContractError):
            self.build(artifact(), ctx)

    def test_context_cannot_grant_execution_authority(self):
        ctx = context()
        ctx["execution_authority"] = True
        with self.assertRaises(PortfolioFitContractError):
            self.build(artifact(), ctx)

    def test_duplicate_candidate_fails_closed(self):
        data = artifact()
        data["categories"][1]["candidates"][1]["fund_code"] = "GKV"
        with self.assertRaises(PortfolioFitContractError):
            self.build(data)

    def test_write_proof_exact_zero(self):
        out = self.build(artifact(), context())
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
