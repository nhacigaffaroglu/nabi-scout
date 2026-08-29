#!/usr/bin/env python3
"""8C controlled SI snapshot persist + local momentum UAT.

Writes only security_intelligence_snapshots after additive migration.
Does not write portfolio/Participation/candidates/Hybrid. No paid providers.
"""
from __future__ import annotations

import json
import sys
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
from scripts.apply_security_intelligence_snapshots_migration import apply_migration
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.local_market_history_service import LocalMarketHistoryService
from services.nabi_intelligence_facade import get_investment_intelligence
from services.security_facts_service import SecurityFactsService
from services.security_identity_service import identity_service_from_security_master
from services.security_intelligence_contract import ENGINE_VERSION
from services.security_intelligence_service import (
    SecurityIntelligenceService,
    participation_from_sources,
)
from services.security_intelligence_snapshot_service import (
    load_previous_for_evaluation,
    save_security_intelligence_snapshot,
)
from services.security_master_service import production_security_master
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.universe_listing_identity import listing_identity

TARGETS = ("CRM", "AAPL", "AVGO", "MRVL", "UPS", "TSLA")


def main() -> int:
    apply_local_secrets_to_env()
    migration = apply_migration()
    raw = create_admin_supabase_client()
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
    repo = SecurityIntelligenceSnapshotRepository(raw)
    facts_service = SecurityFactsService()
    service = SecurityIntelligenceService(facts_service)
    history = LocalMarketHistoryService(raw)
    report: dict[str, Any] = {
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "provider_calls": 0,
        "migration": migration,
        "writes": {
            "schema": 1 if migration.get("applied") else 0,
            "security_intelligence_snapshots": 0,
            "portfolio": 0,
            "transactions": 0,
            "Participation": 0,
            "candidate_approval": 0,
            "Hybrid": 0,
        },
        "holdings": {},
        "crm": {},
        "tsla": {},
        "momentum_audit": {},
    }
    for symbol in TARGETS:
        resolved = master.resolve_security(symbol)
        candidate = candidates.get(symbol)
        qrow = queue.get(symbol) or {}
        snap = snaps.get(symbol) or {}
        momentum = history.compute(symbol)
        built = facts_service.build_detailed(
            symbol,
            candidate=candidate,
            participation_snapshot=snap,
            security_resolution=resolved,
            instrument_type=resolved.instrument_type,
            economic_layer=identity.resolve_economic_layer([symbol]).economic_layer,
            allow_sec_cache_replay=True,
            local_momentum=momentum,
        )
        participation = participation_from_sources(
            queue_or_snapshot={**snap, **qrow},
            candidate=candidate,
            research_allowed=qrow.get("research_allowed"),
        )
        previous = None
        try:
            previous = load_previous_for_evaluation(
                repo,
                symbol,
                as_of=built.facts.as_of,
                facts_version=built.facts.facts_version,
                engine_version=ENGINE_VERSION,
            )
        except Exception:
            previous = None
        view = service.evaluate(built.facts, participation, previous=previous)
        save = save_security_intelligence_snapshot(
            repo,
            view,
            as_of=built.facts.as_of,
            completeness_pct=built.facts.completeness_pct,
            require_sufficient=True,
        )
        if save.saved:
            report["writes"]["security_intelligence_snapshots"] += 1
        replay = save_security_intelligence_snapshot(
            repo,
            view,
            as_of=built.facts.as_of,
            completeness_pct=built.facts.completeness_pct,
            require_sufficient=True,
        )
        reloaded = None
        try:
            reloaded = repo.get_latest(symbol)
        except Exception as exc:
            reloaded = {"error": str(exc)[:160]}
        row = {
            "completeness": built.facts.completeness_pct,
            "si": view.overall_score,
            "status": view.overall_status,
            "state": view.investment_state,
            "participation": view.participation_status,
            "research_allowed": view.research_allowed,
            "change_flags": list(view.change_flags),
            "momentum": {
                name: getattr(built.facts, name)
                for name in (
                    "return_1d",
                    "return_1w",
                    "return_1m",
                    "return_3m",
                    "return_6m",
                    "return_1y",
                    "drawdown",
                    "volatility",
                )
            },
            "local_history": momentum.to_dict(),
            "saved": save.saved,
            "skipped": save.skipped_duplicate,
            "insufficient": save.insufficient,
            "persistence_failed": save.persistence_failed,
            "save_message": save.message,
            "replay_skipped": replay.skipped_duplicate,
            "snapshot_id": (save.row or {}).get("id") or (reloaded or {}).get("id"),
            "engine_version": view.engine_version,
            "facts_version": view.facts_version,
        }
        report["holdings"][symbol] = row
        report["momentum_audit"][symbol] = {
            "observations": momentum.observations,
            "unique_prices": momentum.unique_prices,
            "span_days": momentum.span_days,
            "usable": momentum.usable,
        }
        if symbol == "CRM":
            facade = get_investment_intelligence(raw, "CRM")
            report["crm"] = {
                **row,
                "reload_id": (reloaded or {}).get("id"),
                "facade_live": facade.security_intelligence_overall,
                "facade_persisted": facade.has_persisted_security_intelligence,
                "live_matches_view": facade.security_intelligence_overall == view.overall_score,
            }
        if symbol == "TSLA":
            report["tsla"] = {
                "persisted": save.saved,
                "insufficient": save.insufficient,
                "completeness": built.facts.completeness_pct,
                "cache": False,
            }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
