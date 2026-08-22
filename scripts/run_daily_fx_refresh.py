#!/usr/bin/env python3
"""Daily FX rate refresh — scheduled only, not page render."""
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

from services.fx_rate_refresh_service import FxRateRefreshService
from services.fmp_client import FMPClient, FMPError
from services.alpha_vantage_client import AlphaVantageClient, AlphaVantageError
from services.twelve_data_client import TwelveDataClient, TwelveDataError
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily FX refresh")
    parser.add_argument("--trigger-type", default="scheduled")
    parser.add_argument("--allow-second-run-today", action="store_true")
    args = parser.parse_args()

    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    try:
        fmp = FMPClient.from_env()
    except FMPError:
        fmp = None
    try:
        alpha = AlphaVantageClient.from_env()
    except AlphaVantageError:
        alpha = None
    try:
        twelve = TwelveDataClient.from_env()
    except TwelveDataError:
        twelve = None
    service = FxRateRefreshService(
        client,
        fmp_client=fmp,
        twelve_data_client=twelve,
        alpha_vantage_client=alpha,
    )
    gate = service.evaluate_run(
        trigger_type=args.trigger_type,
        allow_second_run=args.allow_second_run_today,
    )
    if gate.get("skipped"):
        print(json.dumps({"status": "skipped", **gate}, default=str))
        return 0

    run_id = str(gate["run_id"])
    updated = service.refresh_pairs()
    service.finish(run_id, records_updated=updated, report={"pairs_updated": updated})
    result = {
        "status": "completed",
        "run_id": run_id,
        "pairs_updated": updated,
        "provider_calls": service.provider_calls,
        "llm_calls": 0,
    }
    print(json.dumps(result, default=str))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(
            f"## Daily FX Refresh\n\n- Pairs updated: {updated}\n- Provider calls: {service.provider_calls}\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
