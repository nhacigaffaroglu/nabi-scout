#!/usr/bin/env python3
"""8A read-only Security Intelligence UAT on current direct equity holdings.

Uses persisted candidates, Participation snapshots, and Security Master only.
Does not enable Hybrid. Does not write.
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
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.wealth_portfolio_repository import WealthPortfolioRepository
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.security_identity_service import identity_service_from_security_master
from services.security_intelligence_service import (
    SecurityIntelligenceService,
    facts_from_candidate,
    participation_from_sources,
)
from services.security_master_service import production_security_master
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.universe_listing_identity import listing_identity
from services.wealth_core_service import WealthCoreService

US_TARGETS = ("AAPL", "AVGO", "CRM", "TSLA", "MRVL", "UPS")
_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})


class ReadOnlyGuard:
    def __init__(self, client: Any) -> None:
        self._client = client

    def table(self, name: str):
        return _ReadOnlyTable(self._client.table(name), name)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _ReadOnlyTable:
    def __init__(self, inner: Any, table_name: str):
        self._inner = inner
        self._table_name = table_name

    def __getattr__(self, name: str):
        if name in _WRITE_METHODS:
            def _blocked(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError(f"blocked write on {self._table_name}.{name}")

            return _blocked
        return getattr(self._inner, name)


def _user_id(client: Any) -> str:
    rows = (
        client.table("wealth_portfolios")
        .select("user_id")
        .eq("is_default", True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise RuntimeError("no default portfolio user")
    return str(rows[0]["user_id"])


def main() -> int:
    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    readonly = ReadOnlyGuard(raw)
    master = production_security_master(readonly)
    identity = identity_service_from_security_master(master)
    wealth = WealthCoreService(readonly, _user_id(raw))
    portfolio = WealthPortfolioRepository(readonly).get_default_for_user(wealth.user_id)
    if portfolio is None:
        raise RuntimeError("default portfolio missing")
    positions = wealth.list_positions()
    held = {
        listing_identity(row.get("symbol") or row.get("ticker"))
        for row in positions
        if listing_identity(row.get("symbol") or row.get("ticker"))
    }
    bist = sorted(
        symbol
        for symbol in held
        if symbol not in US_TARGETS and "." not in symbol and len(symbol) <= 6
        and master.resolve_security(symbol).exchange not in {"NYSE", "NASDAQ", "AMEX", ""}
    )
    # Only evaluate BIST when a persisted candidate already exists.
    candidates = {
        listing_identity(row.get("symbol")): row
        for row in (CandidateRepository(readonly).get_all(limit=5000) or [])
    }
    supported_bist = [symbol for symbol in bist if symbol in candidates]
    queue = {
        listing_identity(row.get("symbol")): row
        for row in UniverseExpansionRepository(readonly).list_all()
    }
    snaps = ParticipationAssessmentRepository(readonly).list_latest_by_symbol()
    service = SecurityIntelligenceService()
    report: dict[str, Any] = {
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "writes": 0,
        "provider_calls": 0,
        "holdings": {},
    }
    for symbol in (*US_TARGETS, *supported_bist):
        resolved = master.resolve_security(symbol)
        layer = identity.resolve_economic_layer([symbol]).economic_layer
        candidate = candidates.get(symbol)
        qrow = queue.get(symbol) or {}
        snap = snaps.get(symbol) or {}
        facts = facts_from_candidate(
            candidate,
            symbol=symbol,
            instrument_type=resolved.instrument_type,
            economic_layer=layer,
            stale=str((candidate or {}).get("freshness_status") or "").upper() == "STALE",
        )
        participation = participation_from_sources(
            queue_or_snapshot={**snap, **qrow},
            candidate=candidate,
            research_allowed=qrow.get("research_allowed"),
        )
        view = service.evaluate(facts, participation)
        report["holdings"][symbol] = {
            "held": symbol in held,
            "instrument_type": resolved.instrument_type,
            "economic_layer": layer,
            "candidate_present": candidate is not None,
            "data_completeness": view.data_quality.score,
            "missing_fields": list(facts.missing_fields),
            "participation": view.participation_status,
            "research_allowed": view.research_allowed,
            "quality": view.quality.to_dict(),
            "growth": view.growth.to_dict(),
            "profitability": view.profitability.to_dict(),
            "balance_sheet": view.balance_sheet.to_dict(),
            "valuation": view.valuation.to_dict(),
            "momentum": view.momentum.to_dict(),
            "risk": view.risk.to_dict(),
            "overall_score": view.overall_score,
            "overall_status": view.overall_status,
            "overall_confidence": view.overall_confidence,
            "investment_state": view.investment_state,
            "investable": view.investable,
            "strengths": list(view.strengths),
            "weaknesses": list(view.weaknesses),
            "risk_flags": list(view.risk_flags),
        }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
