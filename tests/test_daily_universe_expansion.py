from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from config.universe_expansion_sources import (
    ETF_SYMBOLS,
    dedupe_expansion_symbols,
)
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.daily_universe_expansion_service import DailyUniverseExpansionService
from services.provider_budget_service import ProviderBudgetManager
from services.provider_call_ledger import ProviderCallLedger
from services.universe_expansion_contract import (
    ERROR_CATEGORY_PLAN_RESTRICTED,
    ERROR_CATEGORY_RATE_LIMIT,
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_IN_PROGRESS,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
    PROVIDER_FMP,
    PROVIDER_SEC,
    STOP_REASON_BUDGET_EXHAUSTED,
    STOP_REASON_RATE_LIMIT,
    STOP_REASON_SAFETY_CAP,
)
from services.universe_expansion_cost_model import estimate_participation_minimum_cost
from services.universe_expansion_onboarding_service import (
    OnboardingResult,
    compute_next_retry_at,
    onboarding_final_status,
    run_participation_onboarding,
)
from services.universe_expansion_seed_service import seed_universe_expansion_queue
from services.supabase_admin_client import (
    RLS_ADMIN_REQUIRED_MESSAGE,
    SupabaseAdminClientError,
    raise_friendly_rls_error,
)


def _now() -> datetime:
    return datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _completed_onboarding(symbol: str, *, status: str = "Uygun") -> OnboardingResult:
    return OnboardingResult(
        symbol=symbol,
        success=True,
        participation_status=status,
        research_allowed=status == "Uygun",
        provider_calls={"profile": 1, "sec_inline_xbrl": 0},
        snapshot_saved=True,
        candidate_upserted=True,
    )


class UniverseExpansionRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = UniverseExpansionRepository()

    def test_pending_symbol_selected(self) -> None:
        row = self.repo.upsert_pending("TEST", source_universe="pilot", priority=1)
        eligible = self.repo.list_eligible(_now())
        self.assertEqual(eligible[0]["symbol"], "TEST")
        self.assertEqual(row["status"], EXPANSION_STATUS_PENDING)

    def test_completed_symbol_not_reprocessed(self) -> None:
        row = self.repo.upsert_pending("DONE", source_universe="pilot", priority=1)
        self.repo.finalize(row["id"], {"status": EXPANSION_STATUS_COMPLETED})
        eligible = self.repo.list_eligible(_now())
        self.assertEqual(eligible, [])

    def test_retryable_before_next_retry_skipped_by_service(self) -> None:
        row = self.repo.upsert_pending("RETRY", source_universe="pilot", priority=1)
        future = (_now() + timedelta(hours=5)).isoformat()
        self.repo.finalize(
            row["id"],
            {"status": EXPANSION_STATUS_RETRYABLE, "next_retry_at": future},
        )
        eligible = self.repo.list_eligible(_now())
        self.assertEqual(eligible, [])

    def test_stale_in_progress_recovered(self) -> None:
        row = self.repo.upsert_pending("STALE", source_universe="pilot", priority=1)
        stale_time = (_now() - timedelta(hours=3)).isoformat()
        self.repo.finalize(
            row["id"],
            {
                "status": EXPANSION_STATUS_IN_PROGRESS,
                "claimed_at": stale_time,
            },
        )
        recovered = self.repo.recover_stale_in_progress(_now(), stale_minutes=60)
        self.assertEqual(recovered, 1)
        updated = self.repo.get_by_symbol("STALE")
        assert updated is not None
        self.assertEqual(updated["status"], EXPANSION_STATUS_RETRYABLE)

    def test_concurrency_claim_protection(self) -> None:
        row = self.repo.upsert_pending("CLAIM", source_universe="pilot", priority=1)
        first = self.repo.claim(row["id"], run_id="run-a", now=_now())
        second = self.repo.claim(row["id"], run_id="run-b", now=_now())
        self.assertIsNotNone(first)
        self.assertIsNone(second)


