from __future__ import annotations

import unittest

from services.turkiye_fund_candidate_artifact import _row_exclusion_reasons
from services.turkiye_fund_candidate_detail import (
    CandidateDetailContractError,
    build_candidate_detail,
    build_candidate_detail_catalog,
    candidate_exclusion_reasons,
)


def row(
    code: str,
    score: float | None,
    *,
    status: str = "READY",
    participation: str = "Uygun",
    research_allowed: bool = True,
    completeness: float = 1.0,
    confidence: float = 1.0,
) -> dict:
    return {
        "fund_code": code,
        "fund_name": f"{code} Fund",
        "founder": "Manager",
        "category": "equity",
        "rank": 99,
        "fi_score": score,
        "fi_state": "WATCH",
        "confidence": confidence,
        "participation": participation,
        "research_allowed": research_allowed,
        "exposure": "equity",
        "return_1y": 10.0,
        "max_drawdown": -5.0,
        "data_completeness": completeness,
        "scanner_status": status,
        "universe_states": ["DISCOVERED", "SCANNABLE"],
        "reason": "test",
        "missing_evidence": [],
        "fi_profile": "EQUITY_PARTICIPATION_FUND",
        "peer_view": "PEER_CATEGORY",
    }


def payload(rows: list[dict]) -> dict:
    return {
        "as_of": "2026-09-09",
        "calculated_at": "2026-09-09T10:00:00Z",
        "rows": rows,
        "identities": [
            {
                "fund_code": r["fund_code"],
                "fund_name": r["fund_name"],
                "founder": r["founder"],
                "instrument": "FUND",
                "market": "TR",
                "tefas_status": "ACTIVE",
                "price_date": "2026-09-09",
                "unit_price": 1.23,
            }
            for r in rows
        ],
    }


class CandidateDetailTests(unittest.TestCase):
    def test_four_gate_parity_with_fund14b(self):
        cases = [
            row("AAA", 70.0),
            row("BBB", 99.0, status="REVIEW_REQUIRED"),
            row("CCC", 99.0, participation="Kontrol Et"),
            row("DDD", 99.0, research_allowed=False),
            row("EEE", None),
        ]
        for item in cases:
            with self.subTest(item=item["fund_code"]):
                self.assertEqual(
                    list(candidate_exclusion_reasons(item)),
                    _row_exclusion_reasons(item),
                )

    def test_rank_contract_matches_fund14b_order(self):
        rows = [
            row("BBB", 70.0, completeness=0.9, confidence=1.0),
            row("AAA", 70.0, completeness=1.0, confidence=0.5),
            row("CCC", 80.0, completeness=0.5, confidence=0.5),
            row("DDD", 99.0, status="REVIEW_REQUIRED"),
        ]
        catalog = build_candidate_detail_catalog(payload(rows))
        self.assertEqual(catalog["CCC"].candidate_rank, 1)
        self.assertEqual(catalog["AAA"].candidate_rank, 2)
        self.assertEqual(catalog["BBB"].candidate_rank, 3)
        self.assertIsNone(catalog["DDD"].candidate_rank)
        self.assertEqual(catalog["AAA"].candidate_count, 3)

    def test_detail_is_read_only_and_threshold_free(self):
        detail = build_candidate_detail(payload([row("AAA", 70.0)]), "AAA")
        self.assertTrue(detail.research_only)
        self.assertFalse(detail.threshold_proposed)
        self.assertFalse(detail.threshold_locked)
        self.assertFalse(detail.recommendation_band_applied)
        self.assertFalse(detail.execution_authority)
        self.assertFalse(detail.production_persist)

    def test_provenance_and_identity_are_preserved(self):
        detail = build_candidate_detail(payload([row("AAA", 70.0)]), "AAA")
        self.assertEqual(detail.as_of, "2026-09-09")
        self.assertEqual(detail.calculated_at, "2026-09-09T10:00:00Z")
        self.assertEqual(detail.identity["instrument"], "FUND")
        self.assertEqual(detail.identity["market"], "TR")

    def test_noncanonical_code_fails_closed(self):
        with self.assertRaises(CandidateDetailContractError):
            build_candidate_detail(payload([row("AAA", 70.0)]), "aaa")

    def test_duplicate_code_fails_closed(self):
        with self.assertRaises(CandidateDetailContractError):
            build_candidate_detail_catalog(
                payload([row("AAA", 70.0), row("AAA", 60.0)])
            )

    def test_missing_symbol_fails_closed(self):
        with self.assertRaises(CandidateDetailContractError):
            build_candidate_detail(payload([row("AAA", 70.0)]), "BBB")


if __name__ == "__main__":
    unittest.main()
