from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.candidate_contract import (
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_WATCH_ONLY,
)
from services.candidate_fund_adapter import (
    candidate_from_turkiye_fund,
    candidates_from_turkiye_fund_scanner,
    fund_candidate_snapshot_id,
)


def scanner_row(
    code="GKV",
    *,
    status="READY",
    participation="Uygun",
    research_allowed=True,
    profile="EQUITY_PARTICIPATION_FUND",
    score=81.96,
    state="ATTRACTIVE",
    confidence=.9,
    completeness=1.0,
    exposure="equity",
    missing=(),
):
    return SimpleNamespace(
        fund_code=code,
        scanner_status=status,
        participation=participation,
        research_allowed=research_allowed,
        fi_profile=profile,
        fi_score=score,
        fi_state=state,
        confidence=confidence,
        data_completeness=completeness,
        exposure=exposure,
        missing_evidence=tuple(missing),
    )


def fi_view(
    code="GKV",
    *,
    profile="EQUITY_PARTICIPATION_FUND",
    score=81.96,
    state="ATTRACTIVE",
    confidence=.9,
    completeness=1.0,
    publishable=True,
):
    return SimpleNamespace(
        symbol=code,
        fund_type_profile=profile,
        state=state,
        score=score,
        confidence=confidence,
        as_of="2026-08-31",
        facts_version="fund_facts_1d.1",
        engine_version="fund_intelligence_1g.1",
        provenance=("TEFAS", "KAP"),
        dimensions=(
            SimpleNamespace(name="PERFORMANCE", score=88.0),
            SimpleNamespace(name="RISK", score=72.0),
        ),
        participation=SimpleNamespace(eligible=True),
        missing_evidence=(),
        publishable=publishable,
        completeness=completeness,
    )


class CandidateFundAdapterTests(unittest.TestCase):
    def test_gkv_like_ready_row_becomes_eligible(self):
        record = candidate_from_turkiye_fund(
            scanner_row(),
            fi_view(),
            scanner_as_of="2026-08-31",
        )
        self.assertEqual(record.eligibility.status, ELIGIBILITY_ELIGIBLE)
        self.assertEqual(record.symbol, "GKV")
        self.assertEqual(record.total_score, 81.96)
        self.assertIsNone(record.recommendation_band)
        self.assertEqual(record.sub_scores[0], ("PERFORMANCE", 88.0))
        self.assertEqual(record.peer_group, "EQUITY_PARTICIPATION_FUND")

    def test_ftl_like_high_fi_cannot_bypass_participation(self):
        row = scanner_row(
            "FTL",
            status="REVIEW_REQUIRED",
            participation="Kontrol Et",
            research_allowed=False,
            profile="LIQUIDITY_PARTICIPATION_FUND",
            score=95.0,
            state="ATTRACTIVE",
            exposure=None,
            missing=("PARTICIPATION_REVIEW", "PDR_RECONCILIATION_FAILED"),
        )
        view = fi_view(
            "FTL",
            profile="LIQUIDITY_PARTICIPATION_FUND",
            score=95.0,
        )
        record = candidate_from_turkiye_fund(
            row, view, scanner_as_of="2026-08-31"
        )
        self.assertEqual(record.eligibility.status, ELIGIBILITY_INELIGIBLE)
        self.assertIn("PARTICIPATION_NOT_UYGUN", record.eligibility.reasons)
        self.assertIn("RESEARCH_NOT_ALLOWED", record.eligibility.reasons)
        self.assertIsNone(record.recommendation_band)

    def test_ready_but_stale_is_watch_only(self):
        row = scanner_row(missing=("SOURCE_STALE",))
        record = candidate_from_turkiye_fund(
            row, fi_view(), scanner_as_of="2026-08-31"
        )
        self.assertEqual(record.eligibility.status, ELIGIBILITY_WATCH_ONLY)
        self.assertIn("REQUIRED_EVIDENCE_STALE", record.eligibility.reasons)

    def test_no_fi_evaluation_is_fail_closed(self):
        row = scanner_row(
            "CPU",
            status="REVIEW_REQUIRED",
            participation="Kontrol Et",
            research_allowed=False,
            profile=None,
            score=None,
            state=None,
            confidence=None,
            completeness=None,
            exposure=None,
            missing=("FI_INSUFFICIENT_DATA", "PARTICIPATION_REVIEW"),
        )
        record = candidate_from_turkiye_fund(
            row, None, scanner_as_of="2026-08-31"
        )
        self.assertEqual(record.eligibility.status, ELIGIBILITY_INELIGIBLE)
        self.assertIsNone(record.total_score)
        self.assertEqual(record.intelligence_state, "INSUFFICIENT_DATA")

    def test_scanner_and_fi_score_mismatch_fails(self):
        with self.assertRaisesRegex(ValueError, "fund_candidate_score_mismatch"):
            candidate_from_turkiye_fund(
                scanner_row(score=81.96),
                fi_view(score=82.0),
                scanner_as_of="2026-08-31",
            )

    def test_symbol_mismatch_fails(self):
        with self.assertRaisesRegex(ValueError, "fund_candidate_symbol_mismatch"):
            candidate_from_turkiye_fund(
                scanner_row("GKV"),
                fi_view("ZPE"),
                scanner_as_of="2026-08-31",
            )

    def test_snapshot_id_is_content_addressed(self):
        row = scanner_row()
        view = fi_view()
        one = fund_candidate_snapshot_id(
            row, view, scanner_as_of="2026-08-31"
        )
        two = fund_candidate_snapshot_id(
            row, view, scanner_as_of="2026-08-31"
        )
        changed = fund_candidate_snapshot_id(
            scanner_row(score=82.0),
            fi_view(score=82.0),
            scanner_as_of="2026-08-31",
        )
        self.assertEqual(one, two)
        self.assertNotEqual(one, changed)

    def test_result_adapter_rejects_unknown_fi_symbol(self):
        result = SimpleNamespace(
            as_of="2026-08-31",
            rows=(scanner_row("GKV"),),
        )
        with self.assertRaisesRegex(
            ValueError, "fund_candidate_unknown_intelligence_symbols"
        ):
            candidates_from_turkiye_fund_scanner(
                result,
                {"GKV": fi_view("GKV"), "XXX": fi_view("XXX")},
            )


if __name__ == "__main__":
    unittest.main()
