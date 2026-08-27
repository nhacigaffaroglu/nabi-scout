from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from repositories.candidate_repository import CandidateRepository
from repositories.universe_expansion_run_repository import (
    RUN_STATUS_COMPLETED,
    TRIGGER_SCHEDULED,
    UniverseExpansionRunRepository,
    is_missing_runs_table_error,
)
from services.candidate_identity import (
    merge_preserving_enriched,
    select_canonical_candidate,
)
from services.candidate_price_service import CandidatePriceService
from services.scheduled_universe_expansion_service import (
    evaluate_scheduled_expansion_run,
)
from services.universe_expansion_contract import (
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_RETRYABLE,
    STOP_REASON_SAFETY_CAP,
)
from services.universe_expansion_onboarding_service import (
    onboarding_final_status,
    run_participation_onboarding,
)


ABD_ENRICHED = {
    "id": "abd-avgo",
    "symbol": "AVGO",
    "market": "ABD",
    "asset_type": "Hisse",
    "company_name": "Broadcom Inc.",
    "current_price": 392.99,
    "decision": "İZLE",
    "data_source": "SEC Company Facts + FMP",
    "created_at": "2026-08-11T14:46:59+00:00",
}
US_STUB = {
    "id": "us-avgo",
    "symbol": "AVGO",
    "market": "US",
    "asset_type": "equity",
    "company_name": "AVGO",
    "current_price": None,
    "decision": None,
    "data_source": "universe_expansion",
    "created_at": "2026-08-16T08:41:32+00:00",
}
EXPANSION_INCOMING = {
    "symbol": "AVGO",
    "market": "US",
    "asset_type": "equity",
    "company_name": "AVGO",
    "data_source": "universe_expansion",
}


class _MissingRunsTable:
    def execute(self):
        raise Exception(
            "{'message': \"Could not find the table 'public.universe_expansion_runs' "
            "in the schema cache\", 'code': 'PGRST205'}"
        )

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def insert(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        return self


class _MissingTableClient:
    def table(self, name):
        return _MissingRunsTable()


class CanonicalSelectionTests(unittest.TestCase):
    def test_prefers_enriched_over_stub(self) -> None:
        selected = select_canonical_candidate([US_STUB, ABD_ENRICHED])
        self.assertEqual(selected["id"], ABD_ENRICHED["id"])

    def test_not_random_when_order_flipped(self) -> None:
        first = select_canonical_candidate([US_STUB, ABD_ENRICHED])
        second = select_canonical_candidate([ABD_ENRICHED, US_STUB])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["id"], ABD_ENRICHED["id"])


class MergePreservingTests(unittest.TestCase):
    def test_null_placeholder_does_not_overwrite_enriched(self) -> None:
        patch = merge_preserving_enriched(ABD_ENRICHED, EXPANSION_INCOMING)
        self.assertNotIn("company_name", patch)
        self.assertNotIn("current_price", patch)
        self.assertNotIn("decision", patch)
        self.assertNotIn("data_source", patch)
        self.assertNotIn("market", patch)

    def test_fills_only_empty_fields(self) -> None:
        sparse = {
            "id": "new",
            "symbol": "NEWCO",
            "market": "US",
            "company_name": None,
            "current_price": None,
            "decision": None,
            "data_source": None,
        }
        patch = merge_preserving_enriched(
            sparse,
            {
                "symbol": "NEWCO",
                "participation_status": "Uygun",
                "company_name": "NEWCO",
                "data_source": "universe_expansion",
            },
        )
        self.assertEqual(patch.get("participation_status"), "Uygun")
        self.assertNotIn("company_name", patch)