class ProviderBudgetTests(unittest.TestCase):
    def test_interactive_reserve_protected(self) -> None:
        config = UniverseExpansionBudgetConfig(
            fmp_daily_call_budget=100,
            fmp_interactive_reserve_pct=0.35,
            fmp_expansion_reserve_pct=0.50,
        )
        budget = ProviderBudgetManager(config)
        self.assertEqual(budget.fmp.expansion_budget, 50)
        self.assertTrue(budget.can_spend(PROVIDER_FMP, "profile", 50))
        self.assertFalse(budget.can_spend(PROVIDER_FMP, "profile", 51))

    def test_budget_insufficient_not_started(self) -> None:
        config = UniverseExpansionBudgetConfig(
            fmp_daily_call_budget=1,
            sec_daily_call_budget=1,
            fmp_expansion_reserve_pct=1.0,
            sec_expansion_reserve_pct=1.0,
        )
        service = DailyUniverseExpansionService(
            queue_repo=UniverseExpansionRepository(),
            budget_config=config,
        )
        repo = service.queue_repo
        repo.upsert_pending("LOW", source_universe="pilot", priority=1)
        report = service.run_once(max_symbols=1, dry_run=False, now=_now())
        self.assertEqual(report.stop_reason, STOP_REASON_BUDGET_EXHAUSTED)
        row = repo.get_by_symbol("LOW")
        assert row is not None
        self.assertEqual(row["status"], EXPANSION_STATUS_PENDING)

    def test_actual_spend_recorded(self) -> None:
        budget = ProviderBudgetManager(UniverseExpansionBudgetConfig(fmp_daily_call_budget=10))
        budget.record_spend(PROVIDER_FMP, "profile", 2)
        self.assertEqual(budget.fmp.spent, 2)

    def test_cache_hit_costs_zero_remote_calls(self) -> None:
        ledger = ProviderCallLedger()
        ledger.record_cache_hit(PROVIDER_FMP, "profile")
        self.assertEqual(ledger.provider_totals().get(PROVIDER_FMP, 0), 0)
        self.assertEqual(ledger.cache_hits["fmp:profile"], 1)


