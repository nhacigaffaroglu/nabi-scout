from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.fmp_client import FMPError
from services.participation_intelligence_contract import (
    ASSET_KIND_EQUITY,
    CONFIDENCE_MEDIUM,
    PARTICIPATION_SOURCE_METHODOLOGY,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    ParticipationAssessment,
)
from services.universe_expansion_contract import (
    ERROR_CATEGORY_PLAN_RESTRICTED,
    ERROR_CATEGORY_PROVIDER_ERROR,
    ERROR_CATEGORY_RATE_LIMIT,
    EXPANSION_STATUS_BLOCKED,
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
)
from services.universe_expansion_onboarding_service import (
    OnboardingResult,
    compute_next_retry_at,
    onboarding_final_status,
    run_participation_onboarding,
)
from services.universe_expansion_queue_reconciliation import (
    CONTROL_UYGUN_SYMBOLS,
    reconcile_retryable_completed_assessments,
)
from services.universe_expansion_candidate_payload import build_expansion_candidate_payload


def _now() -> datetime:
    return datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc)


def _assessment_result(*, status: str, sec_available: bool = True, symbol: str = "XOM"):
    from services.participation_assessment_service import ParticipationAssessmentResult

    assessment = ParticipationAssessment(
        symbol=symbol,
        asset_kind=ASSET_KIND_EQUITY,
        status=status,
        source=PARTICIPATION_SOURCE_METHODOLOGY,
        confidence=CONFIDENCE_MEDIUM,
    )
    return ParticipationAssessmentResult(
        symbol=symbol,
        methodology_id="msci_islamic_index_series",
        resolved_methodology_version="2025-05",
        participation_assessment=assessment,
        source_evidence=(("provider", "SEC"),),
        sec_available=sec_available,
        participation_provider_calls={"profile": 1},
    )


def _view(*, status: str, sec_available: bool = True, symbol: str = "XOM"):
    view = MagicMock()
    view.available = True
    view.error_message = None
    view.result = _assessment_result(status=status, sec_available=sec_available, symbol=symbol)
    return view


def _run_onboarding(view, *, candidate_repo=None, research_allowed=False):
    with patch(
        "services.universe_expansion_onboarding_service.build_company_report_participation",
        return_value=view,
    ), patch(
        "services.universe_expansion_onboarding_service.evaluate_research_eligibility_from_assessment",
        return_value=MagicMock(research_allowed=research_allowed),
    ), patch(
        "services.universe_expansion_onboarding_service.save_participation_assessment_snapshot",
        return_value=MagicMock(saved=True, skipped_duplicate=False),
    ):
        return run_participation_onboarding("XOM", candidate_repo=candidate_repo)