class ExpansionUpsertReuseTests(unittest.TestCase):
    def test_existing_symbol_does_not_insert_second_stub(self) -> None:
        repo = CandidateRepository(MagicMock())
        repo.list_by_symbol = MagicMock(return_value=[US_STUB, ABD_ENRICHED])
        repo.update = MagicMock(return_value=ABD_ENRICHED)
        repo.upsert_by_symbol = MagicMock()

        result = repo.upsert_expansion_candidate(EXPANSION_INCOMING)

        repo.upsert_by_symbol.assert_not_called()
        self.assertEqual(result["id"], ABD_ENRICHED["id"])
        if repo.update.called:
            patch = repo.update.call_args.args[1]
            self.assertNotIn("current_price", patch)
            self.assertNotEqual(patch.get("company_name"), "AVGO")

    def test_new_symbol_stub_does_not_insert(self) -> None:
        repo = CandidateRepository(MagicMock())
        repo.list_by_symbol = MagicMock(return_value=[])
        repo.upsert_by_symbol = MagicMock()
        payload = {
            "symbol": "NEWCO",
            "market": "US",
            "asset_type": "equity",
            "company_name": "NEWCO",
            "data_source": "universe_expansion",
        }
        result = repo.upsert_expansion_candidate(payload)
        repo.upsert_by_symbol.assert_not_called()
        self.assertIsNone(result)

    def test_new_symbol_with_price_inserts(self) -> None:
        repo = CandidateRepository(MagicMock())
        repo.list_by_symbol = MagicMock(return_value=[])
        payload = {
            "symbol": "NEWCO",
            "market": "US",
            "asset_type": "equity",
            "company_name": "New Company Inc.",
            "current_price": 12.5,
            "data_source": "universe_expansion",
        }
        repo.upsert_by_symbol = MagicMock(return_value={"id": "created", **payload})
        result = repo.upsert_expansion_candidate(payload)
        repo.upsert_by_symbol.assert_called_once()
        self.assertEqual(result["symbol"], "NEWCO")
        self.assertEqual(result["current_price"], 12.5)


class DuplicateLookupTests(unittest.TestCase):
    def test_priced_row_wins_over_stub_in_price_lookup(self) -> None:
        repo = MagicMock()
        repo.list_by_symbol.return_value = [US_STUB, ABD_ENRICHED]
        with patch(
            "services.candidate_price_service.CandidateRepository",
            return_value=repo,
        ):
            service = CandidatePriceService(MagicMock())
        quote = service.get_quote_for_asset("AVGO", "equity", "USD", market="US")
        self.assertTrue(quote.available)
        self.assertAlmostEqual(float(quote.price), 392.99)
        repo.get_by_symbol.assert_not_called()