class DailyExpansionServiceTests(unittest.TestCase):
    def test_dry_run_makes_no_provider_calls(self) -> None:
        calls = {"count": 0}

        def runner(symbol, **kwargs):
            calls["count"] += 1
            return _completed_onboarding(symbol)

        service = DailyUniverseExpansionService(
            queue_repo=UniverseExpansionRepository(),
            onboarding_runner=runner,
        )
        report = service.run_once(dry_run=True, max_symbols=3, now=_now())
        self.assertEqual(calls["count"], 0)
        self.assertGreater(report.symbols_started, 0)

    def test_dry_run_makes_no_db_mutations(self) -> None:
        repo = UniverseExpansionRepository()
        service = DailyUniverseExpansionService(queue_repo=repo)
        service.run_once(dry_run=True, max_symbols=2, now=_now())
        self.assertEqual(repo.list_all(), [])

    def test_second_run_idempotent(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("IDEM", source_universe="pilot", priority=1)
        service = DailyUniverseExpansionService(
            queue_repo=repo,
            onboarding_runner=lambda symbol, **kwargs: _completed_onboarding(symbol),
        )
        first = service.run_once(max_symbols=1, now=_now(), seed_if_empty=False)
        second = service.run_once(max_symbols=1, now=_now(), seed_if_empty=False)
        self.assertEqual(first.symbols_completed, 1)
        self.assertEqual(second.symbols_started, 0)
        row = repo.get_by_symbol("IDEM")
        assert row is not None
        self.assertEqual(row["status"], EXPANSION_STATUS_COMPLETED)

    def test_rate_limit_stops_run(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("RL", source_universe="pilot", priority=1)

        def runner(symbol, **kwargs):
            return OnboardingResult(
                symbol=symbol,
                success=False,
                error_category=ERROR_CATEGORY_RATE_LIMIT,
            )

        service = DailyUniverseExpansionService(queue_repo=repo, onboarding_runner=runner)
        report = service.run_once(max_symbols=5, now=_now(), seed_if_empty=False)
        self.assertEqual(report.stop_reason, STOP_REASON_RATE_LIMIT)

    def test_onboarding_exception_finalized_retryable(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("CRASH", source_universe="pilot", priority=1)

        def runner(symbol, **kwargs):
            raise AttributeError("tuple has no attribute get")

        service = DailyUniverseExpansionService(queue_repo=repo, onboarding_runner=runner)
        report = service.run_once(max_symbols=1, now=_now(), seed_if_empty=False)
        row = repo.get_by_symbol("CRASH")
        assert row is not None
        self.assertEqual(row["status"], EXPANSION_STATUS_RETRYABLE)
        self.assertEqual(report.symbols_retryable, 1)
        def runner(symbol, **kwargs):
            return OnboardingResult(
                symbol=symbol,
                success=True,
                participation_status="Uygun Değil",
                research_allowed=False,
                company_intelligence_calls=0,
            )

        repo = UniverseExpansionRepository()
        repo.upsert_pending("BLOCK", source_universe="pilot", priority=1)
        service = DailyUniverseExpansionService(queue_repo=repo, onboarding_runner=runner)
        report = service.run_once(max_symbols=1, now=_now(), seed_if_empty=False)
        detail = report.symbol_details[0]
        assert detail.result is not None
        self.assertEqual(detail.result.company_intelligence_calls, 0)

    def test_safety_cap_stops_and_leaves_remaining_pending(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("AAA", source_universe="pilot", priority=1)
        repo.upsert_pending("BBB", source_universe="pilot", priority=2)
        repo.upsert_pending("CCC", source_universe="pilot", priority=3)
        service = DailyUniverseExpansionService(
            queue_repo=repo,
            onboarding_runner=lambda symbol, **kwargs: _completed_onboarding(symbol),
        )
        report = service.run_once(max_symbols=2, now=_now(), seed_if_empty=False)
        self.assertEqual(report.stop_reason, STOP_REASON_SAFETY_CAP)
        self.assertEqual(report.symbols_completed, 2)
        self.assertEqual(repo.get_by_symbol("CCC")["status"], EXPANSION_STATUS_PENDING)

    def test_later_run_resumes_remaining_pending(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("AAA", source_universe="pilot", priority=1)
        repo.upsert_pending("BBB", source_universe="pilot", priority=2)
        repo.upsert_pending("CCC", source_universe="pilot", priority=3)
        service = DailyUniverseExpansionService(
            queue_repo=repo,
            onboarding_runner=lambda symbol, **kwargs: _completed_onboarding(symbol),
        )
        first = service.run_once(max_symbols=2, now=_now(), seed_if_empty=False)
        self.assertEqual(first.stop_reason, STOP_REASON_SAFETY_CAP)
        second = service.run_once(max_symbols=2, now=_now(), seed_if_empty=False)
        self.assertEqual(repo.get_by_symbol("AAA")["status"], EXPANSION_STATUS_COMPLETED)
        self.assertEqual(repo.get_by_symbol("BBB")["status"], EXPANSION_STATUS_COMPLETED)
        self.assertEqual(repo.get_by_symbol("CCC")["status"], EXPANSION_STATUS_COMPLETED)
        self.assertEqual(second.symbols_completed, 1)
        self.assertNotEqual(second.stop_reason, STOP_REASON_SAFETY_CAP)


class SourceUniverseTests(unittest.TestCase):
    def test_duplicate_source_universe_symbol_deduped(self) -> None:
        symbols = [row[0] for row in dedupe_expansion_symbols()]
        self.assertEqual(len(symbols), len(set(symbols)))

    def test_etf_excluded(self) -> None:
        symbols = {row[0] for row in dedupe_expansion_symbols()}
        self.assertTrue(ETF_SYMBOLS.isdisjoint(symbols))

    def test_bounded_universe_at_least_50(self) -> None:
        self.assertGreaterEqual(len(dedupe_expansion_symbols()), 50)


class OnboardingPersistenceTests(unittest.TestCase):
    def test_tuple_source_evidence_onboarding_succeeds(self) -> None:
        from services.participation_assessment_service import ParticipationAssessmentResult
        from services.participation_intelligence_contract import (
            ParticipationAssessment,
            PARTICIPATION_SOURCE_METHODOLOGY,
            PARTICIPATION_STATUS_UYGUN,
            CONFIDENCE_MEDIUM,
            ASSET_KIND_EQUITY,
        )

        assessment = ParticipationAssessment(
            symbol="XYZ",
            asset_kind=ASSET_KIND_EQUITY,
            status=PARTICIPATION_STATUS_UYGUN,
            source=PARTICIPATION_SOURCE_METHODOLOGY,
            confidence=CONFIDENCE_MEDIUM,
        )
        result = ParticipationAssessmentResult(
            symbol="XYZ",
            methodology_id="msci_islamic_index_series",
            resolved_methodology_version="2025-05",
            participation_assessment=assessment,
            source_evidence=(
                ("provider", "SEC"),
                ("cik", "123"),
                ("sec_field:revenue", "extract_financials"),
            ),
            sec_available=True,
            participation_provider_calls={"profile": 1},
        )
        view = MagicMock()
        view.available = True
        view.result = result
        candidate_repo = MagicMock()

        with unittest.mock.patch(
            "services.universe_expansion_onboarding_service.build_company_report_participation",
            return_value=view,
        ), unittest.mock.patch(
            "services.universe_expansion_onboarding_service.evaluate_research_eligibility_from_assessment",
            return_value=MagicMock(research_allowed=True),
        ), unittest.mock.patch(
            "services.universe_expansion_onboarding_service.save_participation_assessment_snapshot",
            return_value=MagicMock(saved=True, skipped_duplicate=False),
        ):
            onboarding = run_participation_onboarding(
                "XYZ",
                candidate_repo=candidate_repo,
            )

        self.assertTrue(onboarding.success)
        self.assertTrue(onboarding.candidate_upserted)
        payload = candidate_repo.upsert_expansion_candidate.call_args.args[0]
        self.assertEqual(payload["symbol"], "XYZ")
        self.assertEqual(payload["company_name"], "XYZ")

    def test_absent_profile_safe_empty_mapping(self) -> None:
        from services.universe_expansion_candidate_payload import (
            build_expansion_candidate_payload,
        )
        from services.participation_assessment_service import ParticipationAssessmentResult
        from services.participation_intelligence_contract import (
            ParticipationAssessment,
            PARTICIPATION_SOURCE_METHODOLOGY,
            PARTICIPATION_STATUS_KONTROL_ET,
            CONFIDENCE_LOW,
            ASSET_KIND_EQUITY,
        )

        assessment = ParticipationAssessment(
            symbol="ABC",
            asset_kind=ASSET_KIND_EQUITY,
            status=PARTICIPATION_STATUS_KONTROL_ET,
            source=PARTICIPATION_SOURCE_METHODOLOGY,
            confidence=CONFIDENCE_LOW,
        )
        result = ParticipationAssessmentResult(
            symbol="ABC",
            methodology_id="msci_islamic_index_series",
            resolved_methodology_version="2025-05",
            participation_assessment=assessment,
            source_evidence=(("provider", "SEC"),),
        )
        payload = build_expansion_candidate_payload(result, "ABC")
        self.assertEqual(payload["company_name"], "ABC")
        self.assertEqual(payload["data_source"], "universe_expansion")

    def test_uygun_persists_via_runner_contract(self) -> None:
        view = MagicMock()
        view.available = True
        view.result = MagicMock()
        view.result.participation_assessment.status = "Uygun"
        view.result.participation_provider_calls = {"profile": 1}
        view.result.sec_available = True
        view.result.source_evidence = (("provider", "SEC"),)
        view.result.symbol = "ABC"

        with unittest.mock.patch(
            "services.universe_expansion_onboarding_service.build_company_report_participation",
            return_value=view,
        ), unittest.mock.patch(
            "services.universe_expansion_onboarding_service.evaluate_research_eligibility_from_assessment",
            return_value=MagicMock(research_allowed=True),
        ), unittest.mock.patch(
            "services.universe_expansion_onboarding_service.save_participation_assessment_snapshot",
            return_value=MagicMock(saved=True, skipped_duplicate=False),
        ):
            result = run_participation_onboarding("ABC")
        self.assertTrue(result.success)
        self.assertEqual(result.participation_status, "Uygun")

    def test_kontrol_et_persists(self) -> None:
        result = onboarding_final_status(
            OnboardingResult(
                symbol="X",
                success=True,
                participation_status="Kontrol Et",
                research_allowed=False,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(result, EXPANSION_STATUS_COMPLETED)

    def test_uygun_degil_persists(self) -> None:
        result = onboarding_final_status(
            OnboardingResult(
                symbol="X",
                success=True,
                participation_status="Uygun Değil",
                research_allowed=False,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(result, EXPANSION_STATUS_COMPLETED)


class RetryPolicyTests(unittest.TestCase):
    def test_retryable_scheduled_correctly(self) -> None:
        retry_at = compute_next_retry_at(
            _now(),
            error_category=ERROR_CATEGORY_RATE_LIMIT,
            attempt_count=2,
            default_hours=6,
            plan_restricted_days=7,
        )
        self.assertIsNotNone(retry_at)

    def test_plan_restricted_long_backoff(self) -> None:
        retry_at = compute_next_retry_at(
            _now(),
            error_category=ERROR_CATEGORY_PLAN_RESTRICTED,
            attempt_count=1,
            default_hours=6,
            plan_restricted_days=7,
        )
        assert retry_at is not None
        parsed = datetime.fromisoformat(retry_at)
        self.assertGreater(parsed, _now() + timedelta(days=6))


class MigrationContractTests(unittest.TestCase):
    def test_queue_migration_contract(self) -> None:
        path = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "database"
            / "migration_universe_expansion_queue.sql"
        )
        sql = path.read_text(encoding="utf-8")
        for column in (
            "symbol",
            "source_universe",
            "priority",
            "status",
            "attempt_count",
            "provider_calls_used",
            "participation_status",
            "research_allowed",
        ):
            self.assertIn(column, sql)
        self.assertIn("PRE-DEPLOY MIGRATION REQUIRED", sql)
        self.assertIn("to authenticated", sql.lower())
        self.assertNotIn("to anon", sql.lower())
        self.assertIn("enable row level security", sql.lower())


class RlsSeedProtectionTests(unittest.TestCase):
    def test_repository_maps_rls_violation_to_friendly_error(self) -> None:
        client = MagicMock()
        exc = Exception("new row violates row-level security policy")
        exc.code = "42501"
        select_execute = MagicMock(return_value=MagicMock(data=[]))
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute = (
            select_execute
        )
        client.table.return_value.upsert.return_value.execute.side_effect = exc
        repo = UniverseExpansionRepository(client)
        with self.assertRaises(SupabaseAdminClientError) as ctx:
            repo.upsert_pending("RLS", source_universe="pilot", priority=1)
        self.assertIn("publishable key cannot bypass RLS", str(ctx.exception))

    def test_dry_run_performs_zero_db_mutations(self) -> None:
        repo = UniverseExpansionRepository()
        service = DailyUniverseExpansionService(queue_repo=repo)
        report = service.run_once(dry_run=True, max_symbols=2, now=_now())
        self.assertEqual(repo.list_all(), [])
        self.assertGreater(report.symbols_started, 0)


class SeedServiceTests(unittest.TestCase):
    def test_seed_inserts_pending_rows(self) -> None:
        repo = UniverseExpansionRepository()
        inserted = seed_universe_expansion_queue(repo)
        self.assertGreater(inserted, 0)
        self.assertEqual(
            repo.get_by_symbol(dedupe_expansion_symbols()[0][0])["status"],
            EXPANSION_STATUS_PENDING,
        )


class ReportSecurityTests(unittest.TestCase):
    def test_report_has_no_secrets(self) -> None:
        service = DailyUniverseExpansionService(
            queue_repo=UniverseExpansionRepository(),
            onboarding_runner=lambda symbol, **kwargs: _completed_onboarding(symbol),
        )
        repo = service.queue_repo
        repo.upsert_pending("SECFREE", source_universe="pilot", priority=1)
        report = service.run_once(max_symbols=1, now=_now(), seed_if_empty=False)
        payload = str(report.to_dict())
        for secret in ("api_key", "Authorization", "Bearer", "password"):
            self.assertNotIn(secret, payload.lower())


if __name__ == "__main__":
    unittest.main()
