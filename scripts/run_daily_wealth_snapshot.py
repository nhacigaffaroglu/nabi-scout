#!/usr/bin/env python3
"""Daily wealth snapshot automation — multi-user, 0 LLM, persisted prices/FX."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.wealth_automation_run_repository import WealthAutomationRunRepository
from repositories.wealth_portfolio_admin_repository import WealthPortfolioAdminRepository
from services.candidate_price_service import CandidatePriceService
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.wealth_core_service import WealthCoreService
from services.wealth_timeline_service import WealthTimelineService


JOB_NAME = "daily_wealth_snapshot"


def _snapshot_portfolio(client, *, user_id: str, portfolio: dict) -> dict:
    wealth = WealthCoreService(client, user_id)
    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(wealth, price_service, nabi_client=client)
    view = intelligence.build_view(portfolio, enrich_nabi=False)
    timeline = WealthTimelineService(wealth)
    saved = timeline.save_snapshot_from_view(portfolio, view)
    return {
        "portfolio_id": str(portfolio.get("id") or ""),
        "user_id": user_id,
        "snapshot_id": saved.id,
        "price_lookups": price_service.fetch_count,
        "fx_supported": view.fx_supported,
        "unpriced_position_count": view.unpriced_position_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily wealth snapshot")
    parser.add_argument("--user-id", help="Optional single-user scope for verification")
    parser.add_argument("--portfolio-id", help="Optional portfolio scope with --user-id")
    parser.add_argument("--trigger-type", default="scheduled")
    parser.add_argument("--allow-second-run-today", action="store_true")
    args = parser.parse_args()

    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    runs = WealthAutomationRunRepository(client)
    admin = WealthPortfolioAdminRepository(client)
    today = date.today()
    existing = runs.get_run(job_name=JOB_NAME, run_date=today, trigger_type=args.trigger_type)
    if existing and not args.allow_second_run_today:
        if str(existing.get("status") or "") in {"COMPLETED", "RUNNING"}:
            print(json.dumps({"status": "skipped", "reason": "already_run"}, default=str))
            return 0

    started = runs.try_start_run(job_name=JOB_NAME, run_date=today, trigger_type=args.trigger_type)
    if started is None and not args.allow_second_run_today:
        print(json.dumps({"status": "skipped", "reason": "duplicate"}, default=str))
        return 0
    run_id = str((started or existing or {}).get("id"))

    if args.user_id:
        wealth = WealthCoreService(client, args.user_id)
        if args.portfolio_id:
            portfolios = [
                row
                for row in wealth.portfolios.list_for_user(args.user_id)
                if str(row.get("id") or "") == str(args.portfolio_id)
            ]
        else:
            portfolios = [wealth.ensure_default_portfolio()]
    else:
        portfolios = admin.list_active_portfolios_for_snapshot()

    results = []
    total_price_lookups = 0
    failures = 0
    for portfolio in portfolios:
        user_id = str(portfolio.get("user_id") or "")
        if not user_id:
            failures += 1
            continue
        try:
            item = _snapshot_portfolio(client, user_id=user_id, portfolio=portfolio)
            total_price_lookups += int(item.get("price_lookups") or 0)
            results.append(item)
        except Exception as exc:
            failures += 1
            results.append(
                {
                    "portfolio_id": str(portfolio.get("id") or ""),
                    "user_id": user_id,
                    "error": str(exc),
                }
            )

    runs.finish_run(
        run_id,
        status="COMPLETED" if failures == 0 else "FAILED",
        records_updated=len(results),
        provider_calls=total_price_lookups,
        report_payload={
            "portfolio_count": len(portfolios),
            "snapshot_count": sum(1 for row in results if row.get("snapshot_id")),
            "failure_count": failures,
        },
    )
    result = {
        "status": "completed" if failures == 0 else "partial",
        "run_id": run_id,
        "portfolio_count": len(portfolios),
        "snapshot_count": sum(1 for row in results if row.get("snapshot_id")),
        "failure_count": failures,
        "price_lookups": total_price_lookups,
        "llm_calls": 0,
    }
    print(json.dumps(result, default=str))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(
            "\n".join(
                [
                    "## Daily Wealth Snapshot",
                    "",
                    f"- Portfolios processed: {len(portfolios)}",
                    f"- Snapshots written: {result['snapshot_count']}",
                    f"- Failures: {failures}",
                    f"- Price lookups: {total_price_lookups}",
                    "- LLM calls: 0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
