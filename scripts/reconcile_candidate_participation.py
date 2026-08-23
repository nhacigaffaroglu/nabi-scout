#!/usr/bin/env python3
"""Reconcile stale candidate participation_status to authoritative snapshots.

Default is dry-run. --apply writes participation_status only for the
exact allowlisted symbol/id transitions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from services.participation_authority import resolve_authoritative_participation
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client

EXPECTED_TRANSITIONS = {
    "AAPL": {
        "from": "Kontrol Et",
        "to": "Uygun Değil",
        "candidate_id": "ab360732-a848-4f8a-8f83-a1cd65ea43d9",
    },
    "CRM": {
        "from": "Kontrol Et",
        "to": "Uygun",
        "candidate_id": "4fc2fa39-5536-4422-a207-844214739457",
    },
    "JNJ": {
        "from": "Kontrol Et",
        "to": "Uygun",
        "candidate_id": "52525a8f-dacf-40b9-bce4-454067f0d0b4",
    },
}


def _research_allowed(status: str) -> bool:
    return status == PARTICIPATION_STATUS_UYGUN


def planned_changes(client) -> list[dict]:
    candidates = CandidateRepository(client).get_all(limit=2000) or []
    snapshots = ParticipationAssessmentRepository(client).list_latest_by_symbol()
    changes: list[dict] = []
    for row in candidates:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        current = str(row.get("participation_status") or "").strip()
        snapshot = snapshots.get(symbol)
        authority = resolve_authoritative_participation(
            symbol,
            candidate=row,
            snapshot=snapshot,
        )
        if not authority.status or authority.status == current:
            continue
        changes.append(
            {
                "symbol": symbol,
                "candidate_id": row.get("id"),
                "from": current or "MISSING",
                "to": authority.status,
                "source": authority.source,
                "snapshot_id": (snapshot or {}).get("id"),
                "assessed_at": (snapshot or {}).get("assessed_at"),
                "research_allowed_before": _research_allowed(current),
                "research_allowed_after": authority.research_allowed,
                "reason": (
                    "authoritative snapshot overrides stale candidate participation_status"
                ),
            }
        )
    return changes


def _matches_allowlist(changes: list[dict]) -> bool:
    if len(changes) != len(EXPECTED_TRANSITIONS):
        return False
    seen = set()
    for item in changes:
        expected = EXPECTED_TRANSITIONS.get(item["symbol"])
        if expected is None:
            return False
        if (
            item["from"] != expected["from"]
            or item["to"] != expected["to"]
            or str(item["candidate_id"]) != expected["candidate_id"]
        ):
            return False
        seen.add(item["symbol"])
    return seen == set(EXPECTED_TRANSITIONS)


def apply_changes(client, changes: list[dict]) -> int:
    repo = CandidateRepository(client)
    written = 0
    for item in changes:
        repo.update(
            item["candidate_id"],
            {"participation_status": item["to"]},
        )
        written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write allowlisted candidate participation_status only.",
    )
    args = parser.parse_args()
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    changes = planned_changes(client)
    print(f"planned_changes={len(changes)}")
    for item in changes:
        print(
            f"{item['symbol']}: {item['from']} -> {item['to']} "
            f"id={item['candidate_id']} snapshot={item['snapshot_id']} "
            f"assessed_at={item['assessed_at']} "
            f"research_allowed {item['research_allowed_before']} -> {item['research_allowed_after']}"
        )
    unexpected = [
        item["symbol"]
        for item in changes
        if item["symbol"] not in EXPECTED_TRANSITIONS
    ]
    if unexpected or not _matches_allowlist(changes):
        print("STOP: planned changes do not match the exact 3-row allowlist.", file=sys.stderr)
        return 3
    if not args.apply:
        return 0
    written = apply_changes(client, changes)
    print(f"applied={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
