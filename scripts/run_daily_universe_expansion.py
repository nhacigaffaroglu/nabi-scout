#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from config.universe_expansion_sources import dedupe_expansion_symbols
from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import ParticipationAssessmentRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.universe_expansion_run_repository import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    TRIGGER_WORKFLOW_DISPATCH,
    UniverseExpansionRunRepository,
)
from services.daily_universe_expansion_service import (
    DailyExpansionRunReport,
    DailyUniverseExpansionService,
)
from services.fmp_client import FMPClient, FMPError
from services.free_universe_client import FreeUniverseClient
from services.scheduled_universe_expansion_service import (
    evaluate_scheduled_expansion_run,
    expansion_run_date,
)
from services.universe_expansion_contract import STOP_REASON_ALREADY_RAN_TODAY
from services.sec_financial_client import SECFinancialClient
from services.supabase_admin_client import (
    SupabaseAdminClientError,
    apply_local_secrets_to_env,
    create_admin_supabase_client,
    is_publishable_supabase_key,
)
from services.universe_expansion_contract import (
    STOP_REASON_BUDGET_EXHAUSTED,
    STOP_REASON_ERROR_THRESHOLD,
    STOP_REASON_QUEUE_EMPTY,
    STOP_REASON_RATE_LIMIT,
    STOP_REASON_SAFETY_CAP,
)
from services.universe_expansion_run_report import (
    format_expansion_run_summary,
    write_github_step_summary,
)
from services.universe_expansion_seed_service import seed_universe_expansion_queue

INFRASTRUCTURE_STOP_REASONS = frozenset({
    STOP_REASON_ERROR_THRESHOLD,
})


def _load_sec_lookup(contact_email: str) -> dict:
    if not contact_email.strip():
        return {}
    rows = FreeUniverseClient(contact_email=contact_email.strip()).get_sec_companies()
    return {
        str(row.get("symbol") or "").strip().upper(): row
        for row in rows
        if row.get("symbol")
    }


def _print_coverage(repo: UniverseExpansionRepository) -> None:
    counts = repo.count_by_status()
    total_static = len(dedupe_expansion_symbols())
    print("Coverage status")
    print(f"  Static universe size: {total_static}")
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")


def _print_report(report: DailyExpansionRunReport, *, trigger: str) -> None:
    print(format_expansion_run_summary(report.to_dict(), trigger=trigger))


def _detect_trigger(explicit: str) -> str:
    if explicit:
        return explicit
    event = (os.environ.get("GITHUB_EVENT_NAME") or "").strip().lower()
    if event == "schedule":
        return TRIGGER_SCHEDULED
    if event == "workflow_dispatch":
        return TRIGGER_WORKFLOW_DISPATCH
    return TRIGGER_MANUAL


def _validate_headless_secrets() -> None:
    missing: list[str] = []
    if not (os.environ.get("SUPABASE_URL") or "").strip():
        missing.append("SUPABASE_URL")
    service_key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    fallback_key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not service_key and (not fallback_key or is_publishable_supabase_key(fallback_key)):
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if not (os.environ.get("FMP_API_KEY") or "").strip():
        missing.append("FMP_API_KEY")
    if not (os.environ.get("SEC_CONTACT_EMAIL") or "").strip():
        missing.append("SEC_CONTACT_EMAIL")
    if missing:
        raise SupabaseAdminClientError(
            "Missing required headless secrets: "
            + ", ".join(missing)
            + ". GitHub Actions must use SUPABASE_SERVICE_ROLE_KEY."
        )


def _resolve_max_symbols(
    cli_value: Optional[int],
    budget_config: UniverseExpansionBudgetConfig,
) -> Optional[int]:
    if cli_value is not None:
        return cli_value if cli_value > 0 else None
    configured = budget_config.max_symbols_per_run
    return configured if configured > 0 else None


def _exit_code(report: DailyExpansionRunReport) -> int:
    if report.stop_reason in INFRASTRUCTURE_STOP_REASONS:
        return 1
    return 0


