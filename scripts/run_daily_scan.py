#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.scan_universe import PARTICIPATION_DEFAULTS
from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.watchlist_repository import WatchlistRepository
from services.fmp_client import FMPClient, FMPError
from services.free_universe_client import FreeUniverseClient
from services.scan_runner_service import ScanRunResult, run_scan
from services.scan_universe_service import build_daily_universe_rows, scheduled_universe_name
from services.scheduled_scan_service import evaluate_scheduled_run, stale_running_cutoff
from services.sec_financial_client import SECFinancialClient
from services.supabase_client_factory import SupabaseConfigError, create_supabase_client


def _load_sec_lookup(contact_email: str) -> dict:
    if not contact_email.strip():
        return {}
    rows = FreeUniverseClient(contact_email=contact_email.strip()).get_sec_companies()
    return {
        str(row.get("symbol") or "").strip().upper(): row
        for row in rows
        if row.get("symbol")
    }


def _print_summary(result: ScanRunResult) -> None:
    print(f"Daily scan {result.universe_name.split('·')[-1].strip()}")
    print(f"Universe: {result.total_symbols} symbols")
    if result.skipped:
        print(result.skip_reason or "Skipped.")
        return
    print(f"Status: {result.status}")
    print(f"Scanned: {result.scanned}")
    print(f"Updated: {result.updated}")
    print(f"Errors: {result.errors}")
    print(f"Meaningful changes: {len(result.meaningful_changes)}")


def main() -> int:
    try:
        client = create_supabase_client()
    except SupabaseConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    sec_email = (os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
    if not sec_email:
        print("SEC_CONTACT_EMAIL environment variable is required.", file=sys.stderr)
        return 1

    try:
        fmp_client = FMPClient.from_env()
    except FMPError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    scan_repo = ScanRepository(client)
    candidate_repo = CandidateRepository(client)
    watchlist_repo = WatchlistRepository(client)

    stale_count = scan_repo.mark_stale_running_failed(stale_running_cutoff())
    if stale_count:
        print(f"Marked {stale_count} stale RUNNING scan(s) as FAILED.")

    should_run, skip_reason, _existing = evaluate_scheduled_run(scan_repo)
    universe_name = scheduled_universe_name()
    if not should_run:
        skipped = ScanRunResult(
            run_id="",
            source="scheduled",
            universe_name=universe_name,
            total_symbols=0,
            scanned=0,
            updated=0,
            strong=0,
            errors=0,
            excluded=0,
            symbols_without_previous=0,
            skipped=True,
            skip_reason=skip_reason,
            status="SKIPPED",
        )
        _print_summary(skipped)
        return 0

    sec_lookup = _load_sec_lookup(sec_email)
    watchlist_entries = watchlist_repo.list_active()
    symbols = build_daily_universe_rows(
        sec_lookup=sec_lookup,
        watchlist_entries=watchlist_entries,
    )
    if not symbols:
        print("Daily universe resolved to zero symbols.", file=sys.stderr)
        return 1

    sec_client = SECFinancialClient(contact_email=sec_email)
    result = run_scan(
        symbols=symbols,
        universe_name=universe_name,
        source="scheduled",
        scan_repo=scan_repo,
        candidate_repo=candidate_repo,
        fmp_client=fmp_client,
        sec_client=sec_client,
        participation_defaults=PARTICIPATION_DEFAULTS,
    )
    _print_summary(result)
    return 0 if result.status == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