class OnboardingWriterTests(unittest.TestCase):
    def test_onboarding_calls_expansion_upsert_not_raw_upsert(self) -> None:
        from services.participation_assessment_service import ParticipationAssessmentResult
        from services.participation_intelligence_contract import (
            ASSET_KIND_EQUITY,
            CONFIDENCE_MEDIUM,
            PARTICIPATION_SOURCE_METHODOLOGY,
            PARTICIPATION_STATUS_UYGUN,
            ParticipationAssessment,
        )

        assessment = ParticipationAssessment(
            symbol="AVGO",
            asset_kind=ASSET_KIND_EQUITY,
            status=PARTICIPATION_STATUS_UYGUN,
            source=PARTICIPATION_SOURCE_METHODOLOGY,
            confidence=CONFIDENCE_MEDIUM,
        )
        result = ParticipationAssessmentResult(
            symbol="AVGO",
            methodology_id="msci_islamic_index_series",
            resolved_methodology_version="2025-05",
            participation_assessment=assessment,
            source_evidence=(("provider", "SEC"),),
            sec_available=True,
            participation_provider_calls={"profile": 1},
        )
        view = MagicMock()
        view.available = True
        view.result = result
        candidate_repo = MagicMock(spec=["upsert_expansion_candidate", "upsert_by_symbol"])
        candidate_repo.upsert_expansion_candidate.return_value = ABD_ENRICHED

        with patch(
            "services.universe_expansion_onboarding_service.build_company_report_participation",
            return_value=view,
        ), patch(
            "services.universe_expansion_onboarding_service.evaluate_research_eligibility_from_assessment",
            return_value=MagicMock(research_allowed=True),
        ), patch(
            "services.universe_expansion_onboarding_service.save_participation_assessment_snapshot",
            return_value=MagicMock(saved=True, skipped_duplicate=False),
        ):
            onboarding = run_participation_onboarding("AVGO", candidate_repo=candidate_repo)

        self.assertTrue(onboarding.candidate_upserted)
        self.assertTrue(onboarding.success)
        candidate_repo.upsert_expansion_candidate.assert_called_once()
        candidate_repo.upsert_by_symbol.assert_not_called()

    def _participation_view(self, *, available: bool, status: str = "Uygun", sec_available: bool = True):
        from services.participation_assessment_service import ParticipationAssessmentResult
        from services.participation_intelligence_contract import (
            ASSET_KIND_EQUITY,
            CONFIDENCE_MEDIUM,
            PARTICIPATION_SOURCE_METHODOLOGY,
            ParticipationAssessment,
        )

        view = MagicMock()
        view.available = available
        view.error_message = None if available else "provider_timeout"
        view.result = None
        if available:
            assessment = ParticipationAssessment(
                symbol="XOM",
                asset_kind=ASSET_KIND_EQUITY,
                status=status,
                source=PARTICIPATION_SOURCE_METHODOLOGY,
                confidence=CONFIDENCE_MEDIUM,
            )
            view.result = ParticipationAssessmentResult(
                symbol="XOM",
                methodology_id="msci_islamic_index_series",
                resolved_methodology_version="2025-05",
                participation_assessment=assessment,
                source_evidence=(("provider", "SEC"),),
                sec_available=sec_available,
                participation_provider_calls={"profile": 1},
            )
        return view

    def test_provider_failure_does_not_insert_candidate(self) -> None:
        candidate_repo = MagicMock(spec=["upsert_expansion_candidate", "upsert_by_symbol"])
        view = self._participation_view(available=False)
        with patch(
            "services.universe_expansion_onboarding_service.build_company_report_participation",
            return_value=view,
        ):
            onboarding = run_participation_onboarding("XOM", candidate_repo=candidate_repo)
        self.assertFalse(onboarding.success)
        self.assertFalse(onboarding.candidate_upserted)
        candidate_repo.upsert_expansion_candidate.assert_not_called()
        candidate_repo.upsert_by_symbol.assert_not_called()
        status = onboarding_final_status(onboarding, budget_rate_limited=False)
        self.assertEqual(status, EXPANSION_STATUS_RETRYABLE)

    def test_no_canonical_no_price_skips_stub_and_completes_queue(self) -> None:
        candidate_repo = MagicMock(spec=["upsert_expansion_candidate", "upsert_by_symbol"])
        candidate_repo.upsert_expansion_candidate.return_value = None
        view = self._participation_view(available=True, status="Kontrol Et")
        with patch(
            "services.universe_expansion_onboarding_service.build_company_report_participation",
            return_value=view,
        ), patch(
            "services.universe_expansion_onboarding_service.evaluate_research_eligibility_from_assessment",
            return_value=MagicMock(research_allowed=False),
        ), patch(
            "services.universe_expansion_onboarding_service.save_participation_assessment_snapshot",
            return_value=MagicMock(saved=True, skipped_duplicate=False),
        ):
            onboarding = run_participation_onboarding("XOM", candidate_repo=candidate_repo)
        self.assertFalse(onboarding.candidate_upserted)
        self.assertTrue(onboarding.success)
        self.assertIsNone(onboarding.error_category)
        self.assertEqual(onboarding.participation_status, "Kontrol Et")
        candidate_repo.upsert_expansion_candidate.assert_called_once()
        payload = candidate_repo.upsert_expansion_candidate.call_args.args[0]
        self.assertNotIn("current_price", payload)
        candidate_repo.upsert_by_symbol.assert_not_called()
        status = onboarding_final_status(onboarding, budget_rate_limited=False)
        self.assertEqual(status, EXPANSION_STATUS_COMPLETED)

    def test_existing_canonical_is_preserved(self) -> None:
        candidate_repo = MagicMock(spec=["upsert_expansion_candidate", "upsert_by_symbol"])
        candidate_repo.upsert_expansion_candidate.return_value = ABD_ENRICHED
        view = self._participation_view(available=True, status="Kontrol Et")
        with patch(
            "services.universe_expansion_onboarding_service.build_company_report_participation",
            return_value=view,
        ), patch(
            "services.universe_expansion_onboarding_service.evaluate_research_eligibility_from_assessment",
            return_value=MagicMock(research_allowed=False),
        ), patch(
            "services.universe_expansion_onboarding_service.save_participation_assessment_snapshot",
            return_value=MagicMock(saved=True, skipped_duplicate=False),
        ):
            onboarding = run_participation_onboarding("AVGO", candidate_repo=candidate_repo)
        self.assertTrue(onboarding.candidate_upserted)
        self.assertTrue(onboarding.success)
        candidate_repo.upsert_by_symbol.assert_not_called()
        written = candidate_repo.upsert_expansion_candidate.return_value
        self.assertEqual(written["current_price"], 392.99)
        self.assertEqual(written["company_name"], "Broadcom Inc.")

    def test_scheduled_path_provider_failure_queue_is_retryable(self) -> None:
        from repositories.universe_expansion_repository import UniverseExpansionRepository
        from services.daily_universe_expansion_service import DailyUniverseExpansionService
        from services.universe_expansion_contract import EXPANSION_STATUS_RETRYABLE as QUEUE_RETRYABLE

        queue_repo = UniverseExpansionRepository()
        queue_repo.upsert_pending("XOM", source_universe="pilot", priority=1)
        candidate_repo = MagicMock(spec=["upsert_expansion_candidate", "upsert_by_symbol"])
        view = self._participation_view(available=False)

        def runner(symbol, **kwargs):
            return run_participation_onboarding(
                symbol,
                candidate_repo=kwargs.get("candidate_repo"),
            )

        service = DailyUniverseExpansionService(
            queue_repo=queue_repo,
            onboarding_runner=runner,
        )
        with patch(
            "services.universe_expansion_onboarding_service.build_company_report_participation",
            return_value=view,
        ):
            report = service.run_once(
                max_symbols=1,
                now=datetime(2026, 8, 18, 5, 19, tzinfo=timezone.utc),
                seed_if_empty=False,
                candidate_repo=candidate_repo,
            )
        row = queue_repo.get_by_symbol("XOM")
        self.assertEqual(report.symbols_retryable, 1)
        self.assertEqual(row["status"], QUEUE_RETRYABLE)
        candidate_repo.upsert_expansion_candidate.assert_not_called()

    def test_scheduled_path_no_stub_insert_queue_completes(self) -> None:
        from repositories.universe_expansion_repository import UniverseExpansionRepository
        from services.daily_universe_expansion_service import DailyUniverseExpansionService
        from services.universe_expansion_contract import EXPANSION_STATUS_COMPLETED as QUEUE_COMPLETED

        queue_repo = UniverseExpansionRepository()
        queue_repo.upsert_pending("XOM", source_universe="pilot", priority=1)
        candidate_repo = CandidateRepository(MagicMock())
        candidate_repo.list_by_symbol = MagicMock(return_value=[])
        candidate_repo.upsert_by_symbol = MagicMock()
        view = self._participation_view(available=True, status="Kontrol Et")

        def runner(symbol, **kwargs):
            return run_participation_onboarding(
                symbol,
                candidate_repo=kwargs.get("candidate_repo"),
            )

        service = DailyUniverseExpansionService(
            queue_repo=queue_repo,
            onboarding_runner=runner,
        )
        with patch(
            "services.universe_expansion_onboarding_service.build_company_report_participation",
            return_value=view,
        ), patch(
            "services.universe_expansion_onboarding_service.evaluate_research_eligibility_from_assessment",
            return_value=MagicMock(research_allowed=False),
        ), patch(
            "services.universe_expansion_onboarding_service.save_participation_assessment_snapshot",
            return_value=MagicMock(saved=True, skipped_duplicate=False),
        ):
            report = service.run_once(
                max_symbols=1,
                now=datetime(2026, 8, 18, 5, 19, tzinfo=timezone.utc),
                seed_if_empty=False,
                candidate_repo=candidate_repo,
            )
        row = queue_repo.get_by_symbol("XOM")
        candidate_repo.upsert_by_symbol.assert_not_called()
        self.assertEqual(report.symbols_retryable, 0)
        self.assertEqual(report.symbols_completed, 1)
        self.assertEqual(row["status"], QUEUE_COMPLETED)
        self.assertIsNone(row["last_error_category"])
        self.assertIsNone(row["next_retry_at"])
        self.assertEqual(row["participation_status"], "Kontrol Et")
        self.assertFalse(row["research_allowed"])
        self.assertIsNotNone(row["completed_at"])


