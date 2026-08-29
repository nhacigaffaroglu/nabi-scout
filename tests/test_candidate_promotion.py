from __future__ import annotations

import unittest

from services.candidate_promotion_policy import (
    EVIDENCE_UNIVERSE_EXPANSION_COMPLETED,
    PROMOTION_DATA_SOURCE,
    REASON_CANDIDATE_ALREADY_EXISTS,
    REASON_IDENTITY_CONFLICT,
    REASON_IDENTITY_MISSING,
    REASON_NO_RESEARCH_EVIDENCE,
    REASON_PARTICIPATION_NOT_UYGUN,
    REASON_PROMOTION_ELIGIBLE,
    REASON_UNSUPPORTED_INSTRUMENT,
    build_promotion_payload,
    evaluate_candidate_promotion,
)
from services.candidate_promotion_service import promote_if_eligible
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.research_workflow_service import DEFAULT_RESEARCH_STATUS
from services.security_intelligence_contract import SecurityFacts, SecurityParticipationContext
from services.security_intelligence_engine import evaluate_security_intelligence
from services.security_master_contract import (
    INSTRUMENT_EQUITY,
    INSTRUMENT_ETF,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNKNOWN,
    SecurityFact,
    SecurityResolution,
)
from services.signal_ingestion_universe import build_signal_ingestion_universe
from services.universe_expansion_contract import EXPANSION_STATUS_COMPLETED


def _resolution(
    symbol: str = "ADBE",
    *,
    status: str = RESOLUTION_RESOLVED,
    instrument_type: str = INSTRUMENT_EQUITY,
    exchange: str = "NASDAQ",
) -> SecurityResolution:
    fact = SecurityFact(
        identifier=symbol,
        identifier_type="TICKER",
        instrument_type=instrument_type,
        source="us_listing",
        observed_at="2026-08-29T00:00:00+00:00",
        symbol=symbol,
        exchange=exchange,
    )
    return SecurityResolution(
        identifier=symbol,
        identifier_type="TICKER",
        instrument_type=instrument_type,
        status=status,
        source="us_listing",
        observed_at=fact.observed_at,
        facts=(fact,),
    )


def _queue(symbol: str = "ADBE", *, status: str = EXPANSION_STATUS_COMPLETED, source: str = "sp500_core"):
    return {
        "symbol": symbol,
        "status": status,
        "source_universe": source,
    }


def _snap(status: str = PARTICIPATION_STATUS_UYGUN):
    return {"status": status, "source": "methodology"}


class MemoryCandidateRepo:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.writes = 0

    def list_by_symbol(self, symbol: str):
        wanted = str(symbol or "").strip().upper()
        return [dict(row) for row in self.rows if row.get("symbol") == wanted]

    def create(self, payload):
        self.writes += 1
        row = dict(payload)
        row.setdefault("id", f"cand-{len(self.rows) + 1}")
        self.rows.append(row)
        return dict(row)