def _skipped_report(
    *,
    trigger: str,
    stop_reason: str,
    dry_run: bool,
) -> DailyExpansionRunReport:
    now = datetime.now(timezone.utc).isoformat()
    return DailyExpansionRunReport(
        run_id=str(uuid4()),
        started_at=now,
        finished_at=now,
        dry_run=dry_run,
        trigger_type=trigger,
        stop_reason=stop_reason,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily universe expansion.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-second-run-today", action="store_true")
    parser.add_argument(
        "--trigger-type",
        choices=(
            TRIGGER_SCHEDULED,
            TRIGGER_MANUAL,
            TRIGGER_WORKFLOW_DISPATCH,
        ),
        default="",
    )
    args = parser.parse_args()

    apply_local_secrets_to_env()
    budget_config = UniverseExpansionBudgetConfig.from_env()
    trigger = _detect_trigger(args.trigger_type)
    queue_repo = UniverseExpansionRepository()
    run_repo = UniverseExpansionRunRepository()

    if not args.dry_run:
        try:
            _validate_headless_secrets()
            client = create_admin_supabase_client()
            queue_repo = UniverseExpansionRepository(client)
            run_repo = UniverseExpansionRunRepository(client)
        except SupabaseAdminClientError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if args.coverage:
        _print_coverage(queue_repo)
        return 0

    if args.seed_only:
        if args.dry_run:
            print("Seed-only skipped in dry-run (no DB mutations).")
            return 0
        try:
            inserted = seed_universe_expansion_queue(queue_repo)
        except SupabaseAdminClientError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Seeded {inserted} symbols.")
        return 0

    now = datetime.now(timezone.utc)
    run_date = expansion_run_date(now)
    should_run, skip_reason, _existing = evaluate_scheduled_expansion_run(
        run_repo,
        run_date=run_date,
        now=now,
        dry_run=args.dry_run,
        allow_second_run_today=args.allow_second_run_today,
        trigger_type=trigger,
    )
    if not should_run:
        report = _skipped_report(
            trigger=trigger,
            stop_reason=STOP_REASON_ALREADY_RAN_TODAY,
            dry_run=args.dry_run,
        )
        if skip_reason:
            print(skip_reason)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        else:
            _print_report(report, trigger=trigger)
        write_github_step_summary(report.to_dict(), trigger=trigger)
        return 0

    sec_email = (os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
    fmp_client = None
    sec_client = None
    participation_repo = None
    candidate_repo = None
    sec_lookup = {}

    run_id = str(uuid4())
    if not args.dry_run:
        try:
            fmp_client = FMPClient.from_env()
        except FMPError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        sec_client = SECFinancialClient(contact_email=sec_email)
        sec_lookup = _load_sec_lookup(sec_email)
        participation_repo = ParticipationAssessmentRepository(queue_repo.client)
        candidate_repo = CandidateRepository(queue_repo.client)
        run_repo.start_run(
            run_id=run_id,
            run_date=run_date,
            trigger_type=trigger,
            dry_run=False,
            allow_second_run_today=args.allow_second_run_today,
            started_at=now,
        )

    service = DailyUniverseExpansionService(
        queue_repo=queue_repo,
        budget_config=budget_config,
    )
    max_symbols = _resolve_max_symbols(args.max_symbols, budget_config)
    report = service.run_once(
        run_id=run_id,
        max_symbols=max_symbols,
        dry_run=args.dry_run,
        now=now,
        trigger_type=trigger,
        fmp_client=fmp_client,
        sec_client=sec_client,
        participation_repo=participation_repo,
        candidate_repo=candidate_repo,
        sec_ticker_lookup=sec_lookup,
    )

    if not args.dry_run:
        status = RUN_STATUS_COMPLETED
        if report.stop_reason in INFRASTRUCTURE_STOP_REASONS:
            status = RUN_STATUS_FAILED
        run_repo.finalize_run(
            report.run_id,
            status=status,
            stop_reason=report.stop_reason,
            report=report.to_dict(),
            finished_at=datetime.now(timezone.utc),
        )
    elif report.symbols_started == 0 and not report.stop_reason:
        report.stop_reason = STOP_REASON_QUEUE_EMPTY

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _print_report(report, trigger=trigger)
        if not args.dry_run:
            _print_coverage(queue_repo)

    write_github_step_summary(
        report.to_dict(),
        trigger=trigger,
        queue_counts=report.queue_counts,
    )
    return _exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
