#!/usr/bin/env python3
"""Daily wealth snapshot — Istanbul calendar day, persisted prices only, 0 LLM."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.wealth_automation_run_repository import WealthAutomationRunRepository
from repositories.wealth_portfolio_admin_repository import WealthPortfolioAdminRepository
from repositories.wealth_portfolio_snapshot_repository import (
    WealthPortfolioSnapshotRepository,
)
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.wealth_core_service import WealthCoreService
from services.wealth_snapshot_capture_service import (
    SnapshotCaptureStatus,
    capture_portfolio_snapshot,
)


JOB_NAME = "daily_wealth_snapshot"


def _result_public(item) -> dict:
    return {
        "status": item.status.value,
        "dry_run": item.dry_run,
        "written": item.written,
        "snapshot_date": item.snapshot_date,
        "valuation_complete": item.valuation_complete,
        "priced_market_value": item.priced_market_value,
        "unpriced_symbols": list(item.unpriced_symbols),
        "unpriced_position_count": item.unpriced_position_count,
        "base_currency": item.base_currency,
        "error": item.error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily wealth snapshot")
    parser.add_argument("--user-id", help="Optional single-user scope")
    parser.add_argument("--portfolio-id", help="Optional portfolio scope with --user-id")
    parser.add_argument("--trigger-type", default="scheduled")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-second-run-today",
        action="store_true",
        help="Bypass job-run lock only; per-portfolio Istanbul-day skip still applies.",
    )
    args = parser.parse_args()

    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    today = WealthPortfolioSnapshotRepository.istanbul_calendar_date()
    runs = None
    run_id = None
    if not args.dry_run:
        runs = WealthAutomationRunRepository(client)
        existing = runs.get_run(
            job_name=JOB_NAME, run_date=today, trigger_type=args.trigger_type
        )
        if existing and not args.allow_second_run_today:
            if str(existing.get("status") or "") in {"COMPLETED", "RUNNING"}:
                print(json.dumps({"status": "skipped", "reason": "already_run"}, default=str))
                return 0
        started = runs.try_start_run(
            job_name=JOB_NAME, run_date=today, trigger_type=args.trigger_type
        )
        if started is None and not args.allow_second_run_today:
            print(json.dumps({"status": "skipped", "reason": "duplicate"}, default=str))
            return 0
        run_id = str((started or existing or {}).get("id") or "")

    if args.user_id:
        wealth = WealthCoreService(client, args.user_id)
        if args.portfolio_id:
            portfolios = [
                row
                for row in wealth.portfolios.list_for_user(args.user_id)
                if str(row.get("id") or "") == str(args.portfolio_id)
            ]
        else:
            default = wealth.portfolios.get_default_for_user(args.user_id)
            portfolios = [default] if default else []
    else:
        portfolios = WealthPortfolioAdminRepository(client).list_active_portfolios_for_snapshot()

    results = []
    failures = 0
    created = 0
    skipped = 0
    for portfolio in portfolios:
        user_id = str(portfolio.get("user_id") or args.user_id or "")
        if not user_id:
            failures += 1
            continue
        wealth = WealthCoreService(client, user_id)
        item = capture_portfolio_snapshot(
            wealth,
            portfolio,
            dry_run=args.dry_run,
        )
        results.append(_result_public(item))
        if item.status == SnapshotCaptureStatus.CREATED and item.written:
            created += 1
        elif item.status == SnapshotCaptureStatus.ALREADY_CAPTURED:
            skipped += 1
        elif item.status in {
            SnapshotCaptureStatus.ERROR,
            SnapshotCaptureStatus.VALUATION_UNAVAILABLE,
            SnapshotCaptureStatus.NO_PORTFOLIO,
        }:
            failures += 1
        elif item.status == SnapshotCaptureStatus.CREATED and args.dry_run:
            created += 1

    if runs is not None and run_id:
        runs.finish_run(
            run_id,
            status="COMPLETED" if failures == 0 else "FAILED",
            records_updated=created,
            provider_calls=0,
            report_payload={
                "portfolio_count": len(portfolios),
                "created": created,
                "already_captured": skipped,
                "failure_count": failures,
                "dry_run": False,
                "snapshot_date": today.isoformat(),
            },
        )

    payload = {
        "status": "dry_run" if args.dry_run else ("completed" if failures == 0 else "partial"),
        "snapshot_date": today.isoformat(),
        "timezone": "Europe/Istanbul",
        "portfolio_count": len(portfolios),
        "created": created,
        "already_captured": skipped,
        "failure_count": failures,
        "provider_calls": 0,
        "llm_calls": 0,
        "results": results,
    }
    print(json.dumps(payload, default=str))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(
            "\n".join(
                [
                    "## Daily Wealth Snapshot",
                    "",
                    f"- Istanbul date: {today.isoformat()}",
                    f"- Portfolios: {len(portfolios)}",
                    f"- Created: {created}",
                    f"- Already captured: {skipped}",
                    f"- Failures: {failures}",
                    "- Provider calls: 0",
                    "- LLM calls: 0",
                    f"- Dry-run: {args.dry_run}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
