#!/usr/bin/env python3
"""Evaluate candidate promotion against persisted facts. Never writes."""

from __future__ import annotations

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
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.candidate_promotion_service import evaluate_symbol_promotion
from services.security_master_service import production_security_master
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client

DEFAULT_SYMBOLS = ("ADBE", "ADSK", "BIIB", "MU", "JNJ")


def main() -> int:
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    participation = ParticipationAssessmentRepository(client)
    candidates = CandidateRepository(client)
    queue = UniverseExpansionRepository(client)
    master = production_security_master(client)
    rows = []
    for symbol in DEFAULT_SYMBOLS:
        decision = evaluate_symbol_promotion(
            symbol,
            snapshot=participation.get_latest(symbol),
            resolution=master.resolve_security(symbol),
            queue_row=queue.get_by_symbol(symbol),
            existing_candidates=candidates.list_by_symbol(symbol),
        )
        payload = decision.to_dict()
        payload["written"] = False
        rows.append(payload)
    print(json.dumps({"persist": False, "results": rows}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
