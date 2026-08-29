#!/usr/bin/env python3
"""8D.2 SEC 8-K signal UAT.

Fixture/cache path first. Live SEC only when existing contact + client work.
Never writes fabricated fixtures to production signal tables.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.signal_intelligence_repository import (
    InMemorySignalIntelligenceRepository,
    verify_signal_intelligence_schema,
)
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN_DEGIL
from services.sec_contact_config import resolve_sec_contact_email
from services.security_intelligence_contract import SecurityFacts, SecurityParticipationContext
from services.security_intelligence_engine import evaluate_security_intelligence
from services.signal_intelligence_fixtures import fixture_material_positive
from services.signal_intelligence_service import SignalIntelligenceService
from services.signal_sec_ingest_fixtures import (
    fixture_crm_multi_item_8k,
    fixture_crm_single_item_8k,
)
from services.signal_sec_ingest_service import (
    live_sec_submissions_loader,
    run_sec_signal_ingestion,
)


def _summarize(result) -> dict:
    events = []
    for item in result.ingest_results:
        events.append(
            {
                "event_id": item.event.event_id,
                "evidence_id": item.evidence.evidence_id,
                "authoritative_event_id": item.event.authoritative_event_id,
                "logical_event_key": item.event.logical_event_key,
                "event_type": item.event.event_type,
                "event_subtype": item.event.event_subtype,
                "verification": item.event.verification_status,
                "materiality": item.event.materiality,
                "direction": item.event.direction,
            }
        )
    filing = result.discovered[0].to_dict() if result.discovered else {}
    return {
        "symbol": result.symbol,
        "cik": result.cik,
        "form": filing.get("form"),
        "accession": filing.get("accession"),
        "filing_date": filing.get("filing_date"),
        "items": filing.get("items"),
        "events": events,
        "event_writes": result.event_writes,
        "evidence_writes": result.evidence_writes,
        "error": result.error,
    }


def _probe_schema() -> tuple[bool, str]:
    try:
        from services.supabase_admin_client import (
            apply_local_secrets_to_env,
            create_admin_supabase_client,
        )

        apply_local_secrets_to_env()
        client = create_admin_supabase_client()
        return verify_signal_intelligence_schema(client)
    except Exception as exc:
        return False, str(exc)[:240]


def main() -> int:
    repo = InMemorySignalIntelligenceRepository()
    first = run_sec_signal_ingestion(
        ["CRM"],
        repo=repo,
        submissions_by_symbol={"CRM": fixture_crm_single_item_8k()},
        cik_by_symbol={"CRM": "1108524"},
        lookback_days=90,
        as_of=date(2026, 3, 20),
    )
    replay = run_sec_signal_ingestion(
        ["CRM"],
        repo=repo,
        submissions_by_symbol={"CRM": fixture_crm_single_item_8k()},
        cik_by_symbol={"CRM": "1108524"},
        lookback_days=90,
        as_of=date(2026, 3, 20),
    )
    multi_repo = InMemorySignalIntelligenceRepository()
    multi = run_sec_signal_ingestion(
        ["CRM"],
        repo=multi_repo,
        submissions_by_symbol={"CRM": fixture_crm_multi_item_8k()},
        cik_by_symbol={"CRM": "1108524"},
        lookback_days=90,
        as_of=date(2026, 7, 2),
    )
    multi_replay = run_sec_signal_ingestion(
        ["CRM"],
        repo=multi_repo,
        submissions_by_symbol={"CRM": fixture_crm_multi_item_8k()},
        cik_by_symbol={"CRM": "1108524"},
        lookback_days=90,
        as_of=date(2026, 7, 2),
    )
    service = SignalIntelligenceService(repo)
    facts = SecurityFacts(symbol="CRM", roic=18, roe=20, operating_margin=18, pe=30)
    before = evaluate_security_intelligence(
        facts,
        SecurityParticipationContext(status="Uygun", research_allowed=True),
    )
    after = service.attach_to_view(before)
    blocked = evaluate_security_intelligence(
        SecurityFacts(symbol="AAPL", roic=18, roe=20, operating_margin=18, pe=30),
        SecurityParticipationContext(
            status=PARTICIPATION_STATUS_UYGUN_DEGIL,
            research_allowed=False,
        ),
    )
    firewall_service = SignalIntelligenceService(InMemorySignalIntelligenceRepository())
    firewall_service.ingest(fixture_material_positive())
    blocked_after = firewall_service.attach_to_view(blocked)
    schema_ok, schema_message = _probe_schema()
    live: dict = {"mode": "skipped", "reason": "SEC contact not configured"}
    try:
        email = resolve_sec_contact_email(allow_empty=False)
        live_repo = InMemorySignalIntelligenceRepository()
        live_first = run_sec_signal_ingestion(
            ["CRM"],
            repo=live_repo,
            submissions_loader=live_sec_submissions_loader(contact_email=email),
            cik_by_symbol={"CRM": "1108524"},
            lookback_days=90,
            max_filings_per_symbol=5,
            sleep_seconds=0.2,
        )
        live_replay = run_sec_signal_ingestion(
            ["CRM"],
            repo=live_repo,
            submissions_loader=live_sec_submissions_loader(contact_email=email),
            cik_by_symbol={"CRM": "1108524"},
            lookback_days=90,
            max_filings_per_symbol=5,
            sleep_seconds=0.2,
        )
        live = {
            "mode": "live_sec_memory",
            "schema_verified": schema_ok,
            "first": live_first.to_dict(),
            "replay_event_writes": live_replay.event_writes,
            "replay_evidence_writes": live_replay.evidence_writes,
            "sample": _summarize(live_first.results[0]) if live_first.results else {},
            "production_writes": 0,
            "note": (
                "Live filings normalized in memory only. "
                "Production persist requires verified schema and explicit --persist-production."
            ),
        }
    except Exception as exc:
        live = {
            "mode": "blocked" if schema_ok else "partial",
            "reason": str(exc)[:240],
            "schema_verified": schema_ok,
            "production_writes": 0,
        }
    context = service.context_for("CRM")
    report = {
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "mode": "cached_fixture",
        "schema_verified": schema_ok,
        "schema_message": schema_message,
        "manual_action_required": (
            None
            if schema_ok
            else "Run database/migration_signal_intelligence.sql in Supabase SQL Editor."
        ),
        "single_item": _summarize(first.results[0]),
        "first_run_event_writes": first.event_writes,
        "first_run_evidence_writes": first.evidence_writes,
        "replay_event_writes": replay.event_writes,
        "replay_evidence_writes": replay.evidence_writes,
        "multi_item": _summarize(multi.results[0]),
        "multi_first_event_writes": multi.event_writes,
        "multi_replay_event_writes": multi_replay.event_writes,
        "multi_replay_evidence_writes": multi_replay.evidence_writes,
        "signal_context": {
            "recent": len(context.recent_signals),
            "material": len(context.material_signals),
            "positive": len(context.positive_signals),
            "negative": len(context.negative_signals),
            "unverified": len(context.unverified_signals),
            "risk_flags": list(context.signal_risk_flags),
            "latest_material_event_at": context.latest_material_event_at,
        },
        "security_intelligence": {
            "overall_before": before.overall_score,
            "overall_after": after.overall_score,
            "quality_before": before.quality.score,
            "quality_after": after.quality.score,
            "blocked_investable": blocked_after.investable,
            "blocked_state": blocked_after.investment_state,
        },
        "live": live,
        "production_writes": {
            "signal_events": 0,
            "signal_evidence": 0,
            "portfolio": 0,
            "transactions": 0,
            "participation": 0,
            "candidates": 0,
            "hybrid": 0,
        },
        "future_orchestration_hook": (
            "scripts/run_sec_signal_ingestion.py via existing daily orchestration; "
            "schedule not activated"
        ),
        "schedule_activated": False,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
