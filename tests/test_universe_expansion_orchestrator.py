from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.universe_expansion_run_repository import (
    RUN_STATUS_COMPLETED,
    TRIGGER_SCHEDULED,
    UniverseExpansionRunRepository,
)
from services.daily_universe_expansion_service import DailyUniverseExpansionService
from services.free_universe_client import UniverseSourceError
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.universe_discovery_service import ingest_merged_exchange_listings
from services.universe_expansion_contract import (
    ERROR_CATEGORY_NETWORK,
    ERROR_CATEGORY_PLAN_RESTRICTED,
    ERROR_CATEGORY_RATE_LIMIT,
    EXPANSION_STATUS_BLOCKED,
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_IN_PROGRESS,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
    ORCHESTRATION_ALREADY_RAN_TODAY,
    ORCHESTRATION_BACKPRESSURE_WAIT,
    ORCHESTRATION_DISCOVERY_AND_PARTICIPATION,
    ORCHESTRATION_IN_PROGRESS_EXIT,
    ORCHESTRATION_NO_NEW_DISCOVERY,
    ORCHESTRATION_PARTICIPATION_ONLY,
    STOP_REASON_ALREADY_RAN_TODAY,
    STOP_REASON_BACKPRESSURE_RETRY_WAIT,
    STOP_REASON_DISCOVERY_SOURCE_ERROR,
    STOP_REASON_IN_PROGRESS_EXIT,
    STOP_REASON_RATE_LIMIT,
)
from services.universe_expansion_onboarding_service import OnboardingResult
from services.universe_expansion_orchestrator import UniverseExpansionOrchestrator


NOW = datetime(2026, 8, 27, 3, 0, tzinfo=timezone.utc)
RUN_DATE = date(2026, 8, 27)


def _completed_result(
    symbol: str,
    *,
    status: str = PARTICIPATION_STATUS_UYGUN_DEGIL,
    candidate_upserted: bool = False,
) -> OnboardingResult:
    return OnboardingResult(
        symbol=symbol,
        success=True,
        participation_status=status,
        research_allowed=False,
        snapshot_saved=True,
        candidate_upserted=candidate_upserted,
    )


def _failing_result(symbol: str, *, error_category: str) -> OnboardingResult:
    return OnboardingResult(
        symbol=symbol,
        success=False,
        error_category=error_category,
        error_message=error_category,
    )


def _complete_row(
    repo: UniverseExpansionRepository,
    symbol: str,
    *,
    status: str = EXPANSION_STATUS_COMPLETED,
    participation: str = PARTICIPATION_STATUS_UYGUN_DEGIL,
    **extra,
) -> dict:
    row = repo.upsert_pending(symbol, source_universe="static_seed", priority=1)
    payload = {"status": status, "participation_status": participation, **extra}
    repo.finalize(row["id"], payload)
    updated = repo.get_by_symbol(symbol)
    assert updated is not None
    return updated


def _seed_completed(repo: UniverseExpansionRepository, count: int = 176) -> None:
    for index in range(count):
        _complete_row(repo, f"SEED{index:03d}")


def _listing_feeds(symbols: list[str]):
    nasdaq = []
    sec = []
    for index, symbol in enumerate(symbols):
        nasdaq.append(
            {
                "symbol": symbol,
                "company_name": f"{symbol} Corporation",
                "exchange_security_name": f"{symbol} Common Stock",
                "exchange": "NYSE",
                "cik": str(2_000_000 + index),
                "is_etf": False,
            }
        )
        sec.append(
            {
                "symbol": symbol,
                "company_name": f"{symbol} Corporation",
                "cik": str(2_000_000 + index),
                "exchange": "NYSE",
            }
        )
    return nasdaq, [], sec


class FeedFetcher:
    def __init__(self, feeds, error: Exception | None = None) -> None:
        self.feeds = feeds
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.feeds


class IngestCounter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return ingest_merged_exchange_listings(*args, **kwargs)


class ParticipationCounter:
    def __init__(self, inner: DailyUniverseExpansionService) -> None:
        self.inner = inner
        self.calls = 0

    def run_once(self, **kwargs):
        self.calls += 1
        return self.inner.run_once(**kwargs)


