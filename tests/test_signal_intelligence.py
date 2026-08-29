from __future__ import annotations

import unittest
from pathlib import Path

from repositories.signal_intelligence_repository import InMemorySignalIntelligenceRepository
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN_DEGIL
from services.security_intelligence_contract import (
    CHANGE_NEW_MATERIAL_SIGNAL,
    CHANGE_SIGNAL_CONFLICT_DETECTED,
    SecurityFacts,
    SecurityParticipationContext,
    snapshot_from_view,
)
from services.security_intelligence_engine import evaluate_security_intelligence
from services.security_intelligence_snapshot_service import (
    payloads_semantically_equal,
    snapshot_row_from_view,
)
from services.signal_disclosure_adapters import KapDisclosureAdapter, OfficialIrAdapter
from services.signal_intelligence_contract import (
    CONFLICTING,
    DIRECTION_NEGATIVE,
    DIRECTION_POSITIVE,
    EVENT_MERGER_ACQUISITION,
    EVENT_SOCIAL_SIGNAL,
    EVENT_TYPES,
    MATERIALITY_CRITICAL,
    MATERIALITY_HIGH,
    MATERIALITY_UNKNOWN,
    SIGNAL_CONTRACT_VERSION,
    SIGNAL_ENGINE_VERSION,
    TIER_1_PRIMARY,
    TIER_4_SOCIAL_DISCOVERY,
    UNVERIFIED,
    VERIFIED,
)
from services.signal_intelligence_engine import (
    classify_event_type,
    event_identity,
    resolve_materiality,
)
from services.signal_intelligence_fixtures import (
    fixture_conflict_negative,
    fixture_conflict_positive,
    fixture_guidance_cut,
    fixture_material_negative,
    fixture_material_positive,
    fixture_merger_newswire,
    fixture_merger_sec,
    fixture_sec_8k_verified,
    fixture_social_only_claim,
)
from services.signal_intelligence_service import SignalIntelligenceService
from services.signal_social_adapter import SocialSignalAdapter
from services.signal_source_registry import resolve_source


PAGE = Path("pages/4_Company_Report.py")
FACADE = Path("services/nabi_intelligence_facade.py")
MIGRATION = Path("database/migration_signal_intelligence.sql")
ENGINE = Path("services/signal_intelligence_engine.py")
SCORE = Path("services/nabi_score_v4.py")


def _service() -> SignalIntelligenceService:
    return SignalIntelligenceService(InMemorySignalIntelligenceRepository())


