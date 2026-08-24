#!/usr/bin/env python3
"""Plan or cache SEC Company Facts for assessed participation equities.

Default is plan-only. --fetch retrieves and caches RAW Company Facts.
It does not apply participation decisions, snapshots, candidates, or queue.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.sec_company_facts_cache import (
    SecCompanyFactsCache,
    default_sec_company_facts_cache_root,
)
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.sec_contact_config import resolve_sec_contact_email
from services.sec_financial_client import SECFinancialClient
from services.sec_participation_evidence_refresh import (
    fetch_sec_evidence,
    plan_sec_evidence_refresh,
)
from services.supabase_admin_client import (
    apply_local_secrets_to_env,
    create_admin_supabase_client,
)


def _build_plan(cache: SecCompanyFactsCache):
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    queue_rows = UniverseExpansionRepository(client).list_all()
    snapshots = ParticipationAssessmentRepository(client).list_latest_by_symbol()
    candidates = CandidateRepository(client).get_all(limit=5000) or []
    candidates_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row
        for row in candidates
        if str(row.get("symbol") or "").strip()
    }
    return plan_sec_evidence_refresh(
        queue_rows=queue_rows,
        snapshots_by_symbol=snapshots,
        candidates_by_symbol=candidates_by_symbol,
        cache=cache,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or cache SEC Company Facts for assessed equities."
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Retrieve missing Company Facts and write the evidence cache only.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(default_sec_company_facts_cache_root()),
        help="Evidence cache directory.",
    )
    args = parser.parse_args()
    cache = SecCompanyFactsCache(root=Path(args.cache_dir))
    plan = _build_plan(cache)
    payload = {
        "mode": "fetch" if args.fetch else "plan",
        "cache_root": str(cache.root),
        **plan.to_dict(),
    }
    if not args.fetch:
        payload["status"] = "plan"
        print(json.dumps(payload, default=str))
        return 0

    email = resolve_sec_contact_email(allow_empty=False)
    sec_client = SECFinancialClient(contact_email=email)
    last_call = 0.0

    def _fetcher(cik: str) -> dict:
        nonlocal last_call
        elapsed = time.monotonic() - last_call
        if last_call and elapsed < 0.15:
            time.sleep(0.15 - elapsed)
        payload = sec_client.company_facts(cik)
        last_call = time.monotonic()
        return payload

    result = fetch_sec_evidence(plan, fetcher=_fetcher, cache=cache)
    payload["status"] = "fetched"
    payload["fetch"] = result.to_dict()
    payload["sec_provider_calls_executed"] = result.sec_calls
    payload["participation_snapshot_writes"] = 0
    payload["candidate_writes"] = 0
    payload["queue_writes"] = 0
    print(json.dumps(payload, default=str))
    return 0 if not result.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
