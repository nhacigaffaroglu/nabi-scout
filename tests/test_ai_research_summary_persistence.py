from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from repositories.ai_research_summary_repository import AIResearchSummaryRepository
from services.ai_research_summary_contract import (
    AIResearchSummaryMetadata,
    AIResearchSummaryView,
)
from services.ai_research_summary_persistence_service import (
    audit_persisted_summary_payload,
    build_snapshot_payload,
    fetch_exact_ai_research_summary,
    save_ai_research_summary_snapshot,
    symbol_has_stale_persisted_summary,
    view_from_row,
)
from services.ai_research_summary_service import (
    AIResearchSummaryService,
    compute_context_semantic_identity,
)
from services.company_intelligence_contract import CompanyIntelligenceView
from services.wealth_adviser_config import AdviserLlmConfig
from tests.test_company_report_ai_research_summary import (
    _blocked_eligibility,
    _ci_view,
    _eligible_eligibility,
    _enabled_config,
    _limited_unified,
    _thesis_view,
    _valid_summary_json,
)


def _available_view(
    symbol: str = "CRM",
    *,
    identity: str = "identity-a",
    valuation_summary: str = "P/S 3.87; P/FCF 11.16; EV/EBIT 20.14.",
) -> AIResearchSummaryView:
    return AIResearchSummaryView(
        symbol=symbol,
        status="AVAILABLE",
        evidence_level="LIMITED",
        financial_outlook="Son yıllık finansallara göre gelir artışı görülüyor.",
        valuation_summary=valuation_summary,
        key_strengths=("Gelir ve faaliyet kârı yıllık bazda iyileşiyor.",),
        generated_at="2026-08-15T10:00:00+00:00",
        model_provider="openai",
        model_name="gpt-test",
        metadata=AIResearchSummaryMetadata(
            context_semantic_identity=identity,
            validation_outcome="valid",
            llm_call_count=1,
        ),
    )


def _snapshot_row(
    view: AIResearchSummaryView,
    *,
    semantic_identity: str,
) -> dict:
    payload = build_snapshot_payload(view, semantic_identity=semantic_identity)
    return {
        "id": "row-1",
        **payload,
        "created_at": "2026-08-15T10:01:00+00:00",
    }


class AIResearchSummaryMigrationContractTests(unittest.TestCase):
    def test_schema_rls_unique_index_contract(self) -> None:
        with open(
            "database/migration_ai_research_summary_snapshots.sql",
            encoding="utf-8",
        ) as handle:
            sql = handle.read()
        self.assertIn("ai_research_summary_snapshots", sql)
        self.assertIn("enable row level security", sql.lower())
        self.assertIn("authenticated", sql.lower())
        self.assertNotIn("anon", sql.lower())
        self.assertIn("ai_research_summary_snapshots_symbol_identity_uidx", sql)
        self.assertIn("ai_research_summary_snapshots_symbol_generated_idx", sql)
        self.assertIn("(symbol, semantic_identity)", sql)