class SignalContractTests(unittest.TestCase):
    def test_versions_and_taxonomy(self) -> None:
        self.assertEqual(SIGNAL_CONTRACT_VERSION, "signal_contract_8d.1")
        self.assertEqual(SIGNAL_ENGINE_VERSION, "signal_engine_8d.1")
        self.assertIn("EARNINGS", EVENT_TYPES)
        self.assertIn("KAP_DISCLOSURE", EVENT_TYPES)
        self.assertIn("SOCIAL_SIGNAL", EVENT_TYPES)
        self.assertEqual(classify_event_type("not-a-type"), "OTHER")
        self.assertEqual(classify_event_type(""), "UNKNOWN")

    def test_authority_registry_not_display_name(self) -> None:
        social = resolve_source("x:bugra_kurtoglu", "SOCIAL_X")
        self.assertEqual(social.authority, TIER_4_SOCIAL_DISCOVERY)
        self.assertTrue(social.discovery_only)
        unknown = resolve_source("Popular Analyst Account")
        self.assertEqual(unknown.authority, TIER_4_SOCIAL_DISCOVERY)
        self.assertEqual(resolve_source("sec", "SEC").authority, TIER_1_PRIMARY)

    def test_migration_is_additive(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("create table if not exists public.signal_events", sql)
        self.assertIn("create table if not exists public.signal_evidence", sql)
        self.assertIn("unique (event_id)", sql)
        self.assertIn("unique (evidence_id)", sql)
        self.assertNotIn("drop table", sql.lower())
        self.assertNotIn("truncate", sql.lower())


class SignalIngestTests(unittest.TestCase):
    def test_verified_sec_event_is_idempotent(self) -> None:
        service = _service()
        first = service.ingest(fixture_sec_8k_verified())
        second = service.ingest(fixture_sec_8k_verified())
        self.assertEqual(first.event.verification_status, VERIFIED)
        self.assertEqual(first.event.source_authority, TIER_1_PRIMARY)
        self.assertTrue(first.event.event_id.startswith("evt:"))
        self.assertEqual(first.event.event_id, second.event.event_id)
        self.assertTrue(second.replay_skipped)
        self.assertFalse(second.created_event)
        self.assertEqual(service.repo.event_writes, 1)
        self.assertEqual(service.repo.evidence_writes, 1)
        self.assertTrue(first.persistence_skipped)
        self.assertFalse(first.persisted)

    def test_social_only_stays_unverified(self) -> None:
        service = _service()
        result = service.ingest(fixture_social_only_claim())
        self.assertEqual(result.event.event_type, EVENT_SOCIAL_SIGNAL)
        self.assertEqual(result.event.verification_status, UNVERIFIED)
        self.assertEqual(result.evidence.source_authority, TIER_4_SOCIAL_DISCOVERY)
        self.assertEqual(result.event.materiality, MATERIALITY_UNKNOWN)
        self.assertIn("UNVERIFIED_SOCIAL_CLAIM", service.context_for("CRM").signal_risk_flags)

    def test_multi_source_one_event(self) -> None:
        service = _service()
        sec = service.ingest(fixture_merger_sec())
        wire = service.ingest(fixture_merger_newswire())
        self.assertEqual(sec.event.event_id, wire.event.event_id)
        self.assertEqual(sec.event.event_type, EVENT_MERGER_ACQUISITION)
        self.assertEqual(len(wire.event.evidence_ids), 2)
        self.assertEqual(len(service.repo.list_evidence(sec.event.event_id)), 2)
        self.assertEqual(len(service.repo.list_events("CRM")), 1)
        self.assertEqual(sec.event.verification_status, VERIFIED)
        self.assertEqual(wire.evidence.verification_status, UNVERIFIED)

    def test_conflict_fails_closed(self) -> None:
        service = _service()
        service.ingest(fixture_conflict_positive())
        conflicted = service.ingest(fixture_conflict_negative())
        self.assertEqual(conflicted.event.verification_status, CONFLICTING)
        self.assertEqual(conflicted.event.direction, "UNKNOWN")
        self.assertEqual(conflicted.event.materiality, MATERIALITY_UNKNOWN)
        self.assertIn("SIGNAL_CONFLICT", service.context_for("CRM").signal_risk_flags)

    def test_event_identity_ignores_headline(self) -> None:
        left = fixture_sec_8k_verified()
        right = fixture_sec_8k_verified()
        right = type(right)(**{**right.__dict__, "headline": "Completely different headline"})
        self.assertEqual(event_identity(left), event_identity(right))

    def test_missing_denominator_stays_unknown(self) -> None:
        materiality, reasons = resolve_materiality(
            event_type="MAJOR_CONTRACT",
            event_subtype=None,
            verification=VERIFIED,
            authority=TIER_1_PRIMARY,
            contract_value=500.0,
            revenue=None,
            period_compatible=False,
        )
        self.assertEqual(materiality, MATERIALITY_UNKNOWN)
        self.assertIn("MISSING_MATERIALITY_DENOMINATOR", reasons)


class SignalImpactTests(unittest.TestCase):
    def test_material_negative_does_not_change_fundamentals(self) -> None:
        facts = SecurityFacts(symbol="CRM", roic=18, roe=20, operating_margin=18, pe=30)
        participation = SecurityParticipationContext(status="Uygun", research_allowed=True)
        before = evaluate_security_intelligence(facts, participation)
        service = _service()
        service.ingest(fixture_material_negative())
        after = service.attach_to_view(before)
        self.assertEqual(after.event.materiality if False else service.context_for("CRM").material_signals[0].materiality, MATERIALITY_CRITICAL)
        self.assertEqual(after.overall_score, before.overall_score)
        self.assertEqual(after.quality.score, before.quality.score)
        self.assertEqual(after.growth.score, before.growth.score)
        self.assertEqual(after.investment_state, before.investment_state)
        self.assertIn("MATERIAL_NEGATIVE_SIGNAL", after.signal_context.signal_risk_flags)
        self.assertEqual(
            snapshot_from_view(before).dimension_scores,
            snapshot_from_view(after).dimension_scores,
        )

    def test_positive_signal_does_not_create_buy(self) -> None:
        facts = SecurityFacts(symbol="AAPL", roic=18, roe=20, operating_margin=18, pe=30)
        participation = SecurityParticipationContext(
            status=PARTICIPATION_STATUS_UYGUN_DEGIL,
            research_allowed=False,
        )
        view = evaluate_security_intelligence(facts, participation)
        service = _service()
        result = service.ingest(fixture_material_positive())
        attached = service.attach_to_view(view)
        self.assertEqual(result.event.direction, DIRECTION_POSITIVE)
        self.assertIn(result.event.materiality, {MATERIALITY_HIGH, "MEDIUM"})
        self.assertFalse(attached.investable)
        self.assertEqual(attached.investment_state, "AVOID")
        self.assertEqual(attached.overall_score, view.overall_score)

    def test_guidance_cut_is_negative_context(self) -> None:
        service = _service()
        result = service.ingest(fixture_guidance_cut())
        self.assertEqual(result.event.direction, DIRECTION_NEGATIVE)
        self.assertEqual(result.event.materiality, MATERIALITY_HIGH)
        self.assertEqual(result.event.verification_status, VERIFIED)

    def test_snapshot_refs_do_not_enter_si_semantic_payload(self) -> None:
        view = evaluate_security_intelligence(
            SecurityFacts(symbol="CRM", roic=18, roe=20, operating_margin=18, pe=30),
            SecurityParticipationContext(status="Uygun", research_allowed=True),
        )
        service = _service()
        service.ingest(fixture_material_negative())
        attached = service.attach_to_view(view)
        flagged = service.attach_to_view(
            view,
            previous_refs=None,
            mutate_change_flags=True,
        )
        self.assertIn(CHANGE_NEW_MATERIAL_SIGNAL, flagged.change_flags)
        left = snapshot_row_from_view(view, as_of="2026-01-31")
        right = snapshot_row_from_view(attached, as_of="2026-01-31")
        self.assertTrue(payloads_semantically_equal(left, right))
        self.assertNotIn("signal_context", left)
        self.assertNotIn("latest_material_event_id", left)

    def test_conflict_change_flag(self) -> None:
        view = evaluate_security_intelligence(SecurityFacts(symbol="CRM", price=250))
        service = _service()
        service.ingest(fixture_conflict_positive())
        service.ingest(fixture_conflict_negative())
        attached = service.attach_to_view(view, mutate_change_flags=True)
        self.assertIn(CHANGE_SIGNAL_CONFLICT_DETECTED, attached.change_flags)

    def test_nabi_score_and_hybrid_untouched(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        self.assertIn("del participation_score, participation_status", SCORE.read_text(encoding="utf-8"))


class SignalConsumerTests(unittest.TestCase):
    def test_company_report_and_facade_use_one_service(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        facade = FACADE.read_text(encoding="utf-8")
        self.assertIn("render_signal_intelligence_section", page)
        self.assertIn("SignalIntelligenceService", page)
        self.assertIn("SignalIntelligenceService", facade)
        self.assertIn("signal_context", facade)
        self.assertNotIn("nabi_score_v4", facade)
        self.assertNotIn(".insert(", facade)
        ui = Path("components/signal_intelligence_ui.py").read_text(encoding="utf-8")
        self.assertIn("Neden önemli", ui)
        self.assertIn("Doğrulama", ui)

    def test_engine_has_no_provider_or_llm(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("fmp_client", source)
        self.assertNotIn("openai", source.lower())
        self.assertNotIn("stock_news", source)

    def test_social_and_kap_adapters_are_fail_closed(self) -> None:
        social = SocialSignalAdapter()
        self.assertFalse(social.available)
        with self.assertRaises(NotImplementedError):
            social.fetch_official_feed()
        self.assertFalse(KapDisclosureAdapter.available)
        self.assertFalse(OfficialIrAdapter.available)
        with self.assertRaises(NotImplementedError):
            KapDisclosureAdapter().raw_from_disclosure()


if __name__ == "__main__":
    unittest.main()
