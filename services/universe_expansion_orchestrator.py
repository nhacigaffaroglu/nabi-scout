"""Backpressured daily Universe Expansion orchestrator.

Recover stale work, process unresolved Participation first, and discover a
new batch only when the queue is clean. Discovery and Participation each run
at most once per orchestration cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional
from uuid import uuid4

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.universe_expansion_run_repository import UniverseExpansionRunRepository
from services.daily_universe_expansion_service import (
    DailyExpansionRunReport,
    DailyUniverseExpansionService,
)
from services.free_universe_client import UniverseSourceError
from services.scheduled_universe_expansion_service import (
    discovery_cycle_already_ran_today,
    expansion_run_date,
)
from services.universe_discovery_service import (
    DiscoveryIngestReport,
    fetch_us_equity_listing_feeds,
    ingest_merged_exchange_listings,
)
from services.universe_expansion_contract import (
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
    STOP_REASON_QUEUE_EMPTY,
)
from services.universe_expansion_onboarding_service import run_participation_onboarding

ListingFeeds = tuple[
    list[Mapping[str, Any]],
    list[Mapping[str, Any]],
    list[Mapping[str, Any]],
]
ListingFetcher = Callable[[], ListingFeeds]

IDLE_DECISIONS = frozenset(
    {
        ORCHESTRATION_ALREADY_RAN_TODAY,
        ORCHESTRATION_BACKPRESSURE_WAIT,
        ORCHESTRATION_IN_PROGRESS_EXIT,
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def snapshot_queue_status(
    repo: UniverseExpansionRepository,
    now: datetime,
) -> Dict[str, int]:
    counts = repo.count_by_status()
    pending = int(counts.get(EXPANSION_STATUS_PENDING) or 0)
    retryable = int(counts.get(EXPANSION_STATUS_RETRYABLE) or 0)
    blocked = int(counts.get(EXPANSION_STATUS_BLOCKED) or 0)
    in_progress = int(counts.get(EXPANSION_STATUS_IN_PROGRESS) or 0)
    completed = int(counts.get(EXPANSION_STATUS_COMPLETED) or 0)
    return {
        "total": len(repo.list_all()),
        "pending": pending,
        "retryable": retryable,
        "due_retryable": repo.count_due_retryable(now),
        "blocked": blocked,
        "in_progress": in_progress,
        "completed": completed,
    }


def empty_discovery_payload(*, attempted: bool = False, error: str = "") -> Dict[str, object]:
    payload: Dict[str, object] = {
        "attempted": attempted,
        "inserted": 0,
        "skipped_existing": 0,
        "skipped_filter": 0,
        "skipped_capacity": 0,
        "skipped_ingest_limit": 0,
    }
    if error:
        payload["error"] = error
    return payload


def discovery_payload_from_ingest(
    ingest: DiscoveryIngestReport,
    *,
    attempted: bool = True,
    error: str = "",
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "attempted": attempted,
        "inserted": ingest.inserted,
        "skipped_existing": ingest.skipped_existing,
        "skipped_filter": ingest.skipped_excluded,
        "skipped_capacity": ingest.skipped_capacity,
        "skipped_ingest_limit": ingest.skipped_ingest_limit,
    }
    if error:
        payload["error"] = error
    return payload


@dataclass
class OrchestrationPlan:
    decision: str
    queue_before: Dict[str, int]
    recovered_stale: int
    now: datetime
    run_discovery: bool
    run_participation: bool
    idle: bool


class UniverseExpansionOrchestrator:
    def __init__(
        self,
        *,
        queue_repo: UniverseExpansionRepository,
        budget_config: Optional[UniverseExpansionBudgetConfig] = None,
        participation_service: Optional[DailyUniverseExpansionService] = None,
        onboarding_runner=run_participation_onboarding,
        listing_fetcher: Optional[ListingFetcher] = None,
        listing_client: Any = None,
        run_repo: Optional[UniverseExpansionRunRepository] = None,
        discovery_ingest=ingest_merged_exchange_listings,
    ) -> None:
        self.queue_repo = queue_repo
        self.budget_config = budget_config or UniverseExpansionBudgetConfig.from_env()
        self.participation_service = participation_service or DailyUniverseExpansionService(
            queue_repo=queue_repo,
            budget_config=self.budget_config,
            onboarding_runner=onboarding_runner,
        )
        self.listing_fetcher = listing_fetcher
        self.listing_client = listing_client
        self.run_repo = run_repo
        self.discovery_ingest = discovery_ingest
        self._discovery_executed = False
        self._participation_executed = False

    def plan(
        self,
        *,
        now: Optional[datetime] = None,
        dry_run: bool = False,
        trigger_type: str = "",
        allow_second_run_today: bool = False,
        run_date=None,
    ) -> OrchestrationPlan:
        timestamp = now or _utcnow()
        recovered = 0
        if not dry_run:
            recovered = self.queue_repo.recover_stale_in_progress(
                timestamp,
                stale_minutes=self.budget_config.stale_in_progress_minutes,
            )
        snapshot = snapshot_queue_status(self.queue_repo, timestamp)

        if snapshot["in_progress"] > 0:
            return OrchestrationPlan(
                decision=ORCHESTRATION_IN_PROGRESS_EXIT,
                queue_before=snapshot,
                recovered_stale=recovered,
                now=timestamp,
                run_discovery=False,
                run_participation=False,
                idle=True,
            )
        if snapshot["pending"] > 0:
            return OrchestrationPlan(
                decision=ORCHESTRATION_PARTICIPATION_ONLY,
                queue_before=snapshot,
                recovered_stale=recovered,
                now=timestamp,
                run_discovery=False,
                run_participation=True,
                idle=False,
            )
        if snapshot["retryable"] > 0:
            if snapshot["due_retryable"] > 0:
                return OrchestrationPlan(
                    decision=ORCHESTRATION_PARTICIPATION_ONLY,
                    queue_before=snapshot,
                    recovered_stale=recovered,
                    now=timestamp,
                    run_discovery=False,
                    run_participation=True,
                    idle=False,
                )
            return OrchestrationPlan(
                decision=ORCHESTRATION_BACKPRESSURE_WAIT,
                queue_before=snapshot,
                recovered_stale=recovered,
                now=timestamp,
                run_discovery=False,
                run_participation=False,
                idle=True,
            )

        target_date = run_date or expansion_run_date(timestamp)
        if (
            not dry_run
            and not allow_second_run_today
            and trigger_type in {"scheduled", "workflow_dispatch"}
            and self.run_repo is not None
        ):
            already_ran, _ = discovery_cycle_already_ran_today(self.run_repo, target_date)
            if already_ran:
                return OrchestrationPlan(
                    decision=ORCHESTRATION_ALREADY_RAN_TODAY,
                    queue_before=snapshot,
                    recovered_stale=recovered,
                    now=timestamp,
                    run_discovery=False,
                    run_participation=False,
                    idle=True,
                )

        return OrchestrationPlan(
            decision=ORCHESTRATION_DISCOVERY_AND_PARTICIPATION,
            queue_before=snapshot,
            recovered_stale=recovered,
            now=timestamp,
            run_discovery=True,
            run_participation=True,
            idle=False,
        )

    def idle_report(
        self,
        plan: OrchestrationPlan,
        *,
        run_id: str,
        dry_run: bool,
        trigger_type: str,
    ) -> DailyExpansionRunReport:
        stop_reason = {
            ORCHESTRATION_IN_PROGRESS_EXIT: STOP_REASON_IN_PROGRESS_EXIT,
            ORCHESTRATION_BACKPRESSURE_WAIT: STOP_REASON_BACKPRESSURE_RETRY_WAIT,
            ORCHESTRATION_ALREADY_RAN_TODAY: STOP_REASON_ALREADY_RAN_TODAY,
        }.get(plan.decision, "")
        queue_after = snapshot_queue_status(self.queue_repo, plan.now)
        now_iso = plan.now.isoformat()
        return DailyExpansionRunReport(
            run_id=run_id,
            started_at=now_iso,
            finished_at=_utcnow().isoformat(),
            dry_run=dry_run,
            trigger_type=trigger_type,
            stop_reason=stop_reason,
            queue_counts=queue_after,
            queue_before=plan.queue_before,
            queue_after=queue_after,
            orchestration_decision=plan.decision,
            discovery=empty_discovery_payload(attempted=False),
            recovered_stale=plan.recovered_stale,
        )

    def execute(
        self,
        plan: OrchestrationPlan,
        *,
        run_id: str,
        max_symbols: Optional[int] = None,
        dry_run: bool = False,
        trigger_type: str = "",
        fmp_client: Any = None,
        sec_client: Any = None,
        participation_repo: Any = None,
        candidate_repo: Any = None,
        sec_ticker_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
        listing_fetcher: Optional[ListingFetcher] = None,
    ) -> DailyExpansionRunReport:
        if plan.idle:
            return self.idle_report(
                plan,
                run_id=run_id,
                dry_run=dry_run,
                trigger_type=trigger_type,
            )

        report = DailyExpansionRunReport(
            run_id=run_id,
            started_at=plan.now.isoformat(),
            dry_run=dry_run,
            trigger_type=trigger_type,
            queue_before=plan.queue_before,
            recovered_stale=plan.recovered_stale,
            discovery=empty_discovery_payload(attempted=False),
        )
        inserted = 0
        if plan.run_discovery:
            inserted = self._run_discovery(report, dry_run=dry_run, listing_fetcher=listing_fetcher)
            if report.stop_reason == STOP_REASON_DISCOVERY_SOURCE_ERROR:
                report.orchestration_decision = ORCHESTRATION_NO_NEW_DISCOVERY
                report.queue_after = snapshot_queue_status(self.queue_repo, plan.now)
                report.queue_counts = report.queue_after
                report.finished_at = _utcnow().isoformat()
                return report
            if inserted <= 0 or dry_run:
                report.orchestration_decision = ORCHESTRATION_NO_NEW_DISCOVERY
                report.stop_reason = report.stop_reason or STOP_REASON_QUEUE_EMPTY
                report.queue_after = snapshot_queue_status(self.queue_repo, plan.now)
                report.queue_counts = report.queue_after
                report.finished_at = _utcnow().isoformat()
                return report

        if plan.run_participation and (not plan.run_discovery or inserted > 0):
            self._run_participation(
                report,
                max_symbols=max_symbols,
                dry_run=dry_run,
                now=plan.now,
                trigger_type=trigger_type,
                fmp_client=fmp_client,
                sec_client=sec_client,
                participation_repo=participation_repo,
                candidate_repo=candidate_repo,
                sec_ticker_lookup=sec_ticker_lookup,
            )
            if plan.run_discovery:
                report.orchestration_decision = ORCHESTRATION_DISCOVERY_AND_PARTICIPATION
            else:
                report.orchestration_decision = ORCHESTRATION_PARTICIPATION_ONLY
        else:
            report.orchestration_decision = ORCHESTRATION_NO_NEW_DISCOVERY
            report.stop_reason = report.stop_reason or STOP_REASON_QUEUE_EMPTY

        report.queue_after = snapshot_queue_status(self.queue_repo, plan.now)
        report.queue_counts = report.queue_after
        report.finished_at = _utcnow().isoformat()
        return report

    def run(
        self,
        *,
        run_id: Optional[str] = None,
        max_symbols: Optional[int] = None,
        dry_run: bool = False,
        now: Optional[datetime] = None,
        trigger_type: str = "",
        allow_second_run_today: bool = False,
        run_date=None,
        fmp_client: Any = None,
        sec_client: Any = None,
        participation_repo: Any = None,
        candidate_repo: Any = None,
        sec_ticker_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
        listing_fetcher: Optional[ListingFetcher] = None,
    ) -> DailyExpansionRunReport:
        self._discovery_executed = False
        self._participation_executed = False
        resolved_run_id = run_id or str(uuid4())
        plan = self.plan(
            now=now,
            dry_run=dry_run,
            trigger_type=trigger_type,
            allow_second_run_today=allow_second_run_today,
            run_date=run_date,
        )
        return self.execute(
            plan,
            run_id=resolved_run_id,
            max_symbols=max_symbols,
            dry_run=dry_run,
            trigger_type=trigger_type,
            fmp_client=fmp_client,
            sec_client=sec_client,
            participation_repo=participation_repo,
            candidate_repo=candidate_repo,
            sec_ticker_lookup=sec_ticker_lookup,
            listing_fetcher=listing_fetcher,
        )

    def _run_discovery(
        self,
        report: DailyExpansionRunReport,
        *,
        dry_run: bool,
        listing_fetcher: Optional[ListingFetcher],
    ) -> int:
        if self._discovery_executed:
            raise RuntimeError("discovery already executed in this orchestration cycle")
        self._discovery_executed = True
        if dry_run:
            report.discovery = empty_discovery_payload(attempted=True)
            return 0
        fetcher = listing_fetcher or self.listing_fetcher
        try:
            if fetcher is not None:
                nasdaq_rows, other_rows, sec_rows = fetcher()
            elif self.listing_client is not None:
                nasdaq_rows, other_rows, sec_rows = fetch_us_equity_listing_feeds(
                    self.listing_client
                )
            else:
                raise UniverseSourceError("listing fetcher is not configured")
        except Exception as exc:
            report.discovery = empty_discovery_payload(
                attempted=True,
                error=str(exc) or exc.__class__.__name__,
            )
            report.stop_reason = STOP_REASON_DISCOVERY_SOURCE_ERROR
            return 0

        ingest = self.discovery_ingest(
            self.queue_repo,
            nasdaq_rows=nasdaq_rows,
            other_rows=other_rows,
            sec_rows=sec_rows,
            discovery_capacity=self.budget_config.discovery_capacity,
            max_new_symbols_per_ingest=self.budget_config.max_new_symbols_per_ingest,
        )
        report.discovery = discovery_payload_from_ingest(ingest, attempted=True)
        return int(ingest.inserted)

    def _run_participation(
        self,
        report: DailyExpansionRunReport,
        *,
        max_symbols: Optional[int],
        dry_run: bool,
        now: datetime,
        trigger_type: str,
        fmp_client: Any,
        sec_client: Any,
        participation_repo: Any,
        candidate_repo: Any,
        sec_ticker_lookup: Optional[Mapping[str, Mapping[str, Any]]],
    ) -> None:
        if self._participation_executed:
            raise RuntimeError("participation already executed in this orchestration cycle")
        self._participation_executed = True
        safety_cap = (
            max_symbols
            if max_symbols is not None
            else self.budget_config.max_symbols_per_run
        )
        participation = self.participation_service.run_once(
            run_id=report.run_id,
            max_symbols=safety_cap,
            dry_run=dry_run,
            now=now,
            seed_if_empty=False,
            trigger_type=trigger_type,
            fmp_client=fmp_client,
            sec_client=sec_client,
            participation_repo=participation_repo,
            candidate_repo=candidate_repo,
            sec_ticker_lookup=sec_ticker_lookup,
        )
        report.symbols_considered = participation.symbols_considered
        report.symbols_started = participation.symbols_started
        report.symbols_completed = participation.symbols_completed
        report.symbols_retryable = participation.symbols_retryable
        report.symbols_blocked = participation.symbols_blocked
        report.symbols_skipped = participation.symbols_skipped
        report.fmp_calls_used = participation.fmp_calls_used
        report.sec_calls_used = participation.sec_calls_used
        report.cache_hits = dict(participation.cache_hits)
        report.budget_remaining = dict(participation.budget_remaining)
        report.stop_reason = participation.stop_reason
        report.symbol_details = list(participation.symbol_details)
