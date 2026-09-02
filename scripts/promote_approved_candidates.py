#!/usr/bin/env python3
"""Bounded production promotion for the four 8D.5B-approved symbols.

Re-evaluates every gate through CandidatePromotionService, then writes only
PROMOTION_ELIGIBLE symbols via CandidateRepository.create. No other writers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.candidate_promotion_service import promote_if_eligible
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.research_workflow_service import normalize_research_status
from services.security_master_service import production_security_master
from services.signal_ingestion_sources import load_signal_ingestion_inputs
from services.signal_ingestion_universe import (
    ACTIVE_RESEARCH_STATUSES,
    build_signal_ingestion_universe,
)
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client

APPROVED_SYMBOLS = ("ADBE", "ADSK", "BIIB", "MU")


def _count(client, table: str) -> int:
    response = client.table(table).select("id", count="exact").limit(1).execute()
    return int(getattr(response, "count", None) or 0)


def _fingerprint_row(row: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if not row:
        return None
    return {key: row.get(key) for key in keys}


def _load_facts(symbol: str, *, participation, master, queue, candidates) -> dict[str, Any]:
    return {
        "snapshot": participation.get_latest(symbol),
        "resolution": master.resolve_security(symbol),
        "queue_row": queue.get_by_symbol(symbol),
        "existing_candidates": candidates.list_by_symbol(symbol),
    }


def _promote(symbol: str, *, facts, candidates, persist: bool):
    return promote_if_eligible(
        symbol,
        snapshot=facts["snapshot"],
        resolution=facts["resolution"],
        queue_row=facts["queue_row"],
        existing_candidates=facts["existing_candidates"],
        candidate_repo=candidates,
        persist=persist,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="8D.5B approved candidate promotion")
    parser.add_argument(
        "--persist-production",
        action="store_true",
        help="Write investment_candidates for still-eligible approved symbols only",
    )
    args = parser.parse_args()

    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    participation = ParticipationAssessmentRepository(client)
    candidates = CandidateRepository(client)
    queue = UniverseExpansionRepository(client)
    master = production_security_master(client)

    before_count = len(candidates.get_all(limit=5000) or [])
    boundary_before = {
        "investment_candidates": before_count,
        "participation_assessment_snapshots": _count(client, "participation_assessment_snapshots"),
        "universe_expansion_queue": _count(client, "universe_expansion_queue"),
        "security_master": _count(client, "security_master"),
        "security_intelligence_snapshots": _count(client, "security_intelligence_snapshots"),
        "signal_events": _count(client, "signal_events"),
        "signal_evidence": _count(client, "signal_evidence"),
    }
    participation_before = {
        symbol: _fingerprint_row(
            participation.get_latest(symbol),
            ("id", "symbol", "status", "assessed_at", "source"),
        )
        for symbol in APPROVED_SYMBOLS
    }
    queue_before = {
        symbol: _fingerprint_row(
            queue.get_by_symbol(symbol),
            ("id", "symbol", "status", "source_universe", "updated_at"),
        )
        for symbol in APPROVED_SYMBOLS
    }

    prewrite = []
    writes = []
    for symbol in APPROVED_SYMBOLS:
        facts = _load_facts(
            symbol,
            participation=participation,
            master=master,
            queue=queue,
            candidates=candidates,
        )
        preview = _promote(symbol, facts=facts, candidates=candidates, persist=False)
        decision = preview.decision
        prewrite.append(
            {
                "symbol": symbol,
                "participation_status": decision.participation_status,
                "identity_status": decision.identity_status,
                "instrument_type": decision.instrument_type,
                "evidence": [item.to_dict() for item in decision.evidence],
                "candidate_exists": decision.candidate_exists,
                "eligible": decision.eligible,
                "reason_codes": list(decision.reason_codes),
            }
        )
        if not args.persist_production:
            writes.append({"symbol": symbol, "action": "evaluate_only", "written": False})
            continue
        if not decision.eligible:
            writes.append(
                {
                    "symbol": symbol,
                    "action": "skipped",
                    "written": False,
                    "reason_codes": list(decision.reason_codes),
                }
            )
            continue
        fresh = _load_facts(
            symbol,
            participation=participation,
            master=master,
            queue=queue,
            candidates=candidates,
        )
        result = _promote(symbol, facts=fresh, candidates=candidates, persist=True)
        created = result.payload if result.written else None
        writes.append(
            {
                "symbol": symbol,
                "action": "inserted" if result.written else "skipped",
                "written": result.written,
                "reason_codes": list(result.decision.reason_codes),
                "candidate_id": (created or {}).get("id"),
                "research_status": (created or {}).get("research_status"),
                "data_source": (created or {}).get("data_source"),
            }
        )

    post_rows = {symbol: candidates.list_by_symbol(symbol) for symbol in APPROVED_SYMBOLS}
    after_rows = candidates.get_all(limit=5000) or []
    after_count = len(after_rows)
    active = [
        row
        for row in after_rows
        if normalize_research_status(row.get("research_status")) in ACTIVE_RESEARCH_STATUSES
    ]
    inputs = load_signal_ingestion_inputs(client)
    universe = build_signal_ingestion_universe(
        holdings=inputs["holdings"],
        candidates=inputs["candidates"],
        participation_by_symbol=inputs["participation_by_symbol"],
    )

    replay = []
    replay_writes = 0
    timestamps_before = {
        symbol: [
            {"id": row.get("id"), "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}
            for row in post_rows[symbol]
        ]
        for symbol in APPROVED_SYMBOLS
    }
    if args.persist_production:
        for symbol in APPROVED_SYMBOLS:
            facts = _load_facts(
                symbol,
                participation=participation,
                master=master,
                queue=queue,
                candidates=candidates,
            )
            result = _promote(symbol, facts=facts, candidates=candidates, persist=True)
            if result.written:
                replay_writes += 1
            replay.append(
                {
                    "symbol": symbol,
                    "written": result.written,
                    "reason_codes": list(result.decision.reason_codes),
                }
            )
    timestamps_after = {
        symbol: [
            {"id": row.get("id"), "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}
            for row in candidates.list_by_symbol(symbol)
        ]
        for symbol in APPROVED_SYMBOLS
    }

    participation_after = {
        symbol: _fingerprint_row(
            participation.get_latest(symbol),
            ("id", "symbol", "status", "assessed_at", "source"),
        )
        for symbol in APPROVED_SYMBOLS
    }
    queue_after = {
        symbol: _fingerprint_row(
            queue.get_by_symbol(symbol),
            ("id", "symbol", "status", "source_universe", "updated_at"),
        )
        for symbol in APPROVED_SYMBOLS
    }
    boundary_after = {
        "investment_candidates": after_count,
        "participation_assessment_snapshots": _count(client, "participation_assessment_snapshots"),
        "universe_expansion_queue": _count(client, "universe_expansion_queue"),
        "security_master": _count(client, "security_master"),
        "security_intelligence_snapshots": _count(client, "security_intelligence_snapshots"),
        "signal_events": _count(client, "signal_events"),
        "signal_evidence": _count(client, "signal_evidence"),
    }

    print(
        json.dumps(
            {
                "persist": bool(args.persist_production),
                "approved_symbols": list(APPROVED_SYMBOLS),
                "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
                "hybrid_env": os.environ.get("NABI_ENABLE_HYBRID", ""),
                "prewrite": prewrite,
                "writes": writes,
                "postwrite": [
                    {
                        "symbol": symbol,
                        "candidate_exists": bool(post_rows[symbol]),
                        "id": (post_rows[symbol][0].get("id") if post_rows[symbol] else None),
                        "research_status": (
                            post_rows[symbol][0].get("research_status") if post_rows[symbol] else None
                        ),
                        "data_source": (
                            post_rows[symbol][0].get("data_source") if post_rows[symbol] else None
                        ),
                        "decision": post_rows[symbol][0].get("decision") if post_rows[symbol] else None,
                        "conviction_score": (
                            post_rows[symbol][0].get("conviction_score") if post_rows[symbol] else None
                        ),
                    }
                    for symbol in APPROVED_SYMBOLS
                ],
                "candidate_count_before": before_count,
                "inserted": sum(1 for row in writes if row.get("action") == "inserted"),
                "candidate_count_after": after_count,
                "active_research_count": len(active),
                "active_research_symbols": sorted(
                    str(row.get("symbol") or "").upper() for row in active
                ),
                "sec_monitoring_count": len(universe.eligible),
                "sec_monitoring_symbols": list(universe.eligible),
                "sec_excluded_promoted": [
                    item
                    for item in universe.excluded
                    if item[0] in APPROVED_SYMBOLS
                ],
                "replay": replay,
                "replay_writes": replay_writes,
                "timestamp_churn": timestamps_before != timestamps_after,
                "timestamps_before": timestamps_before,
                "timestamps_after": timestamps_after,
                "participation_unchanged": participation_before == participation_after,
                "queue_unchanged": queue_before == queue_after,
                "boundary_before": boundary_before,
                "boundary_after": boundary_after,
                "provider_calls": 0,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
