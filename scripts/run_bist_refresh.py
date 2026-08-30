#!/usr/bin/env python3
"""BIST change-driven Facts → SI refresh. Default dry-run. No production writes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.bist_refresh_contract import JOB_NAME, MAX_SYMBOLS_DEFAULT
from services.bist_refresh_orchestrator import run_bist_refresh
from services.bist_thb_history import load_history_cache
from services.wealth_contract import normalize_symbol


def main() -> int:
    parser = argparse.ArgumentParser(description="BIST canonical intelligence refresh")
    parser.add_argument("--symbols", default="ASELS,BIMAS,TUPRS")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--persist-si", action="store_true", default=False)
    parser.add_argument("--allow-live", action="store_true", default=False)
    parser.add_argument("--allow-broad", action="store_true", default=False)
    parser.add_argument("--as-of", default="")
    args = parser.parse_args()
    symbols = [normalize_symbol(item) for item in args.symbols.split(",") if item.strip()]
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    if args.persist_si and not args.allow_live:
        # Persist remains explicit and still requires a repo; this CLI never
        # attaches a production snapshot repository.
        args.persist_si = False
    run = run_bist_refresh(
        symbols,
        dry_run=True,
        persist_si=False,
        allow_live=False,
        allow_broad=args.allow_broad,
        as_of=as_of,
        thb_cache=load_history_cache(),
        max_symbols=MAX_SYMBOLS_DEFAULT,
    )
    payload = run.to_dict()
    payload["cli_persist_si_ignored"] = True
    payload["job_name"] = JOB_NAME
    print(json.dumps(payload, indent=2, default=str))
    return 0 if run.status in {"completed", "partial", "refused"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
