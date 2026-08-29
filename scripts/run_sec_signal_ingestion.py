#!/usr/bin/env python3
"""Bounded SEC 8-K Signal Intelligence ingest entry point.

Daily hook: scripts/run_signal_ingestion.py after scripts/run_daily_scan.py.
Schedule is not activated. Feature flag default OFF.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.signal_intelligence_repository import (
    InMemorySignalIntelligenceRepository,
    SignalIntelligenceRepository,
    verify_signal_intelligence_schema,
)
from services.sec_contact_config import SECContactConfigError, resolve_sec_contact_email
from services.signal_sec_ingest_service import (
    live_sec_submissions_loader,
    run_sec_signal_ingestion,
)


FUTURE_ORCHESTRATION_HOOK = (
    "scripts/run_signal_ingestion.py after scripts/run_daily_scan.py "
    "in .github/workflows/daily_scan.yml. Feature flag default OFF. "
    "Schedule is not activated."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded SEC 8-K signal ingestion")
    parser.add_argument("--symbols", default="CRM", help="Comma-separated symbols")
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--max-filings", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument(
        "--persist-production",
        action="store_true",
        help="Write to signal_events only when schema is verified",
    )
    args = parser.parse_args()
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    repo = InMemorySignalIntelligenceRepository()
    schema_ok = False
    schema_message = "production persist not requested"
    if args.persist_production:
        try:
            from services.supabase_admin_client import (
                apply_local_secrets_to_env,
                create_admin_supabase_client,
            )

            apply_local_secrets_to_env()
            client = create_admin_supabase_client()
            schema_ok, schema_message = verify_signal_intelligence_schema(client)
            if schema_ok:
                repo = SignalIntelligenceRepository(client)
            else:
                print(
                    "STOP: signal schema not verified. "
                    "Run database/migration_signal_intelligence.sql in Supabase SQL Editor.",
                    file=sys.stderr,
                )
                print(schema_message, file=sys.stderr)
                return 2
        except Exception as exc:
            print(f"STOP: cannot verify signal schema ({exc}).", file=sys.stderr)
            return 2
    try:
        email = resolve_sec_contact_email(allow_empty=False)
    except SECContactConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    report = run_sec_signal_ingestion(
        symbols,
        repo=repo,
        submissions_loader=live_sec_submissions_loader(contact_email=email),
        cik_by_symbol={"CRM": "1108524"},
        lookback_days=args.lookback_days,
        max_filings_per_symbol=args.max_filings,
        as_of=date.today(),
        sleep_seconds=max(0.0, args.sleep_seconds),
    )
    payload = report.to_dict()
    payload["schema_verified"] = schema_ok
    payload["schema_message"] = schema_message
    payload["future_orchestration_hook"] = FUTURE_ORCHESTRATION_HOOK
    payload["schedule_activated"] = False
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
