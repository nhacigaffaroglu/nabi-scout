#!/usr/bin/env python3
"""Controlled SPRE economic-classification persist. Security Master only.

Does not enable hybrid. Does not change Participation. Does not write REIT
instrument_type. Does not rewrite fund snapshots.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.candidate_repository import CandidateRepository
from repositories.fund_holdings_repository import FundHoldingsRepository
from repositories.security_master_repository import SecurityMasterRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.wealth_portfolio_repository import WealthPortfolioRepository
from services.economic_classification_ingest import (
    persist_economic_ingest_plan,
    plan_spre_reit_economic_ingest,
)
from services.fund_holdings_service import FundHoldingsService
from services.hybrid_exposure_allocation_policy import (
    first_live_blocker,
    resolve_hybrid_allocation_policy,
)
from services.official_fund_holdings_client import OfficialFundHoldingsClient
from services.portfolio_allocation_policy_service import PortfolioAllocationPolicyService
from services.portfolio_economic_exposure import classify_instrument_exposure
from services.security_identity_service import identity_service_from_security_master
from services.security_master_listing_ingest import SecurityMasterWriteGuard
from services.security_master_service import production_security_master
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.wealth_goal_planning import planning_conversion
from services.wealth_new_money_allocation import allocate_new_money
from services.wealth_planning_fx import load_planning_fx_schedule

_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})


class ReadOnlyGuard:
    def __init__(self, client: Any) -> None:
        self._client = client

    def table(self, name: str):
        return _ReadOnlyTable(self._client.table(name), name)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _ReadOnlyTable:
    def __init__(self, inner: Any, table_name: str) -> None:
        self._inner = inner
        self._table_name = table_name

    def __getattr__(self, name: str):
        if name in _WRITE_METHODS:
            def _blocked(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError(f"blocked write on {self._table_name}.{name}")

            return _blocked
        return getattr(self._inner, name)


def _count(client: Any, table: str) -> int | None:
    try:
        response = client.table(table).select("id", count="exact").limit(1).execute()
        return int(getattr(response, "count", None) or 0)
    except Exception:
        return None


def _user_id(client: Any) -> str:
    user = getattr(getattr(client, "auth", None), "get_user", lambda: None)()
    uid = getattr(getattr(user, "user", None), "id", None)
    if uid:
        return str(uid)
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


def _invariants(client: Any, queue_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "queue": {
            "total": len(queue_rows),
            "status": dict(Counter(str(row.get("status") or "") for row in queue_rows)),
            "participation": dict(
                Counter(str(row.get("participation_status") or "") for row in queue_rows)
            ),
            "research_allowed": dict(
                Counter(str(row.get("research_allowed")) for row in queue_rows)
            ),
        },
        "security_master": _count(client, "security_master"),
        "fund_holdings": _count(client, "fund_holdings"),
        "fund_holdings_snapshots": _count(client, "fund_holdings_snapshots"),
        "investment_candidates": _count(client, "investment_candidates"),
        "wealth_portfolios": _count(client, "wealth_portfolios"),
        "wealth_adviser_goals": _count(client, "wealth_adviser_goals"),
        "wealth_transactions": _count(client, "wealth_transactions"),
    }


def _instrument_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(row.get("instrument_type") or "") for row in rows))


def _source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(row.get("source") or "") for row in rows))


def _portfolio_bundle(raw: Any, client: Any, user_id: str) -> dict[str, Any]:
    from services.candidate_price_service import CandidatePriceService
    from services.portfolio_intelligence_service import PortfolioIntelligenceService
    from services.wealth_core_service import WealthCoreService

    wealth = WealthCoreService(client, user_id)
    with patch.object(
        wealth,
        "ensure_default_portfolio",
        side_effect=RuntimeError("ensure_default_portfolio blocked"),
    ):
        portfolio = WealthPortfolioRepository(client).get_default_for_user(user_id)
        if portfolio is None:
            raise RuntimeError("default portfolio missing")
        intel = PortfolioIntelligenceService(wealth, CandidatePriceService(client))
        view = intel.build_view(portfolio, enrich_nabi=False)
        holdings_svc = FundHoldingsService(client)
        snapshots = {
            symbol: snap
            for symbol in ("SPUS", "SPSK", "SPRE", "SPWO")
            if (snap := holdings_svc.get_snapshot(symbol)) is not None
        }
        master = production_security_master(client)
        identity = identity_service_from_security_master(master)
        from services.portfolio_economic_exposure import build_economic_exposure

        exposure = build_economic_exposure(
            view,
            fund_snapshots=snapshots,
            assets=wealth.list_assets(),
            positions=wealth.list_positions(),
            security_master=master,
            identity_service=identity,
        )
    unknown = next((row for row in exposure.buckets if row.bucket_id == "unknown"), None)
    layers = {
        row.bucket_id: float(row.observable_weight_pct or 0.0) for row in exposure.buckets
    }
    contrib = {}
    total = float(exposure.observable_total_market_value or 0.0)
    if unknown is not None:
        for symbol in unknown.contributing_symbols:
            inst = next(
                (row for row in exposure.instruments if str(row.symbol).upper() == symbol),
                None,
            )
            if inst is None:
                continue
            unk_w = sum(
                float(item.weight_pct or 0.0)
                for item in inst.economic_exposures
                if item.exposure_bucket == "unknown"
            )
            contrib[symbol] = (
                round(float(inst.observable_market_value or 0.0) * unk_w / 100.0 / total * 100.0, 4)
                if total
                else 0.0
            )
    return {
        "wealth": wealth,
        "portfolio": portfolio,
        "view": view,
        "snapshots": snapshots,
        "master": master,
        "identity": identity,
        "exposure": exposure,
        "assets": wealth.list_assets(),
        "positions": wealth.list_positions(),
        "summary": {
            "id": portfolio.get("id"),
            "name": portfolio.get("name"),
            "mv": view.priced_total_market_value,
            "layers": layers,
            "unknown_contributors": contrib,
        },
    }


def _spre_lookthrough(client: Any, master: Any, identity: Any) -> dict[str, Any]:
    from services.fund_intelligence_contract import FundHoldingRow
    from services.portfolio_intelligence_contract import PositionValuationRow

    snap = FundHoldingsRepository(client).get_latest_snapshot("SPRE")
    holdings = FundHoldingsRepository(client).list_holdings(str(snap["id"])) if snap else []
    views = tuple(
        FundHoldingRow(
            underlying_symbol=row.get("underlying_symbol"),
            underlying_name=row.get("underlying_name"),
            weight_pct=row.get("weight_pct"),
            asset_type=row.get("asset_type"),
            participation_status=row.get("participation_status"),
            research_status=row.get("research_status"),
        )
        for row in holdings
    )
    snapshot = None
    if snap is not None:
        from services.fund_intelligence_contract import FundHoldingsSnapshotView

        snapshot = FundHoldingsSnapshotView(
            fund_symbol="SPRE",
            fund_type="etf",
            as_of=str(snap.get("as_of") or ""),
            source=str(snap.get("source") or ""),
            coverage_pct=float(snap.get("coverage_pct") or 0.0) or None,
            underlying_count=len(views),
            holdings=views,
            data_quality="good",
            limitation="",
        )
    etf = PositionValuationRow(
        position_id="x-SPRE",
        account_id="",
        asset_id="",
        symbol="SPRE",
        asset_class="etf",
        account_name="",
        quantity=1,
        average_cost=1,
        valuation_currency="USD",
        price=1,
        price_available=True,
        market_value=1,
        cost_basis=1,
        unrealized_pl=0,
        weight_pct=1,
        is_cash=False,
        included_in_base_totals=True,
    )
    view = classify_instrument_exposure(
        etf,
        fund_snapshots={"SPRE": snapshot} if snapshot is not None else {},
        security_master=master,
        identity_service=identity,
    )
    buckets = {row.exposure_bucket: float(row.weight_pct) for row in view.economic_exposures}
    return {
        "source": None if snap is None else snap.get("source"),
        "as_of": None if snap is None else snap.get("as_of"),
        "rows": len(holdings),
        "raw_weight": round(sum(float(row.get("weight_pct") or 0.0) for row in holdings), 4),
        "coverage_pct": None if snap is None else snap.get("coverage_pct"),
        "buckets": buckets,
        "total": round(sum(buckets.values()), 4),
        "tickers": [row.get("underlying_symbol") for row in holdings],
    }


def _participation(client: Any) -> dict[str, Any]:
    from config.participation_catalog import configured_participation_for_symbol

    candidates = CandidateRepository(client).get_all(limit=5000) or []
    spre = next(
        (row for row in candidates if str(row.get("symbol") or "").strip().upper() == "SPRE"),
        None,
    )
    queue = UniverseExpansionRepository(client).list_all()
    qrow = next(
        (row for row in queue if str(row.get("symbol") or "").strip().upper() == "SPRE"),
        None,
    )
    return {
        "catalog": configured_participation_for_symbol("SPRE"),
        "candidate": None if spre is None else spre.get("participation_status"),
        "queue": None if qrow is None else qrow.get("participation_status"),
    }


def _new_money(bundle: dict[str, Any], *, hybrid: bool) -> dict[str, Any]:
    from services.exposure_determinacy_diagnostics import eligible_fill_assets
    from services.portfolio_allocation_intelligence import (
        AllocationDimension,
        build_allocation_intelligence,
    )
    from services.wealth_new_money_allocation import _allocation_buckets_from_exposure

    wealth = bundle["wealth"]
    portfolio = bundle["portfolio"]
    view = bundle["view"]
    policy = PortfolioAllocationPolicyService(wealth.client, wealth.user_id).get_policy(
        str(portfolio.get("id") or "")
    )
    candidates = CandidateRepository(wealth.client).get_all(limit=5000) or []
    fx = load_planning_fx_schedule(wealth, str(portfolio.get("id") or ""))
    conversion = planning_conversion(fx.usdtry_for_year(date.today().year))
    plan = allocate_new_money(
        available_amount=Decimal("100000"),
        amount_currency="TRY",
        portfolio_view=view,
        policy=policy,
        candidates=candidates,
        conversion=conversion,
        assets=bundle["assets"],
        positions=bundle["positions"],
        fund_snapshots=bundle["snapshots"],
        security_master=bundle["master"],
        identity_service=bundle["identity"],
        enable_hybrid_exposure_allocation=True if hybrid else None,
    )
    fill_assets = eligible_fill_assets(
        bundle["exposure"].instruments,
        extra_symbols=candidates,
        assets=bundle["assets"],
    )
    intelligence = build_allocation_intelligence(
        view,
        policy=policy,
        assets=bundle["assets"],
        positions=bundle["positions"],
        exposure_buckets=_allocation_buckets_from_exposure(bundle["exposure"]),
        exposure_view=bundle["exposure"],
        candidates=list(candidates),
    )
    diagnostics = intelligence.exposure_diagnostics
    diag = diagnostics.to_dict() if diagnostics is not None else {}
    return {
        "hybrid_requested": hybrid,
        "hybrid_active": plan.hybrid_allocation_active,
        "production_hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "mode": plan.hybrid_portfolio_mode,
        "allocated": str(plan.total_allocated),
        "residual": str(plan.residual_cash),
        "limitations": list(plan.limitations),
        "blocker": first_live_blocker(plan.limitations),
        "robust_underweight": diag.get("robust_underweight_layers") or [],
        "fillable": diag.get("fillable_robust_underweight_layers") or [],
        "unfillable": diag.get("unfillable_robust_underweight_layers") or [],
        "eligible_fill": [row.to_dict() for row in fill_assets],
        "spre_fillable": any(row.symbol == "SPRE" for row in fill_assets),
        "dimension": getattr(policy, "primary_dimension", None)
        or (plan.primary_dimension if plan.primary_dimension else AllocationDimension.ECONOMIC_EXPOSURE.value),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    readonly = ReadOnlyGuard(raw)
    official = OfficialFundHoldingsClient().fetch("SPRE")
    existing = SecurityMasterRepository(readonly).list_all()
    plan = plan_spre_reit_economic_ingest(official.holdings, existing_rows=existing)
    report: dict[str, Any] = {
        "apply": args.apply,
        "official_rows": len(official.holdings),
        "official_weight": round(sum(item.weight_pct for item in official.holdings), 4),
        "exact": plan.exact,
        "ambiguous": plan.ambiguous,
        "unmapped": plan.unmapped,
        "write_gate": plan.write_gate,
        "write_gate_reasons": list(plan.write_gate_reasons),
        "planned": [row.to_dict() for row in plan.rows],
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
    }
    keys = {
        (str(row.get("identifier") or "").strip().upper(), str(row.get("identifier_type") or "").strip().upper())
        for row in existing
    }
    report["pre_existing_keys"] = [
        (fact.identifier, fact.identifier_type, fact.source)
        for fact in plan.facts
        if (fact.identifier, fact.identifier_type) in keys
    ]
    report["pre_instrument_counts"] = _instrument_counts(existing)
    report["pre_source_counts"] = _source_counts(existing)
    queue_rows = UniverseExpansionRepository(readonly).list_all()
    report["pre_invariants"] = _invariants(readonly, queue_rows)
    report["participation"] = _participation(readonly)

    writes = {"inserted": 0, "updated": 0, "unchanged": 0, "replay_inserted": 0, "replay_updated": 0}
    if args.apply:
        if plan.write_gate != "PASS":
            raise SystemExit(f"write gate failed: {plan.write_gate_reasons}")
        guard = SecurityMasterWriteGuard(raw)
        from services.security_master_service import SecurityMasterService

        live = SecurityMasterService(repo=SecurityMasterRepository(guard), include_canonical_static=False)
        first = persist_economic_ingest_plan(plan, security_master=live)
        writes["inserted"] = first.inserted
        writes["updated"] = first.updated
        writes["unchanged"] = first.unchanged
        after = SecurityMasterRepository(readonly).list_all()
        replay_plan = plan_spre_reit_economic_ingest(official.holdings, existing_rows=after)
        second = persist_economic_ingest_plan(replay_plan, security_master=live)
        writes["replay_inserted"] = second.inserted
        writes["replay_updated"] = second.updated
        writes["replay_unchanged"] = second.unchanged
        writes["replay_gate"] = replay_plan.write_gate
        writes["replay_actions"] = [row.action for row in replay_plan.rows]
        report["post_instrument_counts"] = _instrument_counts(after)
        report["post_source_counts"] = _source_counts(after)
        report["post_invariants"] = _invariants(readonly, UniverseExpansionRepository(readonly).list_all())
    report["writes"] = writes

    user_id = _user_id(raw)
    bundle = _portfolio_bundle(raw, readonly, user_id)
    report["portfolio"] = bundle["summary"]
    report["spre_lookthrough"] = _spre_lookthrough(readonly, bundle["master"], bundle["identity"])
    report["new_money_off"] = _new_money(bundle, hybrid=False)
    report["new_money_uat"] = _new_money(bundle, hybrid=True)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
