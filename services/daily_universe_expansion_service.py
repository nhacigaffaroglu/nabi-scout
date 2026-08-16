from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.provider_budget_service import ProviderBudgetManager
from services.provider_call_ledger import ProviderCallLedger
from services.universe_expansion_contract import (
    ERROR_CATEGORY_PROVIDER_ERROR,
    ERROR_CATEGORY_RATE_LIMIT,
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_IN_PROGRESS,
    EXPANSION_STATUS_RETRYABLE,
    EXPANSION_STATUS_SKIPPED,
    PROVIDER_FMP,
    PROVIDER_SEC,
    STOP_REASON_BUDGET_EXHAUSTED,
    STOP_REASON_ERROR_THRESHOLD,
    STOP_REASON_QUEUE_EMPTY,
    STOP_REASON_RATE_LIMIT,
    STOP_REASON_SAFETY_CAP,
)
from services.universe_expansion_cost_model import estimate_participation_minimum_cost
from services.universe_expansion_onboarding_service import (
    OnboardingResult,
    compute_next_retry_at,
    onboarding_final_status,
    provider_call_totals,
    run_participation_onboarding,
)
from config.universe_expansion_sources import dedupe_expansion_symbols
from services.universe_expansion_provider_wrappers import (
    wrap_fmp_client,
    wrap_sec_client,
)
from services.universe_expansion_seed_service import seed_universe_expansion_queue


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SymbolRunDetail:
    symbol: str
    priority: int
    estimated_calls: Dict[str, int]
    action: str
    reason: str = ""
    result: Optional[OnboardingResult] = None

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "symbol": self.symbol,
            "priority": self.priority,
            "estimated_calls": dict(self.estimated_calls),
            "action": self.action,
            "reason": self.reason,
        }
        if self.result is not None:
            payload["result"] = self.result.to_dict()
        return payload


@dataclass
class DailyExpansionRunReport:
    run_id: str
    started_at: str
    finished_at: str = ""
    dry_run: bool = False
    symbols_considered: int = 0
    symbols_started: int = 0
    symbols_completed: int = 0
    symbols_retryable: int = 0
    symbols_blocked: int = 0
    symbols_skipped: int = 0
    fmp_calls_used: int = 0
    sec_calls_used: int = 0
    cache_hits: Dict[str, int] = field(default_factory=dict)
    budget_remaining: Dict[str, int] = field(default_factory=dict)
    stop_reason: str = ""
    trigger_type: str = ""
    symbol_details: List[SymbolRunDetail] = field(default_factory=list)
    queue_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "dry_run": self.dry_run,
            "symbols_considered": self.symbols_considered,
            "symbols_started": self.symbols_started,
            "symbols_completed": self.symbols_completed,
            "symbols_retryable": self.symbols_retryable,
            "symbols_blocked": self.symbols_blocked,
            "symbols_skipped": self.symbols_skipped,
            "fmp_calls_used": self.fmp_calls_used,
            "sec_calls_used": self.sec_calls_used,
            "cache_hits": dict(self.cache_hits),
            "budget_remaining": dict(self.budget_remaining),
            "stop_reason": self.stop_reason,
            "trigger_type": self.trigger_type,
            "symbol_details": [item.to_dict() for item in self.symbol_details],
            "queue_counts": dict(self.queue_counts),
        }