def _orchestrator(
    repo: UniverseExpansionRepository,
    *,
    runner,
    fetcher=None,
    run_repo: UniverseExpansionRunRepository | None = None,
    ingest=None,
):
    config = UniverseExpansionBudgetConfig()
    inner = DailyUniverseExpansionService(
        queue_repo=repo,
        budget_config=config,
        onboarding_runner=runner,
    )
    participation = ParticipationCounter(inner)
    ingest_counter = ingest or IngestCounter()
    orch = UniverseExpansionOrchestrator(
        queue_repo=repo,
        budget_config=config,
        participation_service=participation,
        listing_fetcher=fetcher,
        run_repo=run_repo,
        discovery_ingest=ingest_counter,
    )
    return orch, participation, ingest_counter


def _record_paid_run(
    run_repo: UniverseExpansionRunRepository,
    *,
    run_id: str,
    report: dict,
    run_date: date = RUN_DATE,
) -> None:
    run_repo.start_run(
        run_id=run_id,
        run_date=run_date,
        trigger_type=TRIGGER_SCHEDULED,
        dry_run=False,
        allow_second_run_today=False,
        started_at=NOW,
    )
    run_repo.finalize_run(
        run_id,
        status=RUN_STATUS_COMPLETED,
        stop_reason=report.get("stop_reason") or "",
        report=report,
        finished_at=NOW + timedelta(minutes=10),
    )