class CandidatePromotionPolicyTests(unittest.TestCase):
    def test_uygun_plus_discovery_evidence_is_eligible(self) -> None:
        decision = evaluate_candidate_promotion(
            "ADBE",
            snapshot=_snap(),
            resolution=_resolution("ADBE"),
            queue_row=_queue("ADBE"),
        )
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.reason_codes, (REASON_PROMOTION_ELIGIBLE,))
        self.assertEqual(decision.research_status_if_promoted, DEFAULT_RESEARCH_STATUS)
        self.assertEqual(DEFAULT_RESEARCH_STATUS, "YENI")
        self.assertEqual(decision.evidence[0].source, EVIDENCE_UNIVERSE_EXPANSION_COMPLETED)

    def test_uygun_without_evidence_blocked(self) -> None:
        decision = evaluate_candidate_promotion(
            "ADBE",
            snapshot=_snap(),
            resolution=_resolution("ADBE"),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(REASON_NO_RESEARCH_EVIDENCE, decision.reason_codes)

    def test_kontrol_et_blocked_even_with_evidence(self) -> None:
        decision = evaluate_candidate_promotion(
            "AMD",
            snapshot=_snap(PARTICIPATION_STATUS_KONTROL_ET),
            resolution=_resolution("AMD"),
            queue_row=_queue("AMD"),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(REASON_PARTICIPATION_NOT_UYGUN, decision.reason_codes)

    def test_uygun_degil_blocked_even_with_evidence(self) -> None:
        decision = evaluate_candidate_promotion(
            "AAPL",
            snapshot=_snap(PARTICIPATION_STATUS_UYGUN_DEGIL),
            resolution=_resolution("AAPL"),
            queue_row=_queue("AAPL"),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(REASON_PARTICIPATION_NOT_UYGUN, decision.reason_codes)

    def test_missing_participation_blocked(self) -> None:
        decision = evaluate_candidate_promotion(
            "XOM",
            resolution=_resolution("XOM"),
            queue_row=_queue("XOM"),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(REASON_PARTICIPATION_NOT_UYGUN, decision.reason_codes)

    def test_identity_conflict_blocked(self) -> None:
        decision = evaluate_candidate_promotion(
            "ADBE",
            snapshot=_snap(),
            resolution=_resolution("ADBE", status=RESOLUTION_CONFLICT),
            queue_row=_queue("ADBE"),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(REASON_IDENTITY_CONFLICT, decision.reason_codes)

    def test_identity_missing_blocked(self) -> None:
        decision = evaluate_candidate_promotion(
            "ADBE",
            snapshot=_snap(),
            resolution=_resolution("ADBE", status=RESOLUTION_UNKNOWN),
            queue_row=_queue("ADBE"),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(REASON_IDENTITY_MISSING, decision.reason_codes)

    def test_unsupported_etf_blocked(self) -> None:
        decision = evaluate_candidate_promotion(
            "SPUS",
            snapshot=_snap(),
            resolution=_resolution("SPUS", instrument_type=INSTRUMENT_ETF),
            queue_row=_queue("SPUS", source="pilot_equity"),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, decision.reason_codes)

    def test_existing_candidate_skipped(self) -> None:
        decision = evaluate_candidate_promotion(
            "JNJ",
            snapshot=_snap(),
            resolution=_resolution("JNJ", exchange="NYSE"),
            queue_row=_queue("JNJ", source="pilot_equity"),
            existing_candidates=[{"symbol": "JNJ", "research_status": "YENI"}],
        )
        self.assertFalse(decision.eligible)
        self.assertTrue(decision.candidate_exists)
        self.assertIn(REASON_CANDIDATE_ALREADY_EXISTS, decision.reason_codes)

    def test_payload_is_yeni_without_recommendation(self) -> None:
        decision = evaluate_candidate_promotion(
            "ADBE",
            snapshot=_snap(),
            resolution=_resolution("ADBE"),
            queue_row=_queue("ADBE"),
        )
        payload = build_promotion_payload(decision)
        self.assertEqual(payload["research_status"], "YENI")
        self.assertEqual(payload["data_source"], PROMOTION_DATA_SOURCE)
        self.assertNotIn("decision", payload)
        self.assertNotIn("decision_label", payload)
        self.assertNotIn("conviction_score", payload)
        self.assertNotIn("investable", payload)


class CandidatePromotionWriteTests(unittest.TestCase):
    def test_eligible_write_then_idempotent_replay(self) -> None:
        repo = MemoryCandidateRepo()
        first = promote_if_eligible(
            "ADBE",
            snapshot=_snap(),
            resolution=_resolution("ADBE"),
            queue_row=_queue("ADBE"),
            candidate_repo=repo,
            persist=True,
        )
        self.assertTrue(first.written)
        self.assertEqual(repo.writes, 1)
        self.assertEqual(repo.rows[0]["research_status"], "YENI")
        replay = promote_if_eligible(
            "ADBE",
            snapshot=_snap(),
            resolution=_resolution("ADBE"),
            queue_row=_queue("ADBE"),
            candidate_repo=repo,
            persist=True,
        )
        self.assertFalse(replay.written)
        self.assertEqual(repo.writes, 1)
        self.assertIn(REASON_CANDIDATE_ALREADY_EXISTS, replay.decision.reason_codes)

    def test_blocked_symbol_writes_nothing(self) -> None:
        repo = MemoryCandidateRepo()
        result = promote_if_eligible(
            "AMD",
            snapshot=_snap(PARTICIPATION_STATUS_KONTROL_ET),
            resolution=_resolution("AMD"),
            queue_row=_queue("AMD"),
            candidate_repo=repo,
            persist=True,
        )
        self.assertFalse(result.written)
        self.assertEqual(repo.writes, 0)

    def test_evaluate_only_default_does_not_write(self) -> None:
        repo = MemoryCandidateRepo()
        result = promote_if_eligible(
            "ADBE",
            snapshot=_snap(),
            resolution=_resolution("ADBE"),
            queue_row=_queue("ADBE"),
            candidate_repo=repo,
        )
        self.assertFalse(result.written)
        self.assertEqual(repo.writes, 0)
        self.assertTrue(result.decision.eligible)


class PromotionSafetyTests(unittest.TestCase):
    def test_yeni_promotion_is_not_sec_monitored(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[{"symbol": "ADBE", "market": "US", "asset_class": "equity", "research_status": "YENI"}],
            participation_by_symbol={"ADBE": {"status": PARTICIPATION_STATUS_UYGUN}},
        )
        self.assertNotIn("ADBE", universe.eligible)
        self.assertIn(("ADBE", "not_active_research"), universe.excluded)

    def test_promoted_candidate_is_not_investable(self) -> None:
        view = evaluate_security_intelligence(
            SecurityFacts(symbol="ADBE", roic=18, roe=20, operating_margin=18, pe=30),
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN_DEGIL, research_allowed=False),
        )
        self.assertFalse(view.investable)
        payload = build_promotion_payload(
            evaluate_candidate_promotion(
                "ADBE",
                snapshot=_snap(),
                resolution=_resolution("ADBE"),
                queue_row=_queue("ADBE"),
            )
        )
        self.assertNotEqual(payload.get("research_status"), "INCELEMEDE")
        self.assertIsNone(payload.get("decision"))


if __name__ == "__main__":
    unittest.main()