class QueueSemanticsCanonicalCompletionTests(unittest.TestCase):
    def test_uygun_completed(self) -> None:
        status = onboarding_final_status(
            OnboardingResult(
                symbol="ADBE",
                success=True,
                participation_status=PARTICIPATION_STATUS_UYGUN,
                research_allowed=True,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(status, EXPANSION_STATUS_COMPLETED)

    def test_uygun_degil_completed(self) -> None:
        status = onboarding_final_status(
            OnboardingResult(
                symbol="JPM",
                success=True,
                participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL,
                research_allowed=False,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(status, EXPANSION_STATUS_COMPLETED)

    def test_kontrol_et_missing_npr_completed(self) -> None:
        status = onboarding_final_status(
            OnboardingResult(
                symbol="ABT",
                success=True,
                participation_status=PARTICIPATION_STATUS_KONTROL_ET,
                research_allowed=False,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(status, EXPANSION_STATUS_COMPLETED)

    def test_kontrol_et_missing_debt_completed(self) -> None:
        status = onboarding_final_status(
            OnboardingResult(
                symbol="BRK-B",
                success=True,
                participation_status=PARTICIPATION_STATUS_KONTROL_ET,
                research_allowed=False,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(status, EXPANSION_STATUS_COMPLETED)

    def test_kontrol_et_missing_cash_ib_completed(self) -> None:
        status = onboarding_final_status(
            OnboardingResult(
                symbol="BLK",
                success=True,
                participation_status=PARTICIPATION_STATUS_KONTROL_ET,
                research_allowed=False,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(status, EXPANSION_STATUS_COMPLETED)

    def test_kontrol_et_missing_ar_completed(self) -> None:
        status = onboarding_final_status(
            OnboardingResult(
                symbol="COST",
                success=True,
                participation_status=PARTICIPATION_STATUS_KONTROL_ET,
                research_allowed=False,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(status, EXPANSION_STATUS_COMPLETED)

    def test_kontrol_et_sec_unavailable_canonical_assessment_completed(self) -> None:
        onboarding = _run_onboarding(_view(status=PARTICIPATION_STATUS_KONTROL_ET, sec_available=False))
        self.assertEqual(onboarding.participation_status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertTrue(onboarding.success)
        self.assertIsNone(onboarding.error_category)
        self.assertFalse(onboarding.research_allowed)
        self.assertEqual(
            onboarding_final_status(onboarding, budget_rate_limited=False),
            EXPANSION_STATUS_COMPLETED,
        )
        self.assertIsNone(
            compute_next_retry_at(
                _now(),
                error_category=onboarding.error_category,
                attempt_count=2,
                default_hours=6,
                plan_restricted_days=7,
            )
        )


class QueueSemanticsExecutionFailureTests(unittest.TestCase):
    def test_view_unavailable_is_retryable(self) -> None:
        view = MagicMock()
        view.available = False
        view.result = None
        view.error_message = "provider_timeout"
        onboarding = _run_onboarding(view)
        self.assertFalse(onboarding.success)
        self.assertEqual(onboarding.participation_status, "")
        self.assertEqual(
            onboarding_final_status(onboarding, budget_rate_limited=False),
            EXPANSION_STATUS_RETRYABLE,
        )

    def test_rate_limit_is_retryable_with_backoff(self) -> None:
        onboarding = OnboardingResult(
            symbol="XOM",
            success=False,
            error_category=ERROR_CATEGORY_RATE_LIMIT,
            error_message="FMPError",
        )
        self.assertEqual(
            onboarding_final_status(onboarding, budget_rate_limited=False),
            EXPANSION_STATUS_RETRYABLE,
        )
        retry_at = compute_next_retry_at(
            _now(),
            error_category=ERROR_CATEGORY_RATE_LIMIT,
            attempt_count=2,
            default_hours=6,
            plan_restricted_days=7,
        )
        self.assertIsNotNone(retry_at)
        parsed = datetime.fromisoformat(str(retry_at))
        self.assertGreaterEqual(parsed, _now())

    def test_unexpected_provider_exception_follows_classifier(self) -> None:
        with patch(
            "services.universe_expansion_onboarding_service.build_company_report_participation",
            side_effect=FMPError("boom", error_class="http_error"),
        ):
            onboarding = run_participation_onboarding("XOM")
        self.assertFalse(onboarding.success)
        self.assertEqual(onboarding.error_category, ERROR_CATEGORY_PROVIDER_ERROR)
        self.assertEqual(
            onboarding_final_status(onboarding, budget_rate_limited=False),
            EXPANSION_STATUS_RETRYABLE,
        )

    def test_plan_restricted_abort_remains_blocked(self) -> None:
        onboarding = OnboardingResult(
            symbol="XOM",
            success=False,
            error_category=ERROR_CATEGORY_PLAN_RESTRICTED,
        )
        self.assertEqual(
            onboarding_final_status(onboarding, budget_rate_limited=False),
            EXPANSION_STATUS_BLOCKED,
        )


class QueueSemanticsCandidateContractTests(unittest.TestCase):
    def test_upsert_failure_does_not_change_participation_or_reopen_retryable(self) -> None:
        candidate_repo = MagicMock(spec=["upsert_expansion_candidate", "upsert_by_symbol"])
        candidate_repo.upsert_expansion_candidate.side_effect = RuntimeError("db")
        onboarding = _run_onboarding(
            _view(status=PARTICIPATION_STATUS_KONTROL_ET),
            candidate_repo=candidate_repo,
        )
        self.assertEqual(onboarding.participation_status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertFalse(onboarding.candidate_upserted)
        self.assertTrue(onboarding.success)
        self.assertIsNone(onboarding.error_category)
        self.assertEqual(
            onboarding_final_status(onboarding, budget_rate_limited=False),
            EXPANSION_STATUS_COMPLETED,
        )
        candidate_repo.upsert_by_symbol.assert_not_called()
        payload = candidate_repo.upsert_expansion_candidate.call_args.args[0]
        self.assertNotIn("current_price", payload)

    def test_payload_still_omits_current_price(self) -> None:
        payload = build_expansion_candidate_payload(
            _assessment_result(status=PARTICIPATION_STATUS_KONTROL_ET),
            "XOM",
        )
        self.assertNotIn("current_price", payload)
        self.assertEqual(payload["data_source"], "universe_expansion")

    def test_existing_priced_candidate_preserved(self) -> None:
        candidate_repo = MagicMock(spec=["upsert_expansion_candidate", "upsert_by_symbol"])
        candidate_repo.upsert_expansion_candidate.return_value = {
            "id": "priced",
            "symbol": "AVGO",
            "current_price": 392.99,
            "company_name": "Broadcom Inc.",
        }
        onboarding = _run_onboarding(
            _view(status=PARTICIPATION_STATUS_KONTROL_ET, symbol="AVGO"),
            candidate_repo=candidate_repo,
        )
        self.assertTrue(onboarding.candidate_upserted)
        candidate_repo.upsert_by_symbol.assert_not_called()
        written = candidate_repo.upsert_expansion_candidate.return_value
        self.assertEqual(written["current_price"], 392.99)


class QueueSemanticsFairnessAndCapTests(unittest.TestCase):
    def test_pending_precedes_retryable(self) -> None:
        repo = UniverseExpansionRepository()
        retry = repo.upsert_pending("RETRY", source_universe="retry", priority=1)
        repo.finalize(
            retry["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "next_retry_at": _now().isoformat(),
            },
        )
        repo.upsert_pending("FRESH", source_universe="fresh", priority=90)
        eligible = repo.list_eligible(_now(), limit=10)
        self.assertEqual([row["symbol"] for row in eligible], ["FRESH", "RETRY"])

    def test_uygun_degil_excluded_from_reprocessing(self) -> None:
        repo = UniverseExpansionRepository()
        rejected = repo.upsert_pending("JPM", source_universe="sp500", priority=1)
        repo.finalize(
            rejected["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": PARTICIPATION_STATUS_UYGUN_DEGIL,
                "next_retry_at": _now().isoformat(),
            },
        )
        repo.upsert_pending("ADP", source_universe="nasdaq", priority=50)
        symbols = [row["symbol"] for row in repo.list_eligible(_now(), limit=10)]
        self.assertIn("ADP", symbols)
        self.assertNotIn("JPM", symbols)

    def test_max_symbols_per_run_remains_30(self) -> None:
        config = UniverseExpansionBudgetConfig()
        self.assertEqual(config.max_symbols_per_run, 30)
        self.assertEqual(config.max_new_symbols_per_ingest, 30)

    def test_completed_row_is_not_eligible_again(self) -> None:
        repo = UniverseExpansionRepository()
        done = repo.upsert_pending("ABT", source_universe="sp500", priority=1)
        repo.finalize(
            done["id"],
            {
                "status": EXPANSION_STATUS_COMPLETED,
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
            },
        )
        self.assertEqual(repo.list_eligible(_now()), [])


class ControlGroupUygunUnchangedTests(unittest.TestCase):
    def test_control_uygun_symbols_remain_uygun_completed(self) -> None:
        for symbol in CONTROL_UYGUN_SYMBOLS:
            onboarding = OnboardingResult(
                symbol=symbol,
                success=True,
                participation_status=PARTICIPATION_STATUS_UYGUN,
                research_allowed=True,
            )
            self.assertEqual(onboarding.participation_status, PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(onboarding.research_allowed)
            self.assertEqual(
                onboarding_final_status(onboarding, budget_rate_limited=False),
                EXPANSION_STATUS_COMPLETED,
            )


class FakeSnapshotRepo:
    def __init__(self, latest_by_symbol):
        self.latest_by_symbol = latest_by_symbol
        self.appended = []

    def get_latest(self, symbol: str):
        return self.latest_by_symbol.get(str(symbol or "").strip().upper())

    def append_snapshot(self, payload):
        self.appended.append(payload)
        return payload


class QueueCompletedAssessmentReconcileTests(unittest.TestCase):
    def test_reconciles_matching_retryable_kontrol_et_without_provider_or_candidate_writes(self) -> None:
        queue_repo = UniverseExpansionRepository()
        row = queue_repo.upsert_pending("ABT", source_universe="sp500", priority=20)
        queue_repo.finalize(
            row["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
                "research_allowed": False,
                "last_error_category": "DATA_INSUFFICIENT",
                "next_retry_at": _now().isoformat(),
            },
        )
        snapshots = FakeSnapshotRepo(
            {"ABT": {"symbol": "ABT", "status": PARTICIPATION_STATUS_KONTROL_ET}}
        )
        first = reconcile_retryable_completed_assessments(
            queue_repo=queue_repo,
            participation_repo=snapshots,
            now=_now(),
        )
        updated = queue_repo.get_by_symbol("ABT")
        self.assertEqual(first.reconciled_symbols, ("ABT",))
        self.assertEqual(first.queue_writes, 1)
        self.assertEqual(first.provider_calls, 0)
        self.assertEqual(first.candidate_writes, 0)
        self.assertEqual(first.snapshot_writes, 0)
        self.assertEqual(snapshots.appended, [])
        self.assertEqual(updated["status"], EXPANSION_STATUS_COMPLETED)
        self.assertEqual(updated["participation_status"], PARTICIPATION_STATUS_KONTROL_ET)
        self.assertFalse(updated["research_allowed"])
        self.assertIsNone(updated["last_error_category"])
        self.assertIsNone(updated["next_retry_at"])
        self.assertEqual(updated["completed_at"], _now().isoformat())

        second = reconcile_retryable_completed_assessments(
            queue_repo=queue_repo,
            participation_repo=snapshots,
            now=_now(),
        )
        self.assertEqual(second.reconciled_symbols, ())
        self.assertEqual(second.queue_writes, 0)
        self.assertEqual(queue_repo.get_by_symbol("ABT")["status"], EXPANSION_STATUS_COMPLETED)

    def test_skips_status_mismatch_and_pending(self) -> None:
        queue_repo = UniverseExpansionRepository()
        retry = queue_repo.upsert_pending("AMD", source_universe="sp500", priority=20)
        queue_repo.finalize(
            retry["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
            },
        )
        queue_repo.upsert_pending("NEW", source_universe="fresh", priority=50)
        snapshots = FakeSnapshotRepo(
            {
                "AMD": {"symbol": "AMD", "status": PARTICIPATION_STATUS_UYGUN},
                "NEW": {"symbol": "NEW", "status": PARTICIPATION_STATUS_KONTROL_ET},
            }
        )
        result = reconcile_retryable_completed_assessments(
            queue_repo=queue_repo,
            participation_repo=snapshots,
            now=_now(),
        )
        self.assertEqual(result.reconciled_symbols, ())
        self.assertEqual(queue_repo.get_by_symbol("AMD")["status"], EXPANSION_STATUS_RETRYABLE)
        self.assertEqual(queue_repo.get_by_symbol("NEW")["status"], EXPANSION_STATUS_PENDING)

    def test_does_not_promote_uygun(self) -> None:
        queue_repo = UniverseExpansionRepository()
        row = queue_repo.upsert_pending("ABT", source_universe="sp500", priority=20)
        queue_repo.finalize(
            row["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
                "research_allowed": False,
            },
        )
        snapshots = FakeSnapshotRepo(
            {"ABT": {"symbol": "ABT", "status": PARTICIPATION_STATUS_KONTROL_ET}}
        )
        reconcile_retryable_completed_assessments(
            queue_repo=queue_repo,
            participation_repo=snapshots,
            now=_now(),
        )
        updated = queue_repo.get_by_symbol("ABT")
        self.assertEqual(updated["participation_status"], PARTICIPATION_STATUS_KONTROL_ET)
        self.assertNotEqual(updated["participation_status"], PARTICIPATION_STATUS_UYGUN)


if __name__ == "__main__":
    unittest.main()
