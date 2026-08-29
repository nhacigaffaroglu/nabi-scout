#!/usr/bin/env python3
"""8D fixture-only Signal Intelligence UAT.

No provider calls. No production writes. No Hybrid. No Participation mutation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.signal_intelligence_repository import InMemorySignalIntelligenceRepository
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN_DEGIL
from services.security_intelligence_contract import SecurityFacts, SecurityParticipationContext
from services.security_intelligence_engine import evaluate_security_intelligence
from services.signal_intelligence_fixtures import (
    fixture_conflict_negative,
    fixture_conflict_positive,
    fixture_material_negative,
    fixture_material_positive,
    fixture_merger_newswire,
    fixture_merger_sec,
    fixture_sec_8k_verified,
    fixture_social_only_claim,
)
from services.signal_intelligence_service import SignalIntelligenceService


def main() -> int:
    service = SignalIntelligenceService(InMemorySignalIntelligenceRepository())
    sec = service.ingest(fixture_sec_8k_verified())
    sec_replay = service.ingest(fixture_sec_8k_verified())
    social = service.ingest(fixture_social_only_claim())
    merger_sec = service.ingest(fixture_merger_sec())
    merger_wire = service.ingest(fixture_merger_newswire())
    conflict = SignalIntelligenceService(InMemorySignalIntelligenceRepository())
    conflict.ingest(fixture_conflict_positive())
    conflicted = conflict.ingest(fixture_conflict_negative())
    negative = SignalIntelligenceService(InMemorySignalIntelligenceRepository())
    before = evaluate_security_intelligence(
        SecurityFacts(symbol="CRM", roic=18, roe=20, operating_margin=18, pe=30),
        SecurityParticipationContext(status="Uygun", research_allowed=True),
    )
    negative.ingest(fixture_material_negative())
    after_negative = negative.attach_to_view(before)
    positive = SignalIntelligenceService(InMemorySignalIntelligenceRepository())
    blocked = evaluate_security_intelligence(
        SecurityFacts(symbol="AAPL", roic=18, roe=20, operating_margin=18, pe=30),
        SecurityParticipationContext(
            status=PARTICIPATION_STATUS_UYGUN_DEGIL,
            research_allowed=False,
        ),
    )
    pos = positive.ingest(fixture_material_positive())
    after_positive = positive.attach_to_view(blocked)
    report = {
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "provider_calls": 0,
        "production_writes": 0,
        "sec_verified": {
            "event_id": sec.event.event_id,
            "authority": sec.event.source_authority,
            "verification": sec.event.verification_status,
            "replay_skipped": sec_replay.replay_skipped,
            "persisted": sec.persisted,
        },
        "social_only": {
            "verification": social.event.verification_status,
            "authority": social.evidence.source_authority,
            "event_type": social.event.event_type,
        },
        "multi_source": {
            "same_event": merger_sec.event.event_id == merger_wire.event.event_id,
            "evidence_count": len(merger_wire.event.evidence_ids),
        },
        "conflict": {
            "verification": conflicted.event.verification_status,
            "direction": conflicted.event.direction,
        },
        "negative_material": {
            "materiality": after_negative.signal_context.material_signals[0].materiality,
            "direction": after_negative.signal_context.material_signals[0].direction,
            "si_score_unchanged": after_negative.overall_score == before.overall_score,
        },
        "positive_material": {
            "direction": pos.event.direction,
            "investable": after_positive.investable,
            "investment_state": after_positive.investment_state,
        },
        "participation_firewall": {
            "status": after_positive.participation_status,
            "investable": after_positive.investable,
            "state": after_positive.investment_state,
        },
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