class MissingRunsTableTests(unittest.TestCase):
    def test_missing_table_does_not_block_scheduled_run(self) -> None:
        repo = UniverseExpansionRunRepository(_MissingTableClient())
        should_run, reason, existing = evaluate_scheduled_expansion_run(
            repo,
            run_date=date(2026, 8, 17),
            now=datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc),
            trigger_type="scheduled",
        )
        self.assertTrue(should_run)
        self.assertIsNone(reason)
        self.assertIsNone(existing)
        self.assertFalse(repo.ledger_available)

    def test_missing_table_detector(self) -> None:
        self.assertTrue(
            is_missing_runs_table_error(
                Exception("Could not find the table 'public.universe_expansion_runs' PGRST205")
            )
        )

    def test_duplicate_run_guard_still_blocks_when_ledger_available(self) -> None:
        repo = UniverseExpansionRunRepository()
        run_date = date(2026, 8, 17)
        repo.start_run(
            run_id="run-1",
            run_date=run_date,
            trigger_type=TRIGGER_SCHEDULED,
            dry_run=False,
            allow_second_run_today=False,
            started_at=datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc),
        )
        repo.finalize_run(
            "run-1",
            status=RUN_STATUS_COMPLETED,
            stop_reason="SAFETY_CAP",
            report={"symbols_started": 6, "symbols_completed": 6},
            finished_at=datetime(2026, 8, 17, 5, 10, tzinfo=timezone.utc),
        )
        should_run, reason, _ = evaluate_scheduled_expansion_run(
            repo,
            run_date=run_date,
            trigger_type=TRIGGER_SCHEDULED,
        )
        self.assertFalse(should_run)
        self.assertIn("already completed", reason or "")