class DailyUniverseExpansionService:
    def __init__(
        self,
        *,
        queue_repo: UniverseExpansionRepository,
        budget_config: Optional[UniverseExpansionBudgetConfig] = None,
        onboarding_runner=run_participation_onboarding,
    ) -> None:
        self.queue_repo = queue_repo
        self.budget_config = budget_config or UniverseExpansionBudgetConfig.from_env()
        self.onboarding_runner = onboarding_runner

    def run_once(
        self,
        *,
        max_symbols: Optional[int] = None,
        dry_run: bool = False,
        now: Optional[datetime] = None,
        seed_if_empty: bool = True,
        source_filter: set[str] | None = None,
        trigger_type: str = "",
        run_id: Optional[str] = None,
        fmp_client: Any = None,
        sec_client: Any = None,
        participation_repo: Any = None,
        candidate_repo: Any = None,
        sec_ticker_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> DailyExpansionRunReport:
        timestamp = now or _utcnow()
        resolved_run_id = run_id or str(uuid4())
        report = DailyExpansionRunReport(
            run_id=resolved_run_id,
            started_at=timestamp.isoformat(),
            dry_run=dry_run,
            trigger_type=trigger_type,
        )

        if seed_if_empty and not dry_run and not self.queue_repo.list_all():
            seed_universe_expansion_queue(self.queue_repo, source_filter=source_filter)

        if not dry_run:
            self.queue_repo.recover_stale_in_progress(
                timestamp,
                stale_minutes=self.budget_config.stale_in_progress_minutes,
            )

        budget = ProviderBudgetManager(self.budget_config)
        ledger = ProviderCallLedger()

        if not dry_run:
            if fmp_client is not None:
                fmp_client = wrap_fmp_client(fmp_client, ledger=ledger, budget=budget)
            if sec_client is not None:
                sec_client = wrap_sec_client(sec_client, ledger=ledger, budget=budget)
        min_cost = estimate_participation_minimum_cost()
        safety_cap = max_symbols if max_symbols is not None else 10_000
        error_count = 0

        eligible = self.queue_repo.list_eligible(timestamp, limit=500)
        if dry_run and not eligible:
            for symbol, _source, priority in dedupe_expansion_symbols():
                eligible.append(
                    {
                        "symbol": symbol,
                        "priority": priority,
                        "status": EXPANSION_STATUS_RETRYABLE,
                        "id": f"dry-{symbol}",
                    }
                )
            eligible.sort(key=lambda item: (item.get("priority", 100), item.get("symbol", "")))
        for row in eligible:
            if report.symbols_started >= safety_cap:
                report.stop_reason = STOP_REASON_SAFETY_CAP
                break
            if budget.is_rate_limited(PROVIDER_FMP) or budget.is_rate_limited(PROVIDER_SEC):
                report.stop_reason = STOP_REASON_RATE_LIMIT
                break

            status = row.get("status")
            symbol = str(row.get("symbol") or "").upper()
            priority = int(row.get("priority") or 100)
            report.symbols_considered += 1

            if status == EXPANSION_STATUS_COMPLETED:
                report.symbols_skipped += 1
                report.symbol_details.append(
                    SymbolRunDetail(
                        symbol=symbol,
                        priority=priority,
                        estimated_calls=min_cost.by_provider,
                        action="skipped",
                        reason="already_completed",
                    )
                )
                continue

            if status == EXPANSION_STATUS_IN_PROGRESS:
                report.symbols_skipped += 1
                report.symbol_details.append(
                    SymbolRunDetail(
                        symbol=symbol,
                        priority=priority,
                        estimated_calls=min_cost.by_provider,
                        action="skipped",
                        reason="in_progress",
                    )
                )
                continue

            if status == EXPANSION_STATUS_RETRYABLE:
                next_retry = row.get("next_retry_at")
                if next_retry:
                    retry_at = datetime.fromisoformat(str(next_retry).replace("Z", "+00:00"))
                    if retry_at > timestamp:
                        report.symbols_skipped += 1
                        report.symbol_details.append(
                            SymbolRunDetail(
                                symbol=symbol,
                                priority=priority,
                                estimated_calls=min_cost.by_provider,
                                action="skipped",
                                reason="retry_backoff",
                            )
                        )
                        continue

            if not budget.can_afford_operations(min_cost.by_provider):
                report.stop_reason = STOP_REASON_BUDGET_EXHAUSTED
                report.symbol_details.append(
                    SymbolRunDetail(
                        symbol=symbol,
                        priority=priority,
                        estimated_calls=min_cost.by_provider,
                        action="skipped",
                        reason="budget_insufficient",
                    )
                )
                break

            if dry_run:
                report.symbols_started += 1
                report.symbol_details.append(
                    SymbolRunDetail(
                        symbol=symbol,
                        priority=priority,
                        estimated_calls=min_cost.by_provider,
                        action="would_process",
                        reason="dry_run",
                    )
                )
                continue

            claimed = self.queue_repo.claim(str(row["id"]), run_id=resolved_run_id, now=timestamp)
            if claimed is None:
                report.symbols_skipped += 1
                report.symbol_details.append(
                    SymbolRunDetail(
                        symbol=symbol,
                        priority=priority,
                        estimated_calls=min_cost.by_provider,
                        action="skipped",
                        reason="claim_failed",
                    )
                )
                continue

            report.symbols_started += 1
            try:
                onboarding = self.onboarding_runner(
                    symbol,
                    fmp_client=fmp_client,
                    sec_client=sec_client,
                    participation_repo=participation_repo,
                    candidate_repo=candidate_repo,
                    sec_ticker_lookup=sec_ticker_lookup,
                )
            except Exception as exc:
                onboarding = OnboardingResult(
                    symbol=symbol,
                    success=False,
                    error_category=ERROR_CATEGORY_PROVIDER_ERROR,
                    error_message=exc.__class__.__name__,
                )

            if onboarding.company_intelligence_calls:
                error_count += 1

            final_status = onboarding_final_status(
                onboarding,
                budget_rate_limited=budget.is_rate_limited(PROVIDER_FMP)
                or budget.is_rate_limited(PROVIDER_SEC),
            )
            next_retry = compute_next_retry_at(
                timestamp,
                error_category=onboarding.error_category,
                attempt_count=int(claimed.get("attempt_count") or 1),
                default_hours=self.budget_config.default_retry_backoff_hours,
                plan_restricted_days=self.budget_config.plan_restricted_retry_days,
            )

            provider_calls_used = dict(claimed.get("provider_calls_used") or {})
            if onboarding.provider_calls:
                for key, value in provider_call_totals(onboarding.provider_calls).items():
                    provider_calls_used[key] = int(provider_calls_used.get(key, 0)) + value

            self.queue_repo.finalize(
                str(claimed["id"]),
                {
                    "status": final_status,
                    "participation_status": onboarding.participation_status,
                    "research_allowed": onboarding.research_allowed,
                    "last_error_category": onboarding.error_category,
                    "provider_calls_used": provider_calls_used,
                    "next_retry_at": next_retry,
                    "completed_at": timestamp.isoformat()
                    if final_status == EXPANSION_STATUS_COMPLETED
                    else None,
                    "claimed_at": None,
                    "claim_run_id": None,
                },
            )

            if final_status == EXPANSION_STATUS_COMPLETED:
                report.symbols_completed += 1
            elif final_status == EXPANSION_STATUS_RETRYABLE:
                report.symbols_retryable += 1
            else:
                report.symbols_blocked += 1

            report.symbol_details.append(
                SymbolRunDetail(
                    symbol=symbol,
                    priority=priority,
                    estimated_calls=min_cost.by_provider,
                    action="processed",
                    reason=final_status,
                    result=onboarding,
                )
            )

            if onboarding.error_category == ERROR_CATEGORY_RATE_LIMIT:
                report.stop_reason = STOP_REASON_RATE_LIMIT
                break

            if onboarding.company_intelligence_calls:
                if error_count >= self.budget_config.max_errors_before_stop:
                    report.stop_reason = STOP_REASON_ERROR_THRESHOLD
                    break

            if not report.stop_reason and not budget.can_afford_operations(min_cost.by_provider):
                report.stop_reason = STOP_REASON_BUDGET_EXHAUSTED

        if not report.stop_reason:
            if report.dry_run and report.symbols_started == 0 and not eligible:
                report.stop_reason = STOP_REASON_QUEUE_EMPTY
            elif not report.dry_run and report.symbols_started == 0:
                report.stop_reason = STOP_REASON_QUEUE_EMPTY

        report.fmp_calls_used = budget.fmp.spent
        report.sec_calls_used = budget.sec.spent
        report.cache_hits = dict(ledger.cache_hits)
        report.budget_remaining = {
            PROVIDER_FMP: budget.remaining(PROVIDER_FMP),
            PROVIDER_SEC: budget.remaining(PROVIDER_SEC),
        }
        report.queue_counts = self.queue_repo.count_by_status()
        report.finished_at = _utcnow().isoformat()
        return report
