#!/usr/bin/env python3
"""8B read-only Security Intelligence UAT on current direct equity holdings.

Uses persisted candidates, Participation snapshots, Security Master,
and local SEC company-facts cache replay only.
Does not enable Hybrid. Does not write. Does not call FMP.
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
from services.security_facts_service import SecurityFactsService
from services.security_identity_service import identity_service_from_security_master
from services.security_intelligence_service import (
    SecurityIntelligenceService,
    participation_from_sources,
)
from services.security_intelligence_snapshot_service import snapshot_row_from_view
from services.security_master_service import production_security_master
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.universe_listing_identity import listing_identity
from services.wealth_core_service import WealthCoreService

US_TARGETS = ("AAPL", "AVGO", "CRM", "TSLA", "MRVL", "UPS")
BIST_AUDIT = ("BIMAS", "ASELS", "TUPRS")
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


def _payload_has_sec(snap: dict[str, Any]) -> bool:
    payload = snap.get("assessment_payload") or {}
    return bool(payload.get("sec_financials")) or bool(snap.get("sec_available"))


def _classify_gaps(facts, candidate, snap, cache_replayed: bool) -> dict[str, list[str]]:
    gaps = {
        "DATA_EXISTS_NOT_WIRED": [],
        "DATA_NOT_PERSISTED": [],
        "PLAN_RESTRICTED": [],
        "TRUE_MISSING": [],
        "UNSUPPORTED": [],
    }
    inputs = ((snap.get("assessment_payload") or {}).get("financial_inputs") or {})
    if facts.revenue is None and inputs.get("total_revenue") is not None:
        gaps["DATA_EXISTS_NOT_WIRED"].append("revenue")
    if not cache_replayed and not _payload_has_sec(snap) and facts.roic is None:
        gaps["DATA_NOT_PERSISTED"].append("sec_financials")
    if facts.return_1y is None and facts.return_3m is None:
        gaps["PLAN_RESTRICTED"].append("fmp_historical_price_eod_light")
        if not (candidate or {}).get("return_12m"):
            gaps["DATA_NOT_PERSISTED"].append("equity_returns")
    if facts.high_52w is None:
        gaps["DATA_NOT_PERSISTED"].append("high_52w")
    if facts.roic is None and facts.revenue is None:
        gaps["TRUE_MISSING"].append("fundamentals")
    return {key: value for key, value in gaps.items() if value}


def _bist_blockers(master, candidates, snaps, queue, symbol: str) -> dict[str, Any]:
    resolved = master.resolve_security(symbol)
    candidate = candidates.get(symbol)
    return {
        "identity": resolved.status,
        "instrument_type": resolved.instrument_type,
        "exchange": (resolved.facts[0].exchange if resolved.facts else "") or "",
        "candidate_present": candidate is not None,
        "participation_snapshot": symbol in snaps,
        "queue": bool(queue.get(symbol)),
        "blockers": [
            label
            for label, ok in (
                ("identity", resolved.status == "RESOLVED"),
                ("pricing", bool((candidate or {}).get("current_price"))),
                ("financials", bool((candidate or {}).get("revenue") or (candidate or {}).get("roic"))),
                ("Participation", symbol in snaps or bool(queue.get(symbol))),
                ("market_history", bool((candidate or {}).get("return_12m"))),
            )
            if not ok
        ],
    }


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
    candidates = {
        listing_identity(row.get("symbol")): row
        for row in (CandidateRepository(readonly).get_all(limit=5000) or [])
    }
    queue = {
        listing_identity(row.get("symbol")): row
        for row in UniverseExpansionRepository(readonly).list_all()
    }
    snaps = ParticipationAssessmentRepository(readonly).list_latest_by_symbol()
    facts_service = SecurityFactsService()
    service = SecurityIntelligenceService(facts_service)
    report: dict[str, Any] = {
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "writes": 0,
        "provider_calls": 0,
        "holdings": {},
        "bist_audit": {},
        "crm_reference": {},
        "sparse_case": {},
    }
    for symbol in US_TARGETS:
        resolved = master.resolve_security(symbol)
        layer = identity.resolve_economic_layer([symbol]).economic_layer
        candidate = candidates.get(symbol)
        qrow = queue.get(symbol) or {}
        snap = snaps.get(symbol) or {}
        built = facts_service.build_detailed(
            symbol,
            candidate=candidate,
            participation_snapshot=snap,
            security_resolution=resolved,
            instrument_type=resolved.instrument_type,
            economic_layer=layer,
            stale=str((candidate or {}).get("freshness_status") or "").upper() == "STALE",
            allow_sec_cache_replay=True,
        )
        report["provider_calls"] += built.provider_calls
        participation = participation_from_sources(
            queue_or_snapshot={**snap, **qrow},
            candidate=candidate,
            research_allowed=qrow.get("research_allowed"),
        )
        view = service.evaluate(built.facts, participation)
        dry = snapshot_row_from_view(view, as_of=built.facts.as_of)
        nabi = (candidate or {}).get("nabi_score")
        report["holdings"][symbol] = {
            "held": symbol in held,
            "instrument_type": resolved.instrument_type,
            "economic_layer": layer,
            "candidate_present": candidate is not None,
            "completeness": built.facts.completeness_pct,
            "freshness": built.facts.freshness_status,
            "authority": built.facts.authority_status,
            "period_compatibility": built.facts.period_compatibility,
            "sources_used": list(built.sources_used),
            "cache_replayed": built.cache_replayed,
            "missing_critical": list(built.facts.missing_critical_fields),
            "gaps": _classify_gaps(built.facts, candidate, snap, built.cache_replayed),
            "data_sources": {
                "SEC": "sec_extract_financials" in built.sources_used
                or "sec_company_facts_cache" in built.sources_used,
                "FMP": False,
                "Company_Intelligence": "company_intelligence" in built.sources_used,
                "price_history": built.facts.return_1y is not None or built.facts.return_3m is not None,
                "Participation": "participation_financial_inputs" in built.sources_used
                or bool(snap),
                "Security_Master": "security_master" in built.sources_used,
            },
            "participation": view.participation_status,
            "research_allowed": view.research_allowed,
            "quality": view.quality.to_dict(),
            "growth": view.growth.to_dict(),
            "profitability": view.profitability.to_dict(),
            "balance_sheet": view.balance_sheet.to_dict(),
            "valuation": view.valuation.to_dict(),
            "momentum": view.momentum.to_dict(),
            "risk": view.risk.to_dict(),
            "data_quality": view.data_quality.to_dict(),
            "overall_score": view.overall_score,
            "overall_status": view.overall_status,
            "overall_confidence": view.overall_confidence,
            "investment_state": view.investment_state,
            "investable": view.investable,
            "nabi_score_v4": nabi,
            "score_difference_reason": (
                "SI is security-intrinsic and fail-closed; NABI Score v4 is the "
                "Scanner candidate score and includes portfolio_fit/liquidity with "
                "missing metrics defaulting toward 50."
            ),
            "strengths": list(view.strengths),
            "weaknesses": list(view.weaknesses),
            "risk_flags": list(view.risk_flags),
            "snapshot_dry_run": {
                "symbol": dry.get("symbol"),
                "as_of_key": dry.get("as_of_key"),
                "facts_version": dry.get("facts_version"),
                "engine_version": dry.get("engine_version"),
            },
        }
        if symbol == "CRM":
            report["crm_reference"] = {
                "facts_as_of": built.facts.as_of,
                "completeness": built.facts.completeness_pct,
                "participation": view.participation_status,
                "research_allowed": view.research_allowed,
                "overall_score": view.overall_score,
                "overall_status": view.overall_status,
                "investment_state": view.investment_state,
                "forced_attractive": view.investment_state == "ATTRACTIVE"
                and view.overall_status not in {"STRONG", "VERY_STRONG"},
                "snapshot_dry_run": True,
                "company_report_path": "SecurityFactsService → SecurityIntelligenceService",
            }
        if symbol in {"TSLA", "MRVL", "UPS"} and not report["sparse_case"]:
            report["sparse_case"] = {
                "symbol": symbol,
                "missing_remains_missing": built.facts.roic is None or view.quality.score is None,
                "false_strengths": list(view.strengths) if view.quality.score is None else [],
                "completeness": built.facts.completeness_pct,
                "overall_score": view.overall_score,
            }
    for symbol in BIST_AUDIT:
        report["bist_audit"][symbol] = _bist_blockers(master, candidates, snaps, queue, symbol)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