class ProviderAndSourceContractTests(unittest.TestCase):
    def test_expansion_modules_have_no_llm_or_ci(self) -> None:
        root = Path(__file__).resolve().parents[1]
        files = [
            "services/daily_universe_expansion_service.py",
            "services/universe_expansion_onboarding_service.py",
            "services/scheduled_universe_expansion_service.py",
            "scripts/run_daily_universe_expansion.py",
            "services/candidate_identity.py",
        ]
        for rel in files:
            source = (root / rel).read_text(encoding="utf-8").lower()
            with self.subTest(path=rel):
                self.assertNotIn("openai", source)
                self.assertNotIn("companyintelligence", source)

    def test_workflow_still_scheduled(self) -> None:
        content = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "daily_universe_expansion.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('cron: "0 3 * * *"', content)
        self.assertIn("--trigger-type scheduled", content)
        scan = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "daily_scan.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('cron: "0 6 * * *"', scan)

    def test_safety_cap_constant_unchanged(self) -> None:
        self.assertEqual(STOP_REASON_SAFETY_CAP, "SAFETY_CAP")

    def test_provider_budget_defaults_unchanged(self) -> None:
        config = UniverseExpansionBudgetConfig()
        self.assertEqual(config.fmp_daily_call_budget, 250)
        self.assertEqual(config.sec_daily_call_budget, 500)
        self.assertEqual(config.fmp_interactive_reserve_pct, 0.35)
        self.assertEqual(config.fmp_expansion_reserve_pct, 0.50)
        self.assertEqual(config.sec_expansion_reserve_pct, 0.60)
        self.assertEqual(config.max_symbols_per_run, 30)
        self.assertEqual(config.discovery_capacity, 8000)
        self.assertEqual(config.max_new_symbols_per_ingest, 30)


if __name__ == "__main__":
    unittest.main()
