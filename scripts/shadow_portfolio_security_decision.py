#!/usr/bin/env python3
"""8E.2 read-only production shadow. Never writes. No provider calls."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.security_intelligence_snapshot_repository import (
    SecurityIntelligenceSnapshotRepository,
)
from repositories.signal_intelligence_repository import SignalIntelligenceRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.wealth_portfolio_repository import WealthPortfolioRepository
from services.candidate_identity import select_canonical_candidate
from services.candidate_price_service import CandidatePriceService
from services.fund_holdings_service import FundHoldingsService
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_intelligence_helpers import iter_all_position_rows
from services.portfolio_security_context_builder import (
    PortfolioSecuritySourceBundle,
    aggregate_holding,
    build_portfolio_security_context,
    identity_from_security_master,
    load_persisted_si_snapshot,
    load_signal_context,
    resolve_economic_exposure_status,
)
from services.security_intelligence_contract import persisted_snapshot_is_stale
from services.portfolio_security_decision_contract import (
    DECISION_REDUCE,
    REASON_CONCENTRATION_LIMIT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_master_service import production_security_master
from services.signal_intelligence_service import SignalIntelligenceService
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.wealth_core_service import WealthCoreService

SHADOW_SYMBOLS = (
    "CRM",
    "AAPL",
    "AVGO",
    "MRVL",
    "TSLA",
    "UPS",
    "NVDA",
    "ADBE",
    "ADSK",
    "BIIB",
    "MU",
)
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


def _default_user_id(client: Any) -> str:
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


def _lookthrough_symbols(client: Any, fund_symbols: tuple[str, ...]) -> set[str]:
    service = FundHoldingsService(client)
    found: set[str] = set()
    for fund in fund_symbols:
        snapshot = service.get_snapshot(fund)
        holdings = getattr(snapshot, "holdings", None) if snapshot is not None else None
        rows = holdings if holdings is not None else []
        if snapshot is not None and not rows and hasattr(snapshot, "to_dict"):
            rows = (snapshot.to_dict() or {}).get("holdings") or []
        for row in rows:
            symbol = str(
                getattr(row, "underlying_symbol", None)
                or (row.get("underlying_symbol") if isinstance(row, dict) else "")
                or ""
            ).strip().upper()
            if symbol:
                found.add(symbol)
    return found


def main() -> int:
    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    client = ReadOnlyGuard(raw)
    user_id = _default_user_id(client)
    wealth = WealthCoreService(client, user_id)
    portfolio = WealthPortfolioRepository(client).get_default_for_user(user_id)
    if not portfolio:
        raise RuntimeError("default portfolio missing")
    view = PortfolioIntelligenceService(
        wealth,
        CandidatePriceService(client),
    ).build_view(portfolio, enrich_nabi=False)
    participation = ParticipationAssessmentRepository(client)
    queue = UniverseExpansionRepository(client)
    candidates = CandidateRepository(client)
    si_repo = SecurityIntelligenceSnapshotRepository(client)
    signals = SignalIntelligenceService(SignalIntelligenceRepository(client))
    master = production_security_master(client)
    economic_status = resolve_economic_exposure_status()
    lookthrough = _lookthrough_symbols(client, ("SPUS", "SPSK", "SPRE", "SPWO"))
    rows = []
    for symbol in SHADOW_SYMBOLS:
        resolution = master.resolve_security(symbol)
        instrument_type, sm_market = identity_from_security_master(resolution)
        candidate = select_canonical_candidate(candidates.list_by_symbol(symbol))
        qty, value, weight, holding_market = aggregate_holding(
            iter_all_position_rows(view), symbol
        )
        is_holding = qty is not None and qty > 0
        si_snapshot = load_persisted_si_snapshot(si_repo, symbol)
        bundle = PortfolioSecuritySourceBundle(
            snapshot=participation.get_latest(symbol),
            queue_row=queue.get_by_symbol(symbol),
            si_snapshot=si_snapshot,
            signal_context=load_signal_context(signals, symbol),
            candidate=candidate,
            instrument_type=instrument_type,
            market=holding_market or sm_market,
            quantity=qty,
            market_value=value,
            portfolio_weight=weight,
            economic_exposure_status=economic_status,
            lookthrough_only=symbol in lookthrough and not is_holding and candidate is None,
            as_of=None if si_snapshot is None else si_snapshot.as_of,
        )
        context = build_portfolio_security_context(symbol, bundle)
        before = evaluate_portfolio_security_decision(replace(context, stale_inputs=()))
        after = evaluate_portfolio_security_decision(context)
        event_count = len(signals.repo.list_events(symbol)) if signals.repo is not None else 0
        rows.append(
            {
                "symbol": symbol,
                "holding": context.is_holding,
                "portfolio_weight": context.portfolio_weight,
                "participation_status": context.participation_status,
                "research_allowed": context.research_allowed,
                "si_state": context.si_state,
                "si_as_of": context.si_as_of,
                "si_stale": persisted_snapshot_is_stale(si_snapshot),
                "si_score": context.si_score,
                "persisted_signal_events": event_count,
                "verified_material_negative": context.verified_material_negative,
                "verified_material_positive": context.verified_material_positive,
                "signal_conflict": context.signal_conflict,
                "latest_material_signal": context.latest_material_signal,
                "economic_exposure_status": context.economic_exposure_status,
                "candidate_exists": context.candidate_exists,
                "research_status": context.research_status,
                "decision_before_freshness_gate": before.decision,
                "decision_after_freshness_gate": after.decision,
                "decision": after.decision,
                "exposure_increase_allowed": after.exposure_increase_allowed,
                "blocking_reasons": list(after.blocking_reasons),
                "reason_codes": list(after.reason_codes),
                "missing_inputs": list(context.missing_inputs),
                "stale_inputs": list(context.stale_inputs),
                "research_status_unchanged": context.research_status,
            }
        )
    concentrated = [
        row
        for row in rows
        if row["holding"]
        and row["portfolio_weight"] is not None
        and row["portfolio_weight"] >= CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT
    ]
    reduce_from_concentration = [
        row["symbol"]
        for row in rows
        if row["decision"] == DECISION_REDUCE
        and row["blocking_reasons"] == [REASON_CONCENTRATION_LIMIT]
    ]
    print(
        json.dumps(
            {
                "persist": False,
                "provider_calls": 0,
                "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
                "price_source": "candidate_snapshot",
                "economic_exposure_status": economic_status,
                "concentration_ceiling_pct": CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
                "results": rows,
                "concentration_at_or_above_20": [row["symbol"] for row in concentrated],
                "reduce_solely_from_concentration": reduce_from_concentration,
                "signal_observation": {
                    "persisted_event_symbols": [
                        row["symbol"]
                        for row in rows
                        if row["persisted_signal_events"]
                    ],
                    "verified_material_negative": [
                        row["symbol"] for row in rows if row["verified_material_negative"]
                    ],
                    "verified_material_positive": [
                        row["symbol"] for row in rows if row["verified_material_positive"]
                    ],
                    "signal_conflict": [
                        row["symbol"] for row in rows if row["signal_conflict"]
                    ],
                    "context_for_unchanged": True,
                },
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