class AIResearchSummaryPersistenceServiceTests(unittest.TestCase):
    def test_first_generation_persisted_once(self) -> None:
        view = _available_view()
        repo = MagicMock()
        repo.get_exact.return_value = None
        repo.save_if_absent.return_value = (_snapshot_row(view, semantic_identity="identity-a"), True)
        result = save_ai_research_summary_snapshot(
            repo,
            view,
            semantic_identity="identity-a",
        )
        self.assertTrue(result.saved)
        repo.save_if_absent.assert_called_once()

    def test_same_identity_skips_duplicate_save(self) -> None:
        view = _available_view()
        repo = MagicMock()
        existing = _snapshot_row(view, semantic_identity="identity-a")
        repo.get_exact.return_value = existing
        result = save_ai_research_summary_snapshot(
            repo,
            view,
            semantic_identity="identity-a",
        )
        self.assertTrue(result.skipped_duplicate)
        repo.save_if_absent.assert_not_called()

    def test_validation_failed_not_persisted(self) -> None:
        view = AIResearchSummaryView.validation_failed(
            symbol="CRM",
            message="blocked",
        )
        repo = MagicMock()
        result = save_ai_research_summary_snapshot(
            repo,
            view,
            semantic_identity="identity-a",
        )
        self.assertFalse(result.saved)
        repo.get_exact.assert_not_called()
        repo.save_if_absent.assert_not_called()

    def test_unavailable_not_persisted(self) -> None:
        view = AIResearchSummaryView.unavailable(symbol="CRM", message="provider error")
        repo = MagicMock()
        result = save_ai_research_summary_snapshot(
            repo,
            view,
            semantic_identity="identity-a",
        )
        self.assertFalse(result.saved)
        repo.save_if_absent.assert_not_called()

    def test_unique_insert_conflict_reloads_existing(self) -> None:
        view = _available_view()
        existing = _snapshot_row(view, semantic_identity="identity-a")
        repo = MagicMock()
        repo.get_exact.side_effect = [None, existing]
        repo.save_if_absent.return_value = (existing, False)
        result = save_ai_research_summary_snapshot(
            repo,
            view,
            semantic_identity="identity-a",
        )
        self.assertTrue(result.skipped_duplicate)
        self.assertEqual(result.row, existing)

    def test_fetch_exact_returns_available_view(self) -> None:
        view = _available_view()
        row = _snapshot_row(view, semantic_identity="identity-a")
        repo = MagicMock()
        repo.get_exact.return_value = row
        result = fetch_exact_ai_research_summary(repo, "CRM", "identity-a")
        self.assertIsNotNone(result.view)
        assert result.view is not None
        self.assertEqual(result.view.status, "AVAILABLE")
        self.assertEqual(result.view.metadata.validation_outcome if result.view.metadata else "", "persisted")

    def test_context_change_old_retained_new_lookup_misses(self) -> None:
        old_view = _available_view(identity="identity-a")
        old_row = _snapshot_row(old_view, semantic_identity="identity-a")
        repo = MagicMock()
        repo.get_exact.return_value = None
        repo.get_latest.return_value = old_row
        self.assertTrue(symbol_has_stale_persisted_summary(repo, "CRM", "identity-b"))
        miss = fetch_exact_ai_research_summary(repo, "CRM", "identity-b")
        self.assertIsNone(miss.view)

    def test_cross_symbol_isolation(self) -> None:
        crm_view = _available_view("CRM")
        crm_row = _snapshot_row(crm_view, semantic_identity="identity-a")

        def _get_exact(symbol: str, identity: str):
            if symbol == "CRM" and identity == "identity-a":
                return crm_row
            return None

        repo = MagicMock()
        repo.get_exact.side_effect = _get_exact
        crm = fetch_exact_ai_research_summary(repo, "CRM", "identity-a")
        jnj = fetch_exact_ai_research_summary(repo, "JNJ", "identity-a")
        self.assertIsNotNone(crm.view)
        self.assertIsNone(jnj.view)

    def test_serialization_secret_audit(self) -> None:
        payload = _available_view().to_dict()
        payload["api_key"] = "secret-value"
        with self.assertRaises(ValueError):
            audit_persisted_summary_payload(payload)

    def test_persisted_summary_preserves_fields(self) -> None:
        view = _available_view(
            valuation_summary="P/S 3.87; P/FCF 11.16; EV/EBIT 20.14.",
        )
        row = _snapshot_row(view, semantic_identity="identity-a")
        restored = view_from_row(row, semantic_identity="identity-a")
        self.assertEqual(restored.evidence_level, "LIMITED")
        self.assertEqual(restored.model_provider, "openai")
        self.assertEqual(restored.model_name, "gpt-test")
        self.assertIn("3.87", restored.valuation_summary)
        self.assertEqual(restored.generated_at, view.generated_at)

    def test_build_snapshot_payload_roundtrip(self) -> None:
        view = _available_view()
        payload = build_snapshot_payload(view, semantic_identity="identity-a")
        serialized = json.dumps(payload)
        self.assertNotIn("api_key", serialized.lower())
        self.assertNotIn("authorization", serialized.lower())
        self.assertNotIn("raw prompt", serialized.lower())
        self.assertEqual(payload["status"], "AVAILABLE")


class AIResearchSummaryRepositoryTests(unittest.TestCase):
    def test_get_exact_query(self) -> None:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"symbol": "CRM", "semantic_identity": "identity-a"}]
        )
        repo = AIResearchSummaryRepository(client)
        row = repo.get_exact("crm", "identity-a")
        self.assertEqual(row["symbol"], "CRM")

    def test_save_if_absent_conflict_reloads(self) -> None:
        client = MagicMock()
        client.table.return_value.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint 23505"
        )
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"symbol": "CRM", "semantic_identity": "identity-a"}]
        )
        repo = AIResearchSummaryRepository(client)
        row, inserted = repo.save_if_absent(
            {"symbol": "CRM", "semantic_identity": "identity-a"}
        )
        self.assertFalse(inserted)
        self.assertEqual(row["symbol"], "CRM")


class AIResearchSummaryPersistedLookupServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.client.complete.return_value = _valid_summary_json()
        self.unified_service = MagicMock()
        self.unified_service.build_context.return_value = _limited_unified("CRM")
        self.service = AIResearchSummaryService(
            config=_enabled_config(),
            client=self.client,
            unified_research_service=self.unified_service,
        )
        self.identity = compute_context_semantic_identity(
            symbol="CRM",
            participation_result=None,
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
        )

    def test_first_generation_db_miss_one_llm_then_persist(self) -> None:
        repo = MagicMock()
        repo.get_exact.return_value = None
        view = self.service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            force_refresh=True,
        )
        repo.save_if_absent.return_value = (
            _snapshot_row(view, semantic_identity=self.identity),
            True,
        )
        save_result = save_ai_research_summary_snapshot(
            repo,
            view,
            semantic_identity=self.identity,
        )
        self.assertEqual(view.status, "AVAILABLE")
        self.client.complete.assert_called_once()
        self.assertTrue(save_result.saved)
        repo.save_if_absent.assert_called_once()

    def test_persisted_view_avoids_llm(self) -> None:
        persisted = view_from_row(
            _snapshot_row(_available_view(), semantic_identity=self.identity),
            semantic_identity=self.identity,
        )
        view = self.service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            persisted_view=persisted,
        )
        self.assertEqual(view.status, "AVAILABLE")
        self.assertEqual(view.metadata.validation_outcome if view.metadata else "", "persisted")
        self.assertEqual(view.metadata.llm_call_count if view.metadata else -1, 0)
        self.client.complete.assert_not_called()

    def test_same_session_cache_hit_zero_llm(self) -> None:
        first = self.service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            force_refresh=True,
        )
        second = self.service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            cached_view=first,
            cached_identity=self.identity,
        )
        self.assertEqual(self.client.complete.call_count, 1)
        self.assertTrue(second.metadata.cache_hit if second.metadata else False)

    def test_new_session_db_hit_zero_llm(self) -> None:
        persisted = view_from_row(
            _snapshot_row(_available_view(), semantic_identity=self.identity),
            semantic_identity=self.identity,
        )
        view = self.service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            persisted_view=persisted,
        )
        self.client.complete.assert_not_called()
        self.assertEqual(view.metadata.validation_outcome if view.metadata else "", "persisted")

    def test_blocked_participation_zero_llm(self) -> None:
        view = self.service.generate(
            symbol="AAPL",
            research_eligibility=_blocked_eligibility("AAPL", status="FAIL"),
            company_intelligence_view=_ci_view("AAPL"),
            investment_thesis_view=_thesis_view("AAPL"),
            persisted_view=_available_view("AAPL"),
        )
        self.assertEqual(view.status, "UNAVAILABLE")
        self.client.complete.assert_not_called()

    def test_jnj_generic_persisted_lookup(self) -> None:
        self.unified_service.build_context.return_value = _limited_unified("JNJ")
        persisted = view_from_row(
            _snapshot_row(_available_view("JNJ"), semantic_identity="jnj-id"),
            semantic_identity="jnj-id",
        )
        view = self.service.generate(
            symbol="JNJ",
            research_eligibility=_eligible_eligibility("JNJ"),
            company_intelligence_view=_ci_view("JNJ"),
            investment_thesis_view=_thesis_view("JNJ"),
            persisted_view=persisted,
        )
        self.assertEqual(view.symbol, "JNJ")
        self.client.complete.assert_not_called()

    def test_provider_error_not_available(self) -> None:
        disabled = AdviserLlmConfig(
            enabled=False,
            provider="openai",
            model="gpt-test",
            timeout_seconds=10,
            max_output_tokens=800,
            temperature=0.2,
            api_key=None,
        )
        service = AIResearchSummaryService(
            config=disabled,
            client=self.client,
            unified_research_service=self.unified_service,
        )
        view = service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            force_refresh=True,
        )
        self.assertEqual(view.status, "UNAVAILABLE")
        repo = MagicMock()
        result = save_ai_research_summary_snapshot(
            repo,
            view,
            semantic_identity=self.identity,
        )
        self.assertFalse(result.saved)
        repo.save_if_absent.assert_not_called()


class AIResearchSummaryIdentityStabilityPersistenceTests(unittest.TestCase):
    def test_ci_as_of_only_change_same_identity(self) -> None:
        first = _ci_view("CRM")
        second = CompanyIntelligenceView(**{**first.__dict__, "as_of": "2026-08-16T00:00:00Z"})
        identity_a = compute_context_semantic_identity(
            symbol="CRM",
            participation_result=None,
            company_intelligence_view=first,
            investment_thesis_view=_thesis_view("CRM"),
        )
        identity_b = compute_context_semantic_identity(
            symbol="CRM",
            participation_result=None,
            company_intelligence_view=second,
            investment_thesis_view=_thesis_view("CRM"),
        )
        self.assertEqual(identity_a, identity_b)


if __name__ == "__main__":
    unittest.main()