class OrchestratorStateMachineTests(unittest.TestCase):
    def test_a_clean_queue_discovers_and_participates_once(self) -> None:
        repo = UniverseExpansionRepository()
        symbols = [f"NXT{index:03d}" for index in range(30)]
        fetcher = FeedFetcher(_listing_feeds(symbols))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled", max_symbols=30)
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_DISCOVERY_AND_PARTICIPATION)
        self.assertEqual(report.discovery["inserted"], 30)
        self.assertEqual(report.symbols_started, 30)
        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(ingest.calls, 1)
        self.assertEqual(participation.calls, 1)
        self.assertEqual(report.queue_after["pending"], 0)
        self.assertEqual(report.queue_after["completed"], 30)

    def test_b_discovery_zero_skips_participation(self) -> None:
        repo = UniverseExpansionRepository()
        _complete_row(repo, "KEEP")
        fetcher = FeedFetcher(_listing_feeds(["KEEP"]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_NO_NEW_DISCOVERY)
        self.assertEqual(report.discovery["inserted"], 0)
        self.assertEqual(participation.calls, 0)
        self.assertEqual(ingest.calls, 1)
        self.assertEqual(fetcher.calls, 1)

    def test_c_pending_blocks_discovery(self) -> None:
        repo = UniverseExpansionRepository()
        for index in range(10):
            repo.upsert_pending(f"PEN{index:02d}", source_universe="us_exchange_listed", priority=80)
        fetcher = FeedFetcher(_listing_feeds([f"ZZZ{index:03d}" for index in range(30)]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(participation.calls, 1)
        self.assertEqual(report.symbols_started, 10)
        self.assertFalse(report.discovery.get("attempted"))

    def test_d_pending_fifty_starts_max_thirty(self) -> None:
        repo = UniverseExpansionRepository()
        for index in range(50):
            repo.upsert_pending(f"PEN{index:02d}", source_universe="us_exchange_listed", priority=80)
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=FeedFetcher(_listing_feeds(["ZZZZ"])),
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertLessEqual(report.symbols_started, 30)
        self.assertEqual(report.symbols_started, 30)
        self.assertEqual(report.queue_after["pending"], 20)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(participation.calls, 1)

    def test_e_due_retryable_retries_without_discovery(self) -> None:
        repo = UniverseExpansionRepository()
        row = repo.upsert_pending("RTRY", source_universe="us_exchange_listed", priority=80)
        repo.finalize(
            row["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "next_retry_at": NOW.isoformat(),
            },
        )
        fetcher = FeedFetcher(_listing_feeds(["ZZZZ"]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(participation.calls, 1)
        self.assertEqual(report.symbols_started, 1)

    def test_f_not_due_retryable_waits(self) -> None:
        repo = UniverseExpansionRepository()
        row = repo.upsert_pending("WAIT", source_universe="us_exchange_listed", priority=80)
        future = (NOW + timedelta(hours=6)).isoformat()
        repo.finalize(
            row["id"],
            {"status": EXPANSION_STATUS_RETRYABLE, "next_retry_at": future},
        )
        fetcher = FeedFetcher(_listing_feeds(["ZZZZ"]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_BACKPRESSURE_WAIT)
        self.assertEqual(report.stop_reason, STOP_REASON_BACKPRESSURE_RETRY_WAIT)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(participation.calls, 0)
        self.assertEqual(repo.get_by_symbol("WAIT")["next_retry_at"], future)

    def test_g_blocked_only_allows_discovery(self) -> None:
        repo = UniverseExpansionRepository()
        _complete_row(
            repo,
            "BLCK",
            status=EXPANSION_STATUS_BLOCKED,
            participation="",
        )
        symbols = [f"NXT{index:03d}" for index in range(30)]
        fetcher = FeedFetcher(_listing_feeds(symbols))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_DISCOVERY_AND_PARTICIPATION)
        self.assertEqual(report.discovery["inserted"], 30)
        self.assertEqual(repo.get_by_symbol("BLCK")["status"], EXPANSION_STATUS_BLOCKED)
        self.assertEqual(ingest.calls, 1)
        self.assertEqual(participation.calls, 1)

    def test_h_fresh_in_progress_exits(self) -> None:
        repo = UniverseExpansionRepository()
        row = repo.upsert_pending("LIVE", source_universe="us_exchange_listed", priority=80)
        repo.finalize(
            row["id"],
            {
                "status": EXPANSION_STATUS_IN_PROGRESS,
                "claimed_at": NOW.isoformat(),
            },
        )
        fetcher = FeedFetcher(_listing_feeds(["ZZZZ"]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_IN_PROGRESS_EXIT)
        self.assertEqual(report.stop_reason, STOP_REASON_IN_PROGRESS_EXIT)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(participation.calls, 0)
        self.assertEqual(repo.get_by_symbol("LIVE")["status"], EXPANSION_STATUS_IN_PROGRESS)

    def test_i_stale_in_progress_recovers_and_blocks_discovery(self) -> None:
        repo = UniverseExpansionRepository()
        row = repo.upsert_pending("STALE", source_universe="us_exchange_listed", priority=80)
        repo.finalize(
            row["id"],
            {
                "status": EXPANSION_STATUS_IN_PROGRESS,
                "claimed_at": (NOW - timedelta(hours=3)).isoformat(),
            },
        )
        fetcher = FeedFetcher(_listing_feeds(["ZZZZ"]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.recovered_stale, 1)
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(participation.calls, 1)
        self.assertEqual(repo.get_by_symbol("STALE")["status"], EXPANSION_STATUS_COMPLETED)

    def test_j_same_day_completed_run_does_not_skip_pending(self) -> None:
        repo = UniverseExpansionRepository()
        run_repo = UniverseExpansionRunRepository()
        _record_paid_run(
            run_repo,
            run_id="run-1",
            report={
                "symbols_started": 30,
                "symbols_completed": 30,
                "orchestration_decision": ORCHESTRATION_DISCOVERY_AND_PARTICIPATION,
            },
        )
        repo.upsert_pending("LEFT", source_universe="us_exchange_listed", priority=80)
        fetcher = FeedFetcher(_listing_feeds(["ZZZZ"]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
            run_repo=run_repo,
        )
        report = orch.run(
            now=NOW,
            trigger_type="scheduled",
            run_date=RUN_DATE,
        )
        self.assertNotEqual(report.orchestration_decision, ORCHESTRATION_ALREADY_RAN_TODAY)
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertEqual(participation.calls, 1)
        self.assertEqual(ingest.calls, 0)

    def test_k_same_day_clean_discovery_cycle_skips(self) -> None:
        repo = UniverseExpansionRepository()
        _complete_row(repo, "DONE")
        run_repo = UniverseExpansionRunRepository()
        _record_paid_run(
            run_repo,
            run_id="run-1",
            report={
                "symbols_started": 30,
                "symbols_completed": 30,
                "orchestration_decision": ORCHESTRATION_DISCOVERY_AND_PARTICIPATION,
            },
        )
        fetcher = FeedFetcher(_listing_feeds([f"NXT{index:03d}" for index in range(30)]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
            run_repo=run_repo,
        )
        report = orch.run(
            now=NOW,
            trigger_type="scheduled",
            run_date=RUN_DATE,
        )
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_ALREADY_RAN_TODAY)
        self.assertEqual(report.stop_reason, STOP_REASON_ALREADY_RAN_TODAY)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(participation.calls, 0)

    def test_l_kontrol_et_candidate_failure_still_completed_then_discover(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("CTRL", source_universe="us_exchange_listed", priority=80)

        def runner(symbol, **kwargs):
            return _completed_result(
                symbol,
                status=PARTICIPATION_STATUS_KONTROL_ET,
                candidate_upserted=False,
            )

        orch, participation, ingest = _orchestrator(
            repo,
            runner=runner,
            fetcher=FeedFetcher(_listing_feeds(["ZZZZ"])),
        )
        first = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(first.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertEqual(repo.get_by_symbol("CTRL")["status"], EXPANSION_STATUS_COMPLETED)
        self.assertFalse(first.symbol_details[0].result.candidate_upserted)

        next_symbols = [f"NXT{index:03d}" for index in range(30)]
        fetcher = FeedFetcher(_listing_feeds(next_symbols))
        orch2, participation2, ingest2 = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        second = orch2.run(now=NOW + timedelta(days=1), trigger_type="scheduled")
        self.assertEqual(second.orchestration_decision, ORCHESTRATION_DISCOVERY_AND_PARTICIPATION)
        self.assertEqual(second.discovery["inserted"], 30)
        self.assertEqual(ingest2.calls, 1)
        self.assertEqual(participation2.calls, 1)

    def test_m_transient_failure_blocks_next_discovery(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("FAIL", source_universe="us_exchange_listed", priority=80)
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _failing_result(
                symbol,
                error_category=ERROR_CATEGORY_NETWORK,
            ),
            fetcher=FeedFetcher(_listing_feeds(["ZZZZ"])),
        )
        first = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(first.symbols_retryable, 1)
        self.assertEqual(repo.get_by_symbol("FAIL")["status"], EXPANSION_STATUS_RETRYABLE)

        later = NOW + timedelta(days=1)
        fetcher = FeedFetcher(_listing_feeds([f"NXT{index:03d}" for index in range(30)]))
        orch2, participation2, ingest2 = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        second = orch2.run(now=later, trigger_type="scheduled")
        self.assertEqual(second.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertEqual(ingest2.calls, 0)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(participation2.calls, 1)

    def test_n_discovery_inserts_at_most_thirty(self) -> None:
        repo = UniverseExpansionRepository()
        symbols = [f"NXT{index:03d}" for index in range(80)]
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=FeedFetcher(_listing_feeds(symbols)),
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertLessEqual(report.discovery["inserted"], 30)
        self.assertEqual(report.discovery["inserted"], 30)
        self.assertGreater(report.discovery["skipped_ingest_limit"], 0)
        self.assertEqual(ingest.calls, 1)

    def test_o_participation_starts_at_most_thirty(self) -> None:
        repo = UniverseExpansionRepository()
        for index in range(40):
            repo.upsert_pending(f"PEN{index:02d}", source_universe="us_exchange_listed", priority=80)
        orch, participation, _ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=FeedFetcher(_listing_feeds(["ZZZZ"])),
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertLessEqual(report.symbols_started, 30)
        self.assertEqual(report.symbols_started, 30)
        self.assertEqual(participation.calls, 1)

    def test_p_discovery_never_runs_twice_in_one_cycle(self) -> None:
        repo = UniverseExpansionRepository()
        fetcher = FeedFetcher(_listing_feeds([f"NXT{index:03d}" for index in range(30)]))
        orch, _participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(ingest.calls, 1)
        with self.assertRaisesRegex(RuntimeError, "discovery already executed"):
            orch._run_discovery(
                orch.idle_report(
                    orch.plan(now=NOW, trigger_type="scheduled"),
                    run_id="x",
                    dry_run=False,
                    trigger_type="scheduled",
                ),
                dry_run=False,
                listing_fetcher=fetcher,
            )

    def test_q_participation_never_runs_twice_in_one_cycle(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("ONCE", source_universe="us_exchange_listed", priority=80)
        orch, participation, _ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=FeedFetcher(_listing_feeds(["ZZZZ"])),
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(participation.calls, 1)
        with self.assertRaisesRegex(RuntimeError, "participation already executed"):
            orch._run_participation(
                report,
                max_symbols=30,
                dry_run=False,
                now=NOW,
                trigger_type="scheduled",
                fmp_client=None,
                sec_client=None,
                participation_repo=None,
                candidate_repo=None,
                sec_ticker_lookup=None,
            )


class OrchestratorDaySimulationTests(unittest.TestCase):
    def test_day1_day2_deterministic_progression(self) -> None:
        repo = UniverseExpansionRepository()
        _seed_completed(repo, 176)
        candidates = [f"NXT{index:03d}" for index in range(60)]
        fetcher = FeedFetcher(_listing_feeds(candidates))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        day1 = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(day1.orchestration_decision, ORCHESTRATION_DISCOVERY_AND_PARTICIPATION)
        self.assertEqual(day1.discovery["inserted"], 30)
        self.assertEqual(day1.symbols_started, 30)
        self.assertEqual(day1.symbols_completed, 30)
        day1_symbols = {
            row["symbol"]
            for row in repo.list_all()
            if row["source_universe"] == "us_exchange_listed"
        }
        self.assertEqual(len(day1_symbols), 30)
        self.assertEqual(ingest.calls, 1)
        self.assertEqual(participation.calls, 1)

        day2_now = NOW + timedelta(days=1)
        orch2, participation2, ingest2 = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=FeedFetcher(_listing_feeds(candidates)),
        )
        day2 = orch2.run(now=day2_now, trigger_type="scheduled")
        self.assertEqual(day2.orchestration_decision, ORCHESTRATION_DISCOVERY_AND_PARTICIPATION)
        self.assertEqual(day2.discovery["inserted"], 30)
        self.assertEqual(day2.symbols_started, 30)
        day2_symbols = {
            row["symbol"]
            for row in repo.list_all()
            if row["source_universe"] == "us_exchange_listed"
        } - day1_symbols
        self.assertEqual(len(day2_symbols), 30)
        self.assertEqual(day1_symbols & day2_symbols, set())
        self.assertEqual(ingest2.calls, 1)
        self.assertEqual(participation2.calls, 1)
        self.assertEqual(repo.count_by_status().get(EXPANSION_STATUS_COMPLETED), 236)


class OrchestratorFailureTests(unittest.TestCase):
    def test_nasdaq_discovery_failure_is_safe(self) -> None:
        repo = UniverseExpansionRepository()
        _complete_row(repo, "KEEP")
        fetcher = FeedFetcher(None, error=UniverseSourceError("Nasdaq listed: HTTP 500"))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.stop_reason, STOP_REASON_DISCOVERY_SOURCE_ERROR)
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_NO_NEW_DISCOVERY)
        self.assertEqual(report.discovery["inserted"], 0)
        self.assertEqual(participation.calls, 0)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(len(repo.list_all()), 1)

    def test_sec_listing_failure_is_safe(self) -> None:
        repo = UniverseExpansionRepository()
        _complete_row(repo, "KEEP")
        fetcher = FeedFetcher(None, error=UniverseSourceError("SEC: HTTP 500"))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.stop_reason, STOP_REASON_DISCOVERY_SOURCE_ERROR)
        self.assertEqual(participation.calls, 0)
        self.assertEqual(ingest.calls, 0)

    def test_participation_rate_limit_blocks_future_discovery(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("RLIM", source_universe="us_exchange_listed", priority=80)
        orch, _participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _failing_result(
                symbol,
                error_category=ERROR_CATEGORY_RATE_LIMIT,
            ),
            fetcher=FeedFetcher(_listing_feeds(["ZZZZ"])),
        )
        first = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(first.stop_reason, STOP_REASON_RATE_LIMIT)
        self.assertEqual(repo.get_by_symbol("RLIM")["status"], EXPANSION_STATUS_RETRYABLE)

        later = NOW + timedelta(days=1)
        fetcher = FeedFetcher(_listing_feeds([f"NXT{index:03d}" for index in range(30)]))
        orch2, participation2, ingest2 = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        second = orch2.run(now=later, trigger_type="scheduled")
        self.assertEqual(second.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertEqual(ingest2.calls, 0)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(participation2.calls, 1)

    def test_participation_timeout_preserves_retry(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("SLOW", source_universe="us_exchange_listed", priority=80)

        def runner(symbol, **kwargs):
            raise TimeoutError("timed out")

        orch, _participation, ingest = _orchestrator(
            repo,
            runner=runner,
            fetcher=FeedFetcher(_listing_feeds(["ZZZZ"])),
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.symbols_retryable, 1)
        self.assertEqual(repo.get_by_symbol("SLOW")["status"], EXPANSION_STATUS_RETRYABLE)
        self.assertEqual(ingest.calls, 0)

    def test_crash_leftover_pending_is_participation_only(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("LEFT", source_universe="us_exchange_listed", priority=80)
        fetcher = FeedFetcher(_listing_feeds([f"NXT{index:03d}" for index in range(30)]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(participation.calls, 1)

    def test_blocked_symbol_does_not_prevent_later_discovery(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("PLAN", source_universe="us_exchange_listed", priority=80)
        orch, _participation, _ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _failing_result(
                symbol,
                error_category=ERROR_CATEGORY_PLAN_RESTRICTED,
            ),
            fetcher=FeedFetcher(_listing_feeds(["ZZZZ"])),
        )
        first = orch.run(now=NOW, trigger_type="scheduled")
        self.assertEqual(first.symbols_blocked, 1)
        self.assertEqual(repo.get_by_symbol("PLAN")["status"], EXPANSION_STATUS_BLOCKED)

        later = NOW + timedelta(days=1)
        symbols = [f"NXT{index:03d}" for index in range(30)]
        orch2, participation2, ingest2 = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=FeedFetcher(_listing_feeds(symbols)),
        )
        second = orch2.run(now=later, trigger_type="scheduled")
        self.assertEqual(second.orchestration_decision, ORCHESTRATION_DISCOVERY_AND_PARTICIPATION)
        self.assertEqual(second.discovery["inserted"], 30)
        self.assertEqual(repo.get_by_symbol("PLAN")["status"], EXPANSION_STATUS_BLOCKED)
        self.assertEqual(ingest2.calls, 1)
        self.assertEqual(participation2.calls, 1)

    def test_workflow_dispatch_uses_same_backpressure(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("MANUAL", source_universe="us_exchange_listed", priority=80)
        fetcher = FeedFetcher(_listing_feeds([f"NXT{index:03d}" for index in range(30)]))
        orch, participation, ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=fetcher,
        )
        report = orch.run(now=NOW, trigger_type="workflow_dispatch")
        self.assertEqual(report.orchestration_decision, ORCHESTRATION_PARTICIPATION_ONLY)
        self.assertEqual(ingest.calls, 0)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(participation.calls, 1)

    def test_observability_payload_has_required_fields(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("OBS", source_universe="us_exchange_listed", priority=80)
        orch, _participation, _ingest = _orchestrator(
            repo,
            runner=lambda symbol, **kwargs: _completed_result(symbol),
            fetcher=FeedFetcher(_listing_feeds(["ZZZZ"])),
        )
        payload = orch.run(now=NOW, trigger_type="scheduled").to_dict()
        for key in ("total", "pending", "retryable", "due_retryable", "blocked", "in_progress", "completed"):
            self.assertIn(key, payload["queue_before"])
            self.assertIn(key, payload["queue_after"])
        self.assertEqual(payload["orchestration_decision"], ORCHESTRATION_PARTICIPATION_ONLY)
        for key in (
            "attempted",
            "inserted",
            "skipped_existing",
            "skipped_filter",
            "skipped_capacity",
            "skipped_ingest_limit",
        ):
            self.assertIn(key, payload["discovery"])


if __name__ == "__main__":
    unittest.main()
