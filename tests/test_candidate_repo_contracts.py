from __future__ import annotations

import unittest
from dataclasses import fields

from services.candidate_contract import CandidateRecord
from services.fund_product_contract import FundIntelligenceEvaluation
from services.turkiye_fund_universe_contract import (
    RANK_TIE_BREAK,
    TurkiyeFundScannerResult,
    TurkiyeFundScannerRow,
)


class CandidateRepoContractTests(unittest.TestCase):
    def test_scanner_row_required_fields_remain_available(self):
        actual = {field.name for field in fields(TurkiyeFundScannerRow)}
        required = {
            "fund_code",
            "fi_score",
            "fi_state",
            "confidence",
            "participation",
            "research_allowed",
            "exposure",
            "data_completeness",
            "scanner_status",
            "missing_evidence",
            "fi_profile",
        }
        self.assertTrue(
            required.issubset(actual),
            f"scanner row contract missing: {sorted(required - actual)}",
        )

    def test_scanner_result_safety_fields_remain_available(self):
        actual = {field.name for field in fields(TurkiyeFundScannerResult)}
        required = {
            "as_of",
            "rows",
            "production_writes",
            "eight_e_calls",
            "new_money_calls",
            "trades",
            "portfolio_writes",
            "persist",
        }
        self.assertTrue(
            required.issubset(actual),
            f"scanner result safety contract missing: {sorted(required - actual)}",
        )

    def test_fund_intelligence_required_fields_remain_available(self):
        actual = {field.name for field in fields(FundIntelligenceEvaluation)}
        required = {
            "symbol",
            "fund_type_profile",
            "state",
            "score",
            "confidence",
            "as_of",
            "facts_version",
            "engine_version",
            "provenance",
            "dimensions",
            "missing_evidence",
            "publishable",
            "completeness",
        }
        self.assertTrue(
            required.issubset(actual),
            f"fund intelligence contract missing: {sorted(required - actual)}",
        )


    def test_candidate_contract_has_peer_group_for_profile_relative_views(self):
        actual = {field.name for field in fields(CandidateRecord)}
        self.assertIn("peer_group", actual)

    def test_candidate_ranking_spine_matches_scanner_contract(self):
        self.assertEqual(
            RANK_TIE_BREAK,
            (
                "fi_score_desc",
                "completeness_desc",
                "confidence_desc",
                "fund_code_asc",
            ),
        )


if __name__ == "__main__":
    unittest.main()
