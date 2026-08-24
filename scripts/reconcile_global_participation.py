#!/usr/bin/env python3
"""Reconcile global participation from cached SEC Company Facts.

Default is dry-run. --apply writes append-only snapshots, candidate
participation_status sync, and existing queue semantics.

Does not call SEC/FMP/LLM. Does not run Scanner or Research.
"""
from __future__ import annotations

import argparse
import json
import sys
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
from services.global_participation_reconciliation import (
    apply_global_participation_reconciliation,
    plan_global_participation_reconciliation,
)
from services.supabase_admin_client import (
    apply_local_secrets_to_env,
    create_admin_supabase_client,
)


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write snapshots, candidate participation_status, and queue state.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-after", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument(
        "--resume",
        default=None,
        help="JSON state file with last_symbol from a prior run.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(default_sec_company_facts_cache_root()),
    )
    args = parser.parse_args()

    start_after = args.start_after
    resume_path = Path(args.resume) if args.resume else None
    if resume_path is not None and start_after is None:
        start_after = _load_state(resume_path).get("last_symbol")

    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    cache = SecCompanyFactsCache(root=Path(args.cache_dir))
    queue_rows = UniverseExpansionRepository(client).list_all()
    snapshots = ParticipationAssessmentRepository(client).list_latest_by_symbol()
    candidates = CandidateRepository(client).get_all(limit=5000) or []
    candidates_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row
        for row in candidates
        if str(row.get("symbol") or "").strip()
    }
    plan = plan_global_participation_reconciliation(
        queue_rows=queue_rows,
        snapshots_by_symbol=snapshots,
        candidates_by_symbol=candidates_by_symbol,
        cache=cache,
        symbol=args.symbol,
        start_after=start_after,
        limit=args.limit,
    )
    payload = {
        "mode": "apply" if args.apply else "dry_run",
        "planned": len(plan.items),
        "failed": [{"symbol": symbol, "error": error} for symbol, error in plan.failed],
        "pending_excluded": list(plan.pending_excluded),
        "identity_blocked": list(plan.identity_blocked),
        "transition_matrix": {
            key: list(symbols) for key, symbols in plan.transition_matrix.items()
        },
        "sec_provider_calls": 0,
        "participation_snapshot_writes": 0,
        "candidate_writes": 0,
        "queue_writes": 0,
    }
    if not args.apply:
        print(json.dumps(payload, default=str))
        return 0 if not plan.failed else 1

    applied = apply_global_participation_reconciliation(
        plan,
        participation_repo=ParticipationAssessmentRepository(client),
        candidate_repo=CandidateRepository(client),
        queue_repo=UniverseExpansionRepository(client),
        candidates_by_symbol=candidates_by_symbol,
        queue_rows=queue_rows,
    )
    payload["created"] = applied.created
    payload["reused"] = applied.reused
    payload["skipped"] = applied.skipped
    payload["apply_failed"] = [
        {"symbol": symbol, "error": error} for symbol, error in applied.failed
    ]
    payload["candidate_synced"] = applied.candidate_synced
    payload["queue_changed"] = applied.queue_changed
    payload["participation_snapshot_writes"] = len(applied.created)
    payload["candidate_writes"] = len(applied.candidate_synced)
    payload["queue_writes"] = len(applied.queue_changed)
    if resume_path is not None and plan.items:
        resume_path.write_text(
            json.dumps({"last_symbol": plan.items[-1].symbol}, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, default=str))
    return 0 if not applied.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
