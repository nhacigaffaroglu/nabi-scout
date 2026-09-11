import unittest

from services.turkiye_fund_portfolio_context_bridge import (
    PortfolioContextBridgeError,
    build_fund17_portfolio_context,
)
from services.turkiye_fund_portfolio_fit import build_portfolio_fit_artifact


def valid_source():
    return {
        "schema_version": "fund17b_portfolio_context_source_1",
        "human_approved": True,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "source_system": "NABI_WEALTH_OS",
        "as_of": "2026-09-11T18:00:00Z",
        "desired_roles": [
            "portfolio diversification",
            "defensive ballast",
        ],
        "existing_exposures": [
            "US large-cap growth",
            "BIST equities",
            "participation funds",
        ],
        "constraints": [
            "research only",
            "no execution authority",
        ],
        "notes": "Explicit human-approved research context.",
    }


class PortfolioContextBridgeTests(unittest.TestCase):
    def test_valid_source_builds_exact_fund17_context(self):
        result = build_fund17_portfolio_context(valid_source())

        self.assertEqual(
            result["schema_version"],
            "fund17_portfolio_context_1",
        )
        self.assertIs(result["human_supplied"], True)
        self.assertIs(result["research_only"], True)
        self.assertIs(result["execution_authority"], False)
        self.assertEqual(
            result["desired_roles"],
            valid_source()["desired_roles"],
        )
        self.assertEqual(
            result["existing_exposures"],
            valid_source()["existing_exposures"],
        )
        self.assertEqual(
            result["constraints"],
            valid_source()["constraints"],
        )

    def test_no_execution_fields_are_created(self):
        result = build_fund17_portfolio_context(valid_source())

        self.assertNotIn("recommendation", result)
        self.assertNotIn("portfolio_fit_score", result)
        self.assertNotIn("portfolio_fit_rank", result)
        self.assertNotIn("trade_actions", result)
        self.assertNotIn("orders", result)

    def test_wrong_schema_fails_closed(self):
        source = valid_source()
        source["schema_version"] = "wrong"
        with self.assertRaisesRegex(
            PortfolioContextBridgeError,
            "unsupported_source_schema",
        ):
            build_fund17_portfolio_context(source)

    def test_human_approval_is_required(self):
        source = valid_source()
        source["human_approved"] = False
        with self.assertRaisesRegex(
            PortfolioContextBridgeError,
            "source_not_human_approved",
        ):
            build_fund17_portfolio_context(source)

    def test_research_only_is_required(self):
        source = valid_source()
        source["research_only"] = False
        with self.assertRaisesRegex(
            PortfolioContextBridgeError,
            "source_research_only_not_true",
        ):
            build_fund17_portfolio_context(source)

    def test_execution_authority_must_be_false(self):
        source = valid_source()
        source["execution_authority"] = True
        with self.assertRaisesRegex(
            PortfolioContextBridgeError,
            "source_execution_authority_not_false",
        ):
            build_fund17_portfolio_context(source)

    def test_production_persist_must_be_false(self):
        source = valid_source()
        source["production_persist"] = True
        with self.assertRaisesRegex(
            PortfolioContextBridgeError,
            "source_production_persist_not_false",
        ):
            build_fund17_portfolio_context(source)

    def test_source_system_required(self):
        source = valid_source()
        source["source_system"] = ""
        with self.assertRaisesRegex(
            PortfolioContextBridgeError,
            "source_system_invalid",
        ):
            build_fund17_portfolio_context(source)

    def test_as_of_must_be_valid_iso_timestamp(self):
        source = valid_source()
        source["as_of"] = "not-a-date"
        with self.assertRaisesRegex(
            PortfolioContextBridgeError,
            "as_of_invalid",
        ):
            build_fund17_portfolio_context(source)

    def test_required_lists_cannot_be_empty(self):
        for field in (
            "desired_roles",
            "existing_exposures",
            "constraints",
        ):
            source = valid_source()
            source[field] = []
            with self.assertRaises(PortfolioContextBridgeError):
                build_fund17_portfolio_context(source)

    def test_list_items_must_be_nonempty_strings(self):
        source = valid_source()
        source["existing_exposures"] = ["valid", "   "]
        with self.assertRaisesRegex(
            PortfolioContextBridgeError,
            "existing_exposures_item_empty",
        ):
            build_fund17_portfolio_context(source)

    def test_notes_must_be_string_or_null(self):
        source = valid_source()
        source["notes"] = {"bad": "type"}
        with self.assertRaisesRegex(
            PortfolioContextBridgeError,
            "notes_must_be_string_or_null",
        ):
            build_fund17_portfolio_context(source)


    def test_bridge_output_is_accepted_by_fund17_end_to_end(self):
        context = build_fund17_portfolio_context(valid_source())

        fund16 = {
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
                "promotion_eligible": 1,
                "categories": 1,
                "peer_comparable_categories": 0,
            },
            "categories": [
                {
                    "category": "sukuk",
                    "candidate_count": 1,
                    "peer_comparison_available": False,
                    "winner": None,
                    "composite_score": None,
                    "candidates": [
                        {
                            "fund_code": "IAT",
                            "fund_name": "IAT Fund",
                            "category": "sukuk",
                            "fi_score": 60.49,
                            "fi_state": "NEUTRAL",
                            "return_1y": 40.76,
                            "return_1y_rank": None,
                            "max_drawdown": -0.22,
                            "drawdown_resilience_rank": None,
                        }
                    ],
                }
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

        result = build_portfolio_fit_artifact(
            fund16,
            portfolio_context=context,
            generated_at="2026-09-11T18:00:00Z",
        )

        self.assertTrue(result["portfolio_context_available"])
        self.assertEqual(
            result["portfolio_fit_status"],
            "READY_FOR_PORTFOLIO_FIT_RESEARCH",
        )
        self.assertEqual(result["counts"]["context_ready"], 1)
        self.assertEqual(result["counts"]["context_required"], 0)

        candidate = result["candidates"][0]
        self.assertEqual(
            candidate["portfolio_fit_status"],
            "READY_FOR_PORTFOLIO_FIT_RESEARCH",
        )
        self.assertIsNone(candidate["role_fit"])
        self.assertIsNone(candidate["economic_overlap"])
        self.assertIsNone(candidate["diversification_contribution"])
        self.assertIsNone(candidate["concentration_risk"])
        self.assertIsNone(candidate["portfolio_fit_composite_score"])
        self.assertIsNone(candidate["portfolio_fit_rank"])
        self.assertIsNone(candidate["recommendation"])

        self.assertEqual(
            result["write_proof"],
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
