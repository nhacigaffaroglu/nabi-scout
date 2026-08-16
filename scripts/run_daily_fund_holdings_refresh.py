#!/usr/bin/env python3
"""Daily fund holdings refresh — scheduled only."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.fmp_client import FMPClient, FMPError
from services.fund_holdings_refresh_service import FundHoldingsRefreshService
from services.wave4_monitor_context import discover_fund_symbols_for_refresh
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily fund holdings refresh")
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--trigger-type", default="scheduled")
    parser.add_argument("--allow-second-run-today", action="store_true")
    args = parser.parse_args()

    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    try:
        fmp = FMPClient.from_env()
    except FMPError:
        fmp = None

    service = FundHoldingsRefreshService(client, fmp_client=fmp)
    gate = service.evaluate_run(
        trigger_type=args.trigger_type,
        allow_second_run=args.allow_second_run_today,
    )
    if gate.get("skipped"):
        print(json.dumps({"status": "skipped", **gate}, default=str))
        return 0

    symbols = set(s.upper() for s in args.symbols)
    if not symbols:
        symbols = discover_fund_symbols_for_refresh(client)

    run_id = str(gate["run_id"])
    updated = service.refresh_symbols(symbols)
    service.finish(run_id, records_updated=updated, report={"funds_updated": updated})
    result = {
        "status": "completed",
        "run_id": run_id,
        "funds_updated": updated,
        "provider_calls": service.provider_calls,
        "llm_calls": 0,
    }
    print(json.dumps(result, default=str))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(
            f"## Daily Fund Holdings Refresh\n\n- Funds updated: {updated}\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
