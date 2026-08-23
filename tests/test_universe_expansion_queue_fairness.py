from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.daily_universe_expansion_service import DailyUniverseExpansionService
from services.universe_expansion_contract import (
    ERROR_CATEGORY_DATA_INSUFFICIENT,
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
    STOP_REASON_SAFETY_CAP,
)
from services.universe_expansion_onboarding_service import OnboardingResult


def _now() -> datetime:
    return datetime(2026, 8, 22, 5, 0, tzinfo=timezone.utc)


def _ok(symbol: str) -> OnboardingResult:
    return OnboardingResult(
        symbol=symbol,
        success=True,
        participation_status="Uygun",
        research_allowed=True,
        snapshot_saved=True,
        candidate_upserted=True,
    )


def _fail(symbol: str) -> OnboardingResult:
    return OnboardingResult(
        symbol=symbol,
        success=False,
        error_category=ERROR_CATEGORY_DATA_INSUFFICIENT,
        error_message="incomplete",
    )


class UniverseExpansionQueueFairnessTests(unittest.TestCase):
    def test_retryable_failures_cannot_monopolize_daily_batch(self) -> None:
        repo = UniverseExpansionRepository()
        for symbol in ("FAILA", "FAILB", "FAILC"):
            row = repo.upsert_pending(symbol, source_universe="retry", priority=1)
            repo.finalize(
                row["id"],
                {
                    "status": EXPANSION_STATUS_RETRYABLE,
                    "next_retry_at": _now().isoformat(),
                    "priority": 1,
                },
            )
        for symbol in ("PENDX", "PENDY"):
            repo.upsert_pending(symbol, source_universe="fresh", priority=50)

        processed: list[str] = []

        def runner(symbol, **kwargs):
            processed.append(symbol)
            return _ok(symbol)

        service = DailyUniverseExpansionService(queue_repo=repo, onboarding_runner=runner)
        report = service.run_once(max_symbols=3, now=_now(), seed_if_empty=False)
        self.assertEqual(processed[:2], ["PENDX", "PENDY"])
        self.assertEqual(report.symbols_started, 3)
        self.assertEqual(repo.get_by_symbol("PENDX")["status"], EXPANSION_STATUS_COMPLETED)
        self.assertEqual(repo.get_by_symbol("PENDY")["status"], EXPANSION_STATUS_COMPLETED)

    def test_pending_symbols_progress_while_retryable_exist(self) -> None:
        repo = UniverseExpansionRepository()
        retry = repo.upsert_pending("RETRY1", source_universe="retry", priority=1)
        repo.finalize(
            retry["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "next_retry_at": _now().isoformat(),
            },
        )
        repo.upsert_pending("FRESH1", source_universe="fresh", priority=90)
        eligible = repo.list_eligible(_now(), limit=10)
        self.assertEqual([row["symbol"] for row in eligible], ["FRESH1", "RETRY1"])

    def test_next_retry_at_respected(self) -> None:
        repo = UniverseExpansionRepository()
        row = repo.upsert_pending("WAIT", source_universe="retry", priority=1)
        future = (_now() + timedelta(hours=6)).isoformat()
        repo.finalize(
            row["id"],
            {"status": EXPANSION_STATUS_RETRYABLE, "next_retry_at": future},
        )
        repo.upsert_pending("NOW", source_universe="fresh", priority=50)
        eligible = repo.list_eligible(_now(), limit=10)
        self.assertEqual([row["symbol"] for row in eligible], ["NOW"])

        later = _now() + timedelta(hours=6)
        eligible_later = repo.list_eligible(later, limit=10)
        self.assertEqual([row["symbol"] for row in eligible_later], ["NOW", "WAIT"])

    def test_completed_symbols_are_skipped(self) -> None:
        repo = UniverseExpansionRepository()
        done = repo.upsert_pending("DONE", source_universe="pilot", priority=1)
        repo.finalize(done["id"], {"status": EXPANSION_STATUS_COMPLETED})
        repo.upsert_pending("NEXT", source_universe="pilot", priority=2)
        eligible = repo.list_eligible(_now())
        self.assertEqual([row["symbol"] for row in eligible], ["NEXT"])

        processed: list[str] = []

        def runner(symbol, **kwargs):
            processed.append(symbol)
            return _ok(symbol)

        service = DailyUniverseExpansionService(queue_repo=repo, onboarding_runner=runner)
        service.run_once(max_symbols=5, now=_now(), seed_if_empty=False)
        self.assertEqual(processed, ["NEXT"])
        self.assertEqual(repo.get_by_symbol("DONE")["status"], EXPANSION_STATUS_COMPLETED)

    def test_safety_cap_remains_enforced(self) -> None:
        repo = UniverseExpansionRepository()
        for index, symbol in enumerate(("AAA", "BBB", "CCC", "DDD"), start=1):
            repo.upsert_pending(symbol, source_universe="pilot", priority=index)
        service = DailyUniverseExpansionService(
            queue_repo=repo,
            onboarding_runner=lambda symbol, **kwargs: _ok(symbol),
        )
        report = service.run_once(max_symbols=2, now=_now(), seed_if_empty=False)
        self.assertEqual(report.stop_reason, STOP_REASON_SAFETY_CAP)
        self.assertEqual(report.symbols_started, 2)
        self.assertEqual(repo.get_by_symbol("CCC")["status"], EXPANSION_STATUS_PENDING)
        self.assertEqual(repo.get_by_symbol("DDD")["status"], EXPANSION_STATUS_PENDING)

    def test_due_retryable_still_run_when_no_pending(self) -> None:
        repo = UniverseExpansionRepository()
        row = repo.upsert_pending("ONLY", source_universe="retry", priority=1)
        repo.finalize(
            row["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "next_retry_at": _now().isoformat(),
            },
        )
        service = DailyUniverseExpansionService(
            queue_repo=repo,
            onboarding_runner=lambda symbol, **kwargs: _fail(symbol),
        )
        report = service.run_once(max_symbols=1, now=_now(), seed_if_empty=False)
        self.assertEqual(report.symbols_started, 1)
        self.assertEqual(report.symbols_retryable, 1)


if __name__ == "__main__":
    unittest.main()
