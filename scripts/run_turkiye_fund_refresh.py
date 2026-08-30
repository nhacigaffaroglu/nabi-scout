#!/usr/bin/env python3
"""Turkish fund canonical snapshot refresh.

Default is dry-run with zero writes. Live persistence is refused in this
foundation sprint. Credentials never enable writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.bist_refresh_contract import REASON_LIVE_UNSAFE
from services.fund_product_contract import PILOT_TEFAS_FUND_CODES
from services.turkiye_fund_refresh_contract import JOB_NAME, STATE_CACHE_PATH
from services.turkiye_fund_refresh_orchestrator import run_turkiye_fund_refresh


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Turkish fund canonical snapshot refresh")
    parser.add_argument("--symbols", default=",".join(PILOT_TEFAS_FUND_CODES))
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true", default=False)
    parser.add_argument("--persist-fund-intelligence", action="store_true", default=False)
    parser.add_argument("--persist-participation", action="store_true", default=False)
    parser.add_argument("--persist-economic-exposure", action="store_true", default=False)
    parser.add_argument("--persist-decisions", action="store_true", default=False)
    parser.add_argument("--allow-live", action="store_true", default=False)
    parser.add_argument("--state-file", default=STATE_CACHE_PATH)
    return parser.parse_args(argv)


def live_requested(args: argparse.Namespace) -> bool:
    return bool(
        args.live
        or args.allow_live
        or args.persist_fund_intelligence
        or args.persist_participation
        or args.persist_economic_exposure
        or args.persist_decisions
        or (not args.dry_run)
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if live_requested(args):
        payload: dict[str, Any] = {
            "job_name": JOB_NAME,
            "status": "LIVE_BLOCKED",
            "errors": [REASON_LIVE_UNSAFE],
            "symbols": symbols,
            "dry_run": True,
            "writes": 0,
            "persist_fund_intelligence": False,
            "persist_participation": False,
            "persist_economic_exposure": False,
            "persist_decisions": False,
            "allow_live": False,
        }
        print(json.dumps(payload, indent=2, default=str))
        return 1
    run = run_turkiye_fund_refresh(symbols=symbols, dry_run=True)
    payload = run.to_dict()
    payload["state_file"] = args.state_file
    payload["state_written"] = False
    print(json.dumps(payload, indent=2, default=str))
    return 0 if run.status == "DRY_RUN" and run.writes == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
