#!/usr/bin/env python3
"""Signal ingestion stage for existing daily orchestration.

Adapters: SEC (live), KAP (credential-blocked, not called).
Default: enable_sec_signal_ingestion OFF. No schedule of its own.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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
from services.signal_ingestion_orchestration import run_signal_ingestion_stage
from services.signal_ingestion_policy import (
    ADAPTER_KAP,
    ADAPTER_SEC,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_FILINGS_PER_SYMBOL,
    DEFAULT_MAX_SYMBOLS_PER_RUN,
    DEFAULT_SLEEP_SECONDS,
    resolve_sec_signal_ingestion_enabled,
)
from services.signal_ingestion_sources import load_signal_ingestion_inputs
from services.signal_sec_ingest_service import live_sec_submissions_loader


ORCHESTRATION_HOOK = (
    "scripts/run_signal_ingestion.py after scripts/run_daily_scan.py "
    "in .github/workflows/daily_scan.yml. Feature flag default OFF. "
    "Schedule is not activated."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded Signal ingestion stage")
    parser.add_argument("--adapter", default=ADAPTER_SEC, choices=(ADAPTER_SEC, ADAPTER_KAP))
    parser.add_argument("--enable", action="store_true", help="Explicitly enable this run")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--max-filings", type=int, default=DEFAULT_MAX_FILINGS_PER_SYMBOL)
    parser.add_argument("--max-symbols", type=int, default=DEFAULT_MAX_SYMBOLS_PER_RUN)
    parser.add_argument("--sleep-seconds", type=float, default=DEFAULT_SLEEP_SECONDS)
    parser.add_argument(
        "--persist-production",
        action="store_true",
        help="Write signal_events/signal_evidence when schema is verified",
    )
    args = parser.parse_args()
    enabled = resolve_sec_signal_ingestion_enabled(True if args.enable else None)
    if not enabled:
        print(
            json.dumps(
                {
                    "enabled": False,
                    "adapter": args.adapter,
                    "message": "enable_sec_signal_ingestion is OFF; stage skipped.",
                    "orchestration_hook": ORCHESTRATION_HOOK,
                    "schedule_activated": False,
                    "sec_submissions_calls": 0,
                    "event_writes": 0,
                    "evidence_writes": 0,
                },
                indent=2,
            )
        )
        return 0

    from services.supabase_admin_client import (
        apply_local_secrets_to_env,
        create_admin_supabase_client,
    )

    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    repo = InMemorySignalIntelligenceRepository()
    if args.persist_production:
        schema_ok, schema_message = verify_signal_intelligence_schema(client)
        if not schema_ok:
            print(
                "STOP: signal schema not verified. "
                "Run database/migration_signal_intelligence.sql in Supabase SQL Editor.",
                file=sys.stderr,
            )
            print(schema_message, file=sys.stderr)
            return 2
        repo = SignalIntelligenceRepository(client)
    inputs = load_signal_ingestion_inputs(client)
    sec_lookup = {}
    loader = None
    if args.adapter == ADAPTER_SEC:
        try:
            email = resolve_sec_contact_email(allow_empty=False)
        except SECContactConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        loader = live_sec_submissions_loader(contact_email=email)
        from services.free_universe_client import FreeUniverseClient

        try:
            rows = FreeUniverseClient(contact_email=email).get_sec_companies()
            sec_lookup = {
                str(row.get("symbol") or "").strip().upper(): row
                for row in rows
                if row.get("symbol")
            }
        except Exception:
            sec_lookup = {}
    report = run_signal_ingestion_stage(
        holdings=inputs["holdings"],
        candidates=inputs["candidates"],
        participation_by_symbol=inputs["participation_by_symbol"],
        adapter=args.adapter,
        enable_sec_signal_ingestion=True,
        repo=repo,
        submissions_loader=loader,
        sec_ticker_lookup=sec_lookup,
        lookback_days=args.lookback_days,
        max_filings_per_symbol=args.max_filings,
        max_symbols_per_run=args.max_symbols,
        sleep_seconds=max(0.0, args.sleep_seconds),
    )
    payload = report.to_dict()
    payload["orchestration_hook"] = ORCHESTRATION_HOOK
    payload["persist_production"] = bool(args.persist_production)
    payload["hybrid_env"] = os.environ.get("NABI_ENABLE_HYBRID", "")
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
