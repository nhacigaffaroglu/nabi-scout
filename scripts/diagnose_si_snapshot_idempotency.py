#!/usr/bin/env python3
"""Read-only: compare persisted CRM SI snapshot vs freshly built semantic payload."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import ParticipationAssessmentRepository
from repositories.security_intelligence_snapshot_repository import (
    SecurityIntelligenceSnapshotRepository,
)
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.local_market_history_service import LocalMarketHistoryService
from services.security_facts_service import SecurityFactsService
from services.security_identity_service import identity_service_from_security_master
from services.security_intelligence_contract import ENGINE_VERSION
from services.security_intelligence_service import (
    SecurityIntelligenceService,
    participation_from_sources,
)
from services.security_intelligence_snapshot_service import (
    load_previous_for_evaluation,
    payloads_semantically_equal,
    semantic_payload,
    semantic_payload_diffs,
    snapshot_row_from_view,
)
from services.security_master_service import production_security_master
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.universe_listing_identity import listing_identity

CRM_ID = "208751a8-c403-44a1-b8a0-7e8b61ac6d4a"


def _type_name(value: Any) -> str:
    if isinstance(value, Decimal):
        return "Decimal"
    return type(value).__name__


def _walk_diff(left: Any, right: Any, path: str, out: list[dict[str, Any]]) -> None:
    if type(left) is not type(right) and not (
        isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal))
    ):
        out.append(
            {
                "path": path,
                "left": left,
                "right": right,
                "left_type": _type_name(left),
                "right_type": _type_name(right),
            }
        )
        return
    if isinstance(left, dict) and isinstance(right, dict):
        keys = sorted(set(left) | set(right))
        for key in keys:
            _walk_diff(left.get(key), right.get(key), f"{path}.{key}" if path else key, out)
        return
    if isinstance(left, list) and isinstance(right, list):
        if left != right:
            out.append(
                {
                    "path": path,
                    "left": left,
                    "right": right,
                    "left_type": "list",
                    "right_type": "list",
                }
            )
        return
    if left != right:
        out.append(
            {
                "path": path,
                "left": left,
                "right": right,
                "left_type": _type_name(left),
                "right_type": _type_name(right),
            }
        )


def main() -> int:
    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    repo = SecurityIntelligenceSnapshotRepository(raw)
    existing = repo.get_latest("CRM")
    if existing is None:
        print(json.dumps({"error": "no persisted CRM snapshot"}, indent=2))
        return 1
    master = production_security_master(raw)
    identity = identity_service_from_security_master(master)
    candidates = {
        listing_identity(row.get("symbol")): row
        for row in (CandidateRepository(raw).get_all(limit=5000) or [])
    }
    queue = {
        listing_identity(row.get("symbol")): row
        for row in UniverseExpansionRepository(raw).list_all()
    }
    snaps = ParticipationAssessmentRepository(raw).list_latest_by_symbol()
    candidate = candidates.get("CRM")
    qrow = queue.get("CRM") or {}
    snap = snaps.get("CRM") or {}
    resolved = master.resolve_security("CRM")
    built = SecurityFactsService().build_detailed(
        "CRM",
        candidate=candidate,
        participation_snapshot=snap,
        security_resolution=resolved,
        instrument_type=resolved.instrument_type,
        economic_layer=identity.resolve_economic_layer(["CRM"]).economic_layer,
        allow_sec_cache_replay=True,
        local_momentum=LocalMarketHistoryService(raw).compute("CRM"),
    )
    previous = load_previous_for_evaluation(
        repo,
        "CRM",
        as_of=built.facts.as_of,
        facts_version=built.facts.facts_version,
        engine_version=ENGINE_VERSION,
    )
    view = SecurityIntelligenceService().evaluate(
        built.facts,
        participation_from_sources(
            queue_or_snapshot={**snap, **qrow},
            candidate=candidate,
            research_allowed=qrow.get("research_allowed"),
        ),
        previous=previous,
    )
    current = snapshot_row_from_view(view, as_of=built.facts.as_of)
    left = semantic_payload(existing)
    right = semantic_payload(current)
    diffs: list[dict[str, Any]] = []
    _walk_diff(left, right, "", diffs)
    raw_diffs: list[dict[str, Any]] = []
    _walk_diff(
        {k: existing.get(k) for k in current if k not in {"created_at", "updated_at", "id"}},
        current,
        "",
        raw_diffs,
    )
    report = {
        "persisted_id": existing.get("id"),
        "expected_id": CRM_ID,
        "persisted_as_of": existing.get("as_of"),
        "persisted_as_of_type": _type_name(existing.get("as_of")),
        "current_as_of": current.get("as_of"),
        "current_as_of_type": _type_name(current.get("as_of")),
        "persisted_overall": existing.get("overall_score"),
        "persisted_overall_type": _type_name(existing.get("overall_score")),
        "current_overall": current.get("overall_score"),
        "current_overall_type": _type_name(current.get("overall_score")),
        "payloads_semantically_equal": payloads_semantically_equal(existing, current),
        "canonical_field_diffs": [
            {"field": field, "left": left_val, "right": right_val}
            for field, left_val, right_val in semantic_payload_diffs(existing, current)
        ],
        "semantic_diff_count": len(diffs),
        "semantic_diffs": diffs,
        "raw_diff_count": len(raw_diffs),
        "raw_diffs": raw_diffs,
        "persisted_keys": sorted(existing.keys()),
        "current_keys": sorted(current.keys()),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
