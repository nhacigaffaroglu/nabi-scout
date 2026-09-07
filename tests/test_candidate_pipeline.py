from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.candidate_band_policy import CandidateBandPolicy
from services.candidate_pipeline import run_turkiye_fund_candidate_pipeline


def scanner_row(
    code,
    *,
    status,
    participation,
    research_allowed,
    profile,
    score,
    state,
    confidence,
    completeness,
    exposure,
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
    code,
    *,
    profile,
    score,
    state,
    confidence,
    completeness,
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
        dimensions=(),
        missing_evidence=(),
        publishable=publishable,
        completeness=completeness,
    )


def scanner_result():
    gkv = scanner_row(
        "GKV",
        status="READY",
        participation="Uygun",
        research_allowed=True,
        profile="EQUITY_PARTICIPATION_FUND",
        score=81.96,
        state="ATTRACTIVE",
        confidence=.9,
        completeness=1.0,
        exposure="equity",
    )
    ftl = scanner_row(
        "FTL",
        status="REVIEW_REQUIRED",
        participation="Kontrol Et",
        research_allowed=False,
        profile="LIQUIDITY_PARTICIPATION_FUND",
        score=95.0,
        state="ATTRACTIVE",
        confidence=.8,
        completeness=.9,
        exposure=None,
        missing=("PARTICIPATION_REVIEW", "PDR_RECONCILIATION_FAILED"),
    )
    cpu = scanner_row(
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
    return SimpleNamespace(
        as_of="2026-08-31",
        rows=(gkv, ftl, cpu),
        persist=False,
        production_writes=(),
        eight_e_calls=0,
        new_money_calls=0,
        trades=0,
        portfolio_writes=0,
    )


def intelligence():
    return {
        "GKV": fi_view(
            "GKV",
            profile="EQUITY_PARTICIPATION_FUND",
            score=81.96,
            state="ATTRACTIVE",
            confidence=.9,
            completeness=1.0,
        ),
        "FTL": fi_view(
            "FTL",
            profile="LIQUIDITY_PARTICIPATION_FUND",
            score=95.0,
            state="ATTRACTIVE",
            confidence=.8,
            completeness=.9,
        ),
    }


class CandidatePipelineTests(unittest.TestCase):
    def test_e2e_without_policy_leaves_bands_unassigned(self):
        result = run_turkiye_fund_candidate_pipeline(
            scanner_result(),
            intelligence(),
        )
        self.assertFalse(result.band_policy_applied)
        self.assertEqual(result.ranking.candidate_count, 1)
        self.assertEqual(result.ranking.ranked[0].candidate.symbol, "GKV")
        self.assertIsNone(
            result.ranking.ranked[0].candidate.recommendation_band
        )

    def test_high_score_ftl_does_not_bypass_gate(self):
        result = run_turkiye_fund_candidate_pipeline(
            scanner_result(),
            intelligence(),
        )
        self.assertEqual([row.symbol for row in result.ranking.ineligible], ["CPU", "FTL"])
        self.assertEqual(result.ranking.ranked[0].candidate.symbol, "GKV")

    def test_calibration_uses_only_eligible_scores(self):
        result = run_turkiye_fund_candidate_pipeline(
            scanner_result(),
            intelligence(),
        )
        self.assertEqual(result.calibration.eligible_scores.count, 1)
        self.assertEqual(result.calibration.eligible_scores.maximum, 81.96)

    def test_synthetic_policy_can_be_applied_only_when_supplied(self):
        policy = CandidateBandPolicy(
            policy_version="synthetic-test",
            calibration_fingerprint="synthetic",
            strong_candidate_min=90,
            candidate_min=80,
            watch_min=70,
        )
        result = run_turkiye_fund_candidate_pipeline(
            scanner_result(),
            intelligence(),
            band_policy=policy,
        )
        self.assertTrue(result.band_policy_applied)
        self.assertEqual(
            result.ranking.ranked[0].candidate.recommendation_band,
            "candidate",
        )

    def test_pipeline_no_write_proof(self):
        result = run_turkiye_fund_candidate_pipeline(
            scanner_result(),
            intelligence(),
        )
        self.assertFalse(result.persist)
        self.assertEqual(result.production_writes, ())
        self.assertEqual(result.eight_e_calls, 0)
        self.assertEqual(result.new_money_calls, 0)
        self.assertEqual(result.trades, 0)
        self.assertEqual(result.portfolio_writes, 0)

    def test_refuses_dirty_scanner_write_state(self):
        dirty = scanner_result()
        dirty.production_writes = ("portfolio",)
        with self.assertRaisesRegex(
            ValueError, "candidate_pipeline_refuses_scanner_production_writes"
        ):
            run_turkiye_fund_candidate_pipeline(dirty, intelligence())

    def test_refuses_scanner_8e_activity(self):
        dirty = scanner_result()
        dirty.eight_e_calls = 1
        with self.assertRaisesRegex(
            ValueError, "candidate_pipeline_refuses_scanner_eight_e_calls"
        ):
            run_turkiye_fund_candidate_pipeline(dirty, intelligence())


if __name__ == "__main__":
    unittest.main()
